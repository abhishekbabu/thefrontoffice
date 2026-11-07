"""NBA on Yahoo.

Category-league basketball: the forward-looking number is games remaining in the
matchup period crossed with recent per-category form, and the budget constraint
is Yahoo's weekly add limit.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import requests
from yahoofantasy import League, Player, Team

from thefrontoffice.adapters.outbound.competitions import paging, places
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba.context import PlayerContextBuilder
from thefrontoffice.adapters.outbound.competitions.nba.form import PACIFIC, FormSource, PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    ASSISTS,
    CATEGORIES,
    POINTS,
    REBOUNDS,
    SCOUTED,
    Category,
)
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.sleeper.client import NBA, SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    LeagueNotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
)
from thefrontoffice.domain.models import (
    CompetitionContext,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    StandingRow,
    Stat,
    StatGroup,
    Summary,
    TeamRef,
    TradeProposal,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Enough to find somebody, few enough to read — and one Yahoo request rather
# than the eight the category scout makes.
AVAILABLE_BROWSE_LIMIT = 100

# Where the moves are actually made. Unlike the other two platforms these
# cannot be checked from here — the sport is behind an approval this app does
# not have — so they follow Yahoo's documented shape rather than a probe.
LEAGUE_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}"
TEAM_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}/{team_id}"

CARD_CATEGORIES = (POINTS, REBOUNDS, ASSISTS)
"""The categories a table row has room for; the drawer carries all nine."""

NO_FIGURE = "—"
"""What a table cell shows where there is no number. A zero would read as a
bad line rather than an absent one."""


def _recent(stats: PlayerStats | None, category: Category) -> str:
    """One category over the last fifteen games, or a dash where there is no figure.

    Out of season, and for a player who has not featured, there is no line to
    show; nor is there a percentage for a player who has attempted nothing.
    """
    value = ((stats or PlayerStats()).get("last_15") or {}).get(category.label)
    return category.show(value) if value is not None else NO_FIGURE


class YahooNBAProvider:
    """CompetitionProvider for Yahoo category-league basketball."""

    sport = "basketball"
    competition = "nba"
    label = "NBA (Yahoo)"

    @staticmethod
    def season_year(now: datetime | None = None) -> int:
        """The NBA season a date belongs to, which rolls over on 1 September,
        ahead of October's opening night.

        Read in Pacific time, like the rest of basketball: a local clock would
        put the night of 31 August in a different season depending on where
        the machine is.
        """
        moment = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
        return moment.year if moment.month >= 9 else moment.year - 1

    def __init__(
        self,
        league: League,
        *,
        all_leagues: list[League] | None = None,
        nba: FormSource,
        yahoo_for: Callable[[League], YahooSource],
        sleeper: SleeperProjectionSource,
        max_weekly_adds: int,
    ):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        `yahoo_for` rather than one client because a Yahoo client is bound to a
        league, and every call names the league it reads. `league` is the one
        read when a call names none.
        """
        self._default_league = league
        self._all_leagues = all_leagues or [league]
        self.nba = nba
        self._yahoo_for = yahoo_for
        self.max_weekly_adds = max_weekly_adds
        self.context_builder = PlayerContextBuilder(self.nba)
        self.sleeper = sleeper

    def list_leagues(self) -> list[LeagueRef]:
        """Every Yahoo NBA league this login is in."""
        return [
            LeagueRef(
                league_id=str(lg.id),
                name=str(lg.name),
                competition=self.competition,
                detail=str(getattr(lg, "league_type", "")),
                url=LEAGUE_URL.format(league_id=lg.id),
            )
            for lg in self._all_leagues
        ]

    def _yahoo(self, league_id: str) -> YahooSource:
        """A reader for `league_id`, or for the default league when it names none.

        Resolved on every call rather than remembered: a provider that moved
        itself between leagues answered each request from whichever league the
        previous one had asked for.
        """
        if not league_id:
            return self._yahoo_for(self._default_league)
        for lg in self._all_leagues:
            if str(lg.id) == str(league_id):
                return self._yahoo_for(lg)
        raise LeagueNotFoundError(f"Yahoo league {league_id} is not one of yours")

    def summary(self, league_id: str) -> Summary:
        """The header, without the free-agent pool or the model: the add budget.

        A category league has no lineup to set, so there is no side to show.
        """
        my_team = self._yahoo(league_id).get_user_team()
        return Summary(headline=_adds(my_team.roster_adds.value, self.max_weekly_adds))

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The league table, which is the only one of these Yahoo gives cheaply.

        A category league has no season of fixtures to list in the football
        sense, Yahoo publishes no real-world NBA schedule through this SDK, and
        there is no league-wide transaction feed on it either. Three empty
        sections is the honest answer, and each renders as nothing rather than
        as an empty promise.
        """
        yahoo = self._yahoo(league_id)
        standings = _standings(yahoo, yahoo.get_user_team())
        return LeagueSchedule(headline=_season(standings), standings=standings)

    def build_context(self, league_id: str = "") -> CompetitionContext:
        """Gather league state and render the scouting prompt.

        Returns the prompt plus the pieces that make it up, so a follow-up
        briefing can be assembled without re-deriving or re-sending everything.
        """
        yahoo = self._yahoo(league_id)
        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team)
        start, end = (week.start, week.end) if week else (None, None)
        used_adds, limit = my_team.roster_adds.value, self.max_weekly_adds

        # Gathered before the schedule so one bulk lookup covers every team
        # either of them touches.
        rostered = my_team.roster().players
        free_agents, annotations = _rank_free_agents(yahoo)
        logger.debug(f"Building context for {len(rostered)} rostered and {len(free_agents)} free agents")

        remaining_games: dict[str, int] = {}
        if start and end:
            teams = [p.editorial_team_abbr for p in (*rostered, *free_agents)]
            remaining_games = self.nba.get_remaining_games_bulk(teams, start, end)

        projections = self._projection_index(start, end)
        roster_lines = self.context_builder.build_player_lines(
            rostered, start, end, remaining_games=remaining_games, projections=projections
        )
        fa_lines = self.context_builder.build_player_lines(
            free_agents, start, end, annotations, remaining_games, projections=projections
        )

        schedule_context = prompt.schedule(week, remaining_games, projected=projections is not None)
        trans_context = prompt.transactions(used_adds, limit)
        return CompetitionContext(
            prompt=prompt.scout(
                roster="".join(roster_lines.values()),
                week=week,
                free_agents="".join(fa_lines.values()),
                schedule_context=schedule_context,
                trans_context=trans_context,
                adds_left=max(0, limit - used_adds),
            ),
            situation=prompt.matchup(week),
            constraints=trans_context,
            extra=schedule_context,
            roster_lines=roster_lines,
            candidate_lines=fa_lines,
            headline=_adds(used_adds, limit),
        )

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster."""
        yahoo = self._yahoo(league_id)
        giving, receiving = resolve_sides(proposal, lambda name: _find_player(yahoo, name))

        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team)

        # Roster context is enrichment: losing it degrades the prompt but must
        # not block the evaluation the user asked for. `players()` is the SDK's
        # own fetch, so it fails in requests' terms rather than ours.
        try:
            roster = self.context_builder.build_context_for_players(
                my_team.players(), week.start if week else None, week.end if week else None
            )
        except (FrontOfficeError, requests.RequestException) as e:
            logger.warning(f"Failed to build roster context for trade: {e}")
            roster = "(Roster data unavailable)"

        text = prompt.trade(
            giving=self.context_builder.build_context_for_players(giving),
            receiving=self.context_builder.build_context_for_players(receiving),
            week=week,
            roster=roster,
        )
        return CompetitionContext(prompt=text, situation=prompt.matchup(week))

    # ── players and teams ───────────────────────────────────────────

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, with recent form where Sleeper has it."""
        return self._cards(self._yahoo(league_id).get_user_team().players())

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        yahoo = self._yahoo(league_id)
        my_key = getattr(yahoo.get_user_team(), "team_key", object())
        refs = [
            TeamRef(
                team_id=str(getattr(team, "team_key", "")),
                name=str(getattr(team, "name", "")),
                detail=_record(getattr(getattr(team, "team_standings", None), "outcome_totals", None)),
                url=_team_url(str(getattr(team, "team_key", ""))),
                is_mine=getattr(team, "team_key", None) == my_key,
            )
            for team in yahoo.league.teams()
        ]
        return sorted([r for r in refs if r.team_id], key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's roster, in the same columns as your own."""
        teams = self._yahoo(league_id).league.teams()
        team = next((t for t in teams if str(getattr(t, "team_key", "")) == team_id), None)
        if team is None:
            raise TeamNotFoundError(team_id)
        return self._cards(team.players())

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds.

        Sorted by Yahoo's own season rank rather than by a category: a wire
        browsed one stat at a time is the scout's job, and this is the list you
        read when you just want to see who is out there.
        """
        ranked = self._cards(self._yahoo(league_id).fetch_available(AVAILABLE_BROWSE_LIMIT), slot_column=False)
        return paging.page(ranked, query)

    def _cards(self, players: Any, slot_column: bool = True) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows."""
        cards = []
        for player in players:
            name = str(player.name.full)
            status = str(getattr(player, "status", "") or "")
            stats = self.nba.get_player_stats(name)
            cards.append(
                PlayerCard(
                    player_id=str(player.player_key),
                    tone="warning" if status else "neutral",
                    columns={
                        "Player": name,
                        "Pos": str(player.display_position),
                        "Team": str(player.editorial_team_abbr),
                        # A free-agent list has no lineup to be in, so the
                        # column would be blank down its whole length.
                        **(
                            {"Slot": str(getattr(getattr(player, "selected_position", None), "position", ""))}
                            if slot_column
                            else {}
                        ),
                        **{c.label: _recent(stats, c) for c in CARD_CATEGORIES},
                        "Status": status,
                    },
                )
            )
        return cards

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, with their last-fifteen line where Sleeper has it."""
        player = next(
            (p for p in self._yahoo(league_id).get_user_team().players() if str(p.player_key) == player_id),
            None,
        )
        if player is None:
            raise PlayerNotFoundError([player_id])

        name = str(player.name.full)
        stats = self.nba.get_player_stats(name)
        status = str(getattr(player, "status", "") or "")
        points = _recent(stats, POINTS)
        return PlayerDetail(
            player_id=player_id,
            name=name,
            position=str(player.display_position),
            team=str(player.editorial_team_abbr),
            headline=points if points != NO_FIGURE else "",
            headline_label="points a game over the last 15" if points != NO_FIGURE else "No recent form on record",
            note=status,
            tone="warning" if status else "neutral",
            groups=[
                StatGroup(
                    title="Last 15",
                    stats=[Stat(label=c.label, value=_recent(stats, c)) for c in CATEGORIES],
                )
            ],
        )

    def _projection_index(self, start: date | None, end: date | None) -> ProjectionIndex | None:
        """Projected category totals for the matchup period, or None.

        Returns None rather than raising when projections are unavailable —
        Sleeper publishes none before opening night, and a scout report built
        from recent form alone is the behavior this had all along.
        """
        if start is None or end is None:
            return None
        try:
            state = self.sleeper.get_state(NBA)
            rows = self.sleeper.get_nba_projections(state.season, state.week)
            if not rows and state.week:
                # A matchup can straddle two Sleeper weeks near a boundary.
                rows = self.sleeper.get_nba_projections(state.season, state.week + 1)
            index = ProjectionIndex(rows, start, end)
        except FrontOfficeError as e:
            logger.warning(f"No NBA projections available, using recent form only: {e}")
            return None

        if index.is_empty:
            logger.info("Sleeper has no NBA projections for this period (out of season?)")
            return None
        logger.debug(f"Matched projections for {len(index)} players")
        return index


def _find_player(yahoo: YahooSource, name: str) -> Player | None:
    """The one Yahoo player a name refers to, or None — never a guess.

    Yahoo's search matches substrings, so a name can come back with others
    beside it, and an exact match among them wins. Failing any match, the
    surname alone tolerates first-name spelling ("Lebron" for "LeBron"), but
    only where it finds one player: two Williamses resolve to neither.
    """
    players = yahoo.search_players(name)
    parts = name.split()
    if not players and len(parts) > 1:
        players = yahoo.search_players(parts[-1])

    wanted = normalize_name(name)
    candidates = [p for p in players if normalize_name(str(p.name.full)) == wanted] or players
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning(f"{len(candidates)} players match {name!r}; resolving to none rather than guessing")
    return None


def _rank_free_agents(yahoo: YahooSource) -> tuple[list[Player], dict[str, str]]:
    """Top available players per category, deduplicated, most versatile first.

    A player leading several categories appears once, annotated with all of
    them, and ahead of single-category players — the ordering the prompt
    relies on when it asks for the three best adds.
    """
    leaders = yahoo.fetch_top_by_stat({c.label: c.yahoo_stat for c in SCOUTED}, per_stat=10)

    categories_by_key: dict[str, list[str]] = {}
    player_by_key: dict[str, Player] = {}
    for label, players in leaders.items():
        for p in players:
            key = str(p.player_key)
            if key not in categories_by_key:
                categories_by_key[key] = []
                player_by_key[key] = p
            categories_by_key[key].append(label)

    ranked = sorted(categories_by_key.items(), key=lambda kv: len(kv[1]), reverse=True)
    players = [player_by_key[key] for key, _ in ranked]
    annotations = {key: f"[Top in: {', '.join(cats)}]" for key, cats in ranked}
    return players, annotations


def _standings(yahoo: YahooSource, mine: Team) -> list[StandingRow]:
    """Read defensively: yahoofantasy sets these by setattr at runtime, so
    a team missing its standings block is a shape question, not an error."""
    rows: list[tuple[int, StandingRow]] = []
    for team in yahoo.league.teams():
        standings = getattr(team, "team_standings", None)
        if standings is None:
            continue
        rank = int(getattr(standings, "rank", 0) or 0)
        rows.append(
            (
                rank,
                StandingRow(
                    rank=rank,
                    name=str(getattr(team, "name", "")),
                    record=_record(getattr(standings, "outcome_totals", None)),
                    team_id=str(getattr(team, "team_key", "")),
                    points=str(getattr(standings, "points_for", "") or ""),
                    is_mine=getattr(team, "team_key", None) == getattr(mine, "team_key", object()),
                ),
            )
        )
    return [row for _, row in sorted(rows, key=lambda pair: pair[0])]


def _record(outcome: Any) -> str:
    if outcome is None:
        return ""
    wins = getattr(outcome, "wins", 0) or 0
    losses = getattr(outcome, "losses", 0) or 0
    ties = getattr(outcome, "ties", 0) or 0
    base = f"{wins}-{losses}"
    return f"{base}-{ties}" if ties else base


def _team_url(team_key: str) -> str:
    """A team's page on Yahoo, addressed the way Yahoo addresses it.

    A team key is `nba.l.<league>.t.<team>` and the URL wants the two
    numbers, not the key — so a key in an unexpected shape yields no link
    rather than a broken one.
    """
    parts = team_key.split(".")
    if len(parts) != 5 or parts[3] != "t":
        return ""
    return TEAM_URL.format(league_id=parts[2], team_id=parts[4])


def _adds(used: int, limit: int) -> list[Stat]:
    """The week's add budget, as what is left of it.

    The one figure the week turns on: an exhausted budget is the constraint
    the whole report bends around, turning every recommendation into a
    MONITOR, so it warns. The team's name is the page's title already, and
    the roster's size is My team's to say.
    """
    left = max(0, limit - used)
    return [Stat(label="Adds left", value=f"{left} of {limit}", tone="good" if left else "warning")]


def _season(standings: list[StandingRow]) -> list[Stat]:
    """Your record and where it puts you: the season in figures, at the head of the league view."""
    mine = next((row for row in standings if row.is_mine), None)
    if mine is None:
        return []
    stats = [Stat(label="Record", value=mine.record)] if mine.record else []
    if mine.rank:
        stats.append(Stat(label="Place", value=places.place(mine.rank, len(standings))))
    return stats
