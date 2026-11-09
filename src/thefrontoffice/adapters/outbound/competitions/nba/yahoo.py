"""NBA on Yahoo.

Category-league basketball: the forward-looking number is games remaining in the
matchup period crossed with recent per-category form, and the budget constraint
is Yahoo's weekly add limit.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime

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
    ruled_out,
    stranded,
)
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooLeagueSource
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague, YahooPlayer, YahooTeam
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    LeagueNotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
)
from thefrontoffice.domain.models import (
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Action,
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


def _figure(stats: PlayerStats | None, category: Category) -> float | None:
    """One category over the last fifteen games, or None where there is no figure.

    Out of season, and for a player who has not featured, there is no line to
    show; nor is there a percentage for a player who has attempted nothing.
    """
    return ((stats or PlayerStats()).get("last_15") or {}).get(category.label)


def _recent(stats: PlayerStats | None, category: Category) -> str:
    """That figure as a cell reads it, or a dash where there is none."""
    value = _figure(stats, category)
    return category.show(value) if value is not None else NO_FIGURE


class YahooNBAProvider:
    """CompetitionProvider for Yahoo category-league basketball."""

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
        *,
        auth: YahooLeagueSource,
        yahoo_for: Callable[[YahooLeague], YahooSource],
        nba: FormSource,
        sleeper: SleeperProjectionSource,
        max_weekly_adds: int,
    ):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        `yahoo_for` rather than one client because a Yahoo client is bound to a
        league, and every call names the league it reads.
        """
        self._auth = auth
        self._yahoo_for = yahoo_for
        self.nba = nba
        self.sleeper = sleeper
        self.max_weekly_adds = max_weekly_adds
        self.context_builder = PlayerContextBuilder(self.nba)
        self._found: list[YahooLeague] | None = None

    def _leagues(self) -> list[YahooLeague]:
        """This season's leagues, found once per provider: the first is read when a call names none.

        Raises:
            LeagueNotFoundError: the login plays in no NBA league this season.
        """
        if self._found is None:
            self._found = self._auth.find_leagues("nba", self.season_year())
        if not self._found:
            raise LeagueNotFoundError("no Yahoo NBA leagues for this season")
        return self._found

    def list_leagues(self) -> list[LeagueRef]:
        """Every Yahoo NBA league this login is in."""
        return [
            LeagueRef(
                league_id=lg.league_key,
                name=lg.name,
                detail=lg.league_type,
                url=_league_url(lg.league_key),
            )
            for lg in self._leagues()
        ]

    def _yahoo(self, league_id: str) -> YahooSource:
        """A reader for `league_id`, or for the first league when it names none.

        Resolved on every call rather than remembered: a provider that moved
        itself between leagues answered each request from whichever league the
        previous one had asked for.
        """
        leagues = self._leagues()
        if not league_id:
            return self._yahoo_for(leagues[0])
        for lg in leagues:
            if lg.league_key == league_id:
                return self._yahoo_for(lg)
        raise LeagueNotFoundError(f"Yahoo league {league_id} is not one of yours")

    def summary(self, league_id: str) -> Summary:
        """The header, without the free-agent pool or the model: the add budget.

        A category league has no lineup to set, so there is no side to show. The one
        to-do item it computes is a player an injured slot no longer takes; with none,
        there is no list, rather than an empty one claiming there is nothing to do.
        """
        yahoo = self._yahoo(league_id)
        my_team = yahoo.get_user_team()
        stuck = _off_il(yahoo.roster(my_team.team_key))
        return Summary(headline=_adds(my_team.adds_used, self.max_weekly_adds), actions=stuck or None)

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The league table, which is the only one of these Yahoo gives cheaply.

        A category league has no season of fixtures to list in the football
        sense, Yahoo publishes no real-world NBA schedule through this SDK, and
        there is no league-wide transaction feed on it either. Three empty
        sections is the honest answer, and each renders as nothing rather than
        as an empty promise.
        """
        yahoo = self._yahoo(league_id)
        standings = _standings(yahoo.teams())
        mine = next((row for row in standings if row.is_mine), None)
        headline = places.season(mine.record, mine.rank, len(standings)) if mine else []
        return LeagueSchedule(headline=headline, standings=standings)

    def build_context(self, league_id: str = "") -> CompetitionContext:
        """Gather league state and render the scouting prompt.

        Returns the prompt plus the pieces that make it up, so a follow-up
        briefing can be assembled without re-deriving or re-sending everything.
        """
        yahoo = self._yahoo(league_id)
        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team.team_key)
        start, end = (week.start, week.end) if week else (None, None)
        used_adds, limit = my_team.adds_used, self.max_weekly_adds

        # Gathered before the schedule so one bulk lookup covers every team
        # either of them touches.
        rostered = yahoo.roster(my_team.team_key)
        free_agents, annotations = _rank_free_agents(yahoo)
        logger.debug(f"Building context for {len(rostered)} rostered and {len(free_agents)} free agents")

        remaining_games: dict[str, int] = {}
        if start and end:
            teams = [p.team for p in (*rostered, *free_agents)]
            remaining_games = self.nba.get_remaining_games_bulk(teams, start, end)

        projections = self._projection_index(start, end)
        roster_lines = self.context_builder.build_player_lines(
            rostered, start, end, remaining_games=remaining_games, projections=projections
        )
        fa_lines = self.context_builder.build_player_lines(
            free_agents, start, end, annotations, remaining_games, projections=projections
        )

        schedule_context = prompt.schedule(week, remaining_games, projected=projections is not None)
        stuck = _off_il(rostered)
        trans_context = prompt.transactions(used_adds, limit) + "".join(f"\n- {item.reason}" for item in stuck)
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
            tasks=stuck,
            # A kept judgment's add of somebody another manager has since claimed is no move at all.
            movable=frozenset(p.name for p in (*rostered, *free_agents)),
        )

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster."""
        yahoo = self._yahoo(league_id)
        giving, receiving = resolve_sides(proposal, lambda name: _find_player(yahoo, name))

        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team.team_key)

        # Not enrichment: a trade is judged against the roster it changes, and
        # one judged without it is an answer to a different question.
        roster = self.context_builder.build_player_lines(
            yahoo.roster(my_team.team_key), week.start if week else None, week.end if week else None
        )

        text = prompt.trade(
            giving=self.context_builder.build_context_for_players(giving),
            receiving=self.context_builder.build_context_for_players(receiving),
            week=week,
            roster="".join(roster.values()),
        )
        return CompetitionContext(prompt=text, situation=prompt.matchup(week), roster_lines=roster)

    # ── players and teams ───────────────────────────────────────────

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, with recent form where Sleeper has it."""
        yahoo = self._yahoo(league_id)
        return self._cards(yahoo.roster(yahoo.get_user_team().team_key))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        refs = [
            TeamRef(
                team_id=team.team_key,
                name=team.name,
                detail=team.standing.record if team.standing else "",
                url=_team_url(team.team_key),
                is_mine=team.is_mine,
            )
            for team in self._yahoo(league_id).teams()
        ]
        return sorted([r for r in refs if r.team_id], key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's roster, in the same columns as your own."""
        yahoo = self._yahoo(league_id)
        if not any(t.team_key == team_id for t in yahoo.teams()):
            raise TeamNotFoundError(team_id)
        return self._cards(yahoo.roster(team_id))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds.

        Sorted by Yahoo's own season rank rather than by a category: a wire
        browsed one stat at a time is the scout's job, and this is the list you
        read when you just want to see who is out there.
        """
        ranked = self._cards(self._yahoo(league_id).fetch_available(AVAILABLE_BROWSE_LIMIT))
        return paging.page(ranked, query)

    def _cards(self, players: list[YahooPlayer]) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows.

        The lineup slot is a column only where somebody holds one: on the wire
        nobody does, and the column would be blank down its whole length.
        """
        slotted = any(p.slot for p in players)
        cards = []
        for player in players:
            stats = self.nba.get_player_stats(player.name)
            cards.append(
                PlayerCard(
                    player_id=player.player_key,
                    ruled_out=ruled_out(player.status),
                    values={c.label: value for c in CARD_CATEGORIES if (value := _figure(stats, c)) is not None},
                    columns={
                        PLAYER_COLUMN: player.name,
                        POSITION_COLUMN: player.position,
                        "Team": player.team,
                        **({SLOT_COLUMN: player.slot} if slotted else {}),
                        **{c.label: _recent(stats, c) for c in CARD_CATEGORIES},
                        STATUS_COLUMN: player.status,
                    },
                )
            )
        return cards

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """Any player in the league — yours, a rival's or a free agent — with their last-fifteen line where Sleeper has it."""
        found = self._yahoo(league_id).players([player_id])
        if not found:
            raise PlayerNotFoundError([player_id])
        player = found[0]

        stats = self.nba.get_player_stats(player.name)
        points = _recent(stats, POINTS)
        return PlayerDetail(
            player_id=player_id,
            name=player.name,
            position=player.position,
            team=player.team,
            headline=points if points != NO_FIGURE else "",
            headline_label="points a game over the last 15" if points != NO_FIGURE else "No recent form on record",
            note=player.status,
            tone="warning" if player.status else "neutral",
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
            state = self.sleeper.get_nba_state()
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


def _find_player(yahoo: YahooSource, name: str) -> YahooPlayer | None:
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
    candidates = [p for p in players if normalize_name(p.name) == wanted] or players
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning(f"{len(candidates)} players match {name!r}; resolving to none rather than guessing")
    return None


def _rank_free_agents(yahoo: YahooSource) -> tuple[list[YahooPlayer], dict[str, str]]:
    """Top available players per category, deduplicated, most versatile first.

    A player leading several categories appears once, annotated with all of
    them, and ahead of single-category players — the ordering the prompt
    relies on when it asks for the three best adds.
    """
    leaders = yahoo.fetch_top_by_stat({c.label: c.yahoo_stat for c in SCOUTED}, per_stat=10)

    categories_by_key: dict[str, list[str]] = {}
    player_by_key: dict[str, YahooPlayer] = {}
    for label, players in leaders.items():
        for p in players:
            key = p.player_key
            if key not in categories_by_key:
                categories_by_key[key] = []
                player_by_key[key] = p
            categories_by_key[key].append(label)

    ranked = sorted(categories_by_key.items(), key=lambda kv: len(kv[1]), reverse=True)
    players = [player_by_key[key] for key, _ in ranked]
    annotations = {key: f"[Top in: {', '.join(cats)}]" for key, cats in ranked}
    return players, annotations


def _standings(teams: list[YahooTeam]) -> list[StandingRow]:
    """The table in rank order; a team Yahoo sent without its standings has no row in it."""
    rows = [
        StandingRow(
            rank=team.standing.rank,
            name=team.name,
            record=team.standing.record,
            team_id=team.team_key,
            points=team.standing.points_for,
            is_mine=team.is_mine,
        )
        for team in teams
        if team.standing is not None
    ]
    return sorted(rows, key=lambda row: row.rank)


def _league_url(league_key: str) -> str:
    """A league's page on Yahoo: `<game>.l.<league>` addressed by its number."""
    numbers = _key_numbers(league_key, "l")
    return LEAGUE_URL.format(league_id=numbers[0]) if numbers else ""


def _team_url(team_key: str) -> str:
    """A team's page on Yahoo: `<game>.l.<league>.t.<team>` addressed by its two numbers."""
    numbers = _key_numbers(team_key, "l", "t")
    return TEAM_URL.format(league_id=numbers[0], team_id=numbers[1]) if numbers else ""


def _key_numbers(key: str, *kinds: str) -> list[str]:
    """The number after each of `kinds` in a Yahoo key; empty for a key in any other shape.

    A URL wants the numbers, not the key — so a key in an unexpected shape
    yields no link rather than a broken one.
    """
    parts = key.split(".")
    if len(parts) != 1 + 2 * len(kinds) or tuple(parts[1::2]) != kinds:
        return []
    return parts[2::2]


def _off_il(roster: list[YahooPlayer]) -> list[Action]:
    """Each player held in an injured slot his status no longer qualifies him for.

    Yahoo holds every add while one sits there, so it comes before any other
    move. Activating him needs an active roster spot, which may mean a drop.
    """
    items = []
    for player in roster:
        if not stranded(player.slot, player.status):
            continue
        status = f"listed {player.status}" if player.status else "cleared to play"
        items.append(
            Action(
                kind="lineup",
                urgency="now",
                title=f"Move {player.name} off {player.slot}",
                reason=(
                    f"{player.name} is {status}, which Yahoo's {player.slot} slot does not take, and Yahoo "
                    "holds every add until he leaves it. Activating him needs an open roster spot."
                ),
                when="before any other move",
                player_id=player.player_key,
                key=f"il:{player.player_key}:{player.status.upper() or 'ACTIVE'}",
            )
        )
    return items


def _adds(used: int, limit: int) -> list[Stat]:
    """The week's add budget, as what is left of it.

    The one figure the week turns on: an exhausted budget is the constraint
    the whole report bends around, turning every recommendation into a
    MONITOR, so it warns. The team's name is the page's title already, and
    the roster's size is My team's to say.
    """
    left = max(0, limit - used)
    return [Stat(label="Adds left", value=f"{left} of {limit}", tone="good" if left else "warning")]
