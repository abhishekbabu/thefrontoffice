"""NBA on Yahoo.

Category-league basketball: the forward-looking number is games remaining in the
matchup period crossed with recent per-category form, and the budget constraint
is Yahoo's weekly add limit.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient

from yahoofantasy import League, Player  # type: ignore[import-untyped]

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.nba.context import PlayerContextBuilder
from thefrontoffice.adapters.outbound.competitions.nba.form import PACIFIC, SleeperNBAForm
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectionIndex
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient
from thefrontoffice.config.constants import NBA_SCOUT_PROMPT, NBA_TRADE_PROMPT
from thefrontoffice.config.settings import settings
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


NINE_CAT = ("PTS", "REB", "AST", "STL", "BLK", "3PTM", "FG%", "FT%", "TO")

# Enough to find somebody, few enough to read — and one Yahoo request rather
# than the eight the category scout makes.
AVAILABLE_BROWSE_LIMIT = 100

# Where the moves are actually made. Unlike the other two platforms these
# cannot be checked from here — the sport is behind an approval this app does
# not have — so they follow Yahoo's documented shape rather than a probe.
LEAGUE_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}"
TEAM_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}/{team_id}"
"""What a nine-category league is actually scored on, in the order it is read."""


NO_FIGURE = "—"
"""What a table cell shows where there is no number. A zero would read as a
bad line rather than an absent one."""


def _recent(stats: object, key: str) -> str:
    """One recent-form figure, or a dash when there is no line to show.

    Out of season, and for a player who has not featured, there is no line to
    show — and a zero would read as a bad one rather than an absent one.
    """
    line = getattr(stats, "last_15", None) if stats is not None else None
    value = (line or {}).get(key) if isinstance(line, dict) else None
    return f"{value:.1f}" if isinstance(value, int | float) else NO_FIGURE


class YahooNBAProvider:
    """CompetitionProvider for Yahoo category-league basketball."""

    sport = "basketball"
    competition = "nba"
    label = "NBA (Yahoo)"

    @staticmethod
    def season_year(now: datetime | None = None) -> int:
        """The NBA season a date belongs to. Seasons start in October.

        Read in Pacific time, like the rest of basketball: a local clock would
        put the night of 31 August in a different season depending on where
        the machine is.
        """
        from datetime import datetime as _dt

        moment = (now or _dt.now(PACIFIC)).astimezone(PACIFIC)
        return moment.year if moment.month >= 9 else moment.year - 1

    def __init__(
        self,
        league: League,
        *,
        all_leagues: list[League] | None = None,
        nba: SleeperNBAForm | None = None,
        yahoo: YahooClient | None = None,
        sleeper: SleeperClient | None = None,
    ):
        """Collaborators default to real clients; pass them in to test or reuse."""
        self.league = league
        self._all_leagues = all_leagues or [league]
        self.nba = nba or SleeperNBAForm()
        self.yahoo = yahoo or YahooClient(league)
        self.context_builder = PlayerContextBuilder(self.nba)
        # Two questions, one platform: Yahoo says who is on the roster, and
        # Sleeper says both what they have been doing and what they are
        # expected to do.
        self._sleeper = sleeper

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

    def _select(self, league_id: str) -> League:
        """The league object for `league_id`, defaulting to the current one."""
        if not league_id:
            return self.league
        for lg in self._all_leagues:
            if str(lg.id) == str(league_id):
                return lg
        raise LeagueNotFoundError(f"Yahoo league {league_id} is not one of yours")

    def _select_into(self, league_id: str) -> None:
        """Point this provider at `league_id`, if it is not there already."""
        league = self._select(league_id)
        if league is not self.league:
            self.league = league
            self.yahoo = YahooClient(league)

    def summary(self, league_id: str) -> Summary:
        """The header, without the free-agent pool or the model.

        Only the roster and the add budget. Yahoo hands the matchup back as
        prose it has already rendered, so there is nothing structured to lift
        out of it without parsing what the model is meant to read — and a
        category league has no lineup to set, so there is no side to show.
        """
        my_team = self.yahoo.get_user_team()
        used = my_team.roster_adds.value
        limit = settings.yahoo_max_weekly_adds
        remaining = max(0, limit - used)
        return Summary(
            headline=[
                Stat(label="Team", value=str(my_team.name)),
                Stat(label="Roster", value=str(len(list(my_team.players())))),
                Stat(label="Adds used", value=f"{used}/{limit}"),
                Stat(label="Adds left", value=str(remaining), tone="good" if remaining else "warning"),
            ]
        )

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The league table, which is the only one of these Yahoo gives cheaply.

        A category league has no season of fixtures to list in the football
        sense, Yahoo publishes no real-world NBA schedule through this SDK, and
        there is no league-wide transaction feed on it either. Three empty
        sections is the honest answer, and each renders as nothing rather than
        as an empty promise.
        """
        self._select_into(league_id)
        mine = self.yahoo.get_user_team()
        return LeagueSchedule(standings=self._standings(mine))

    def _standings(self, mine: Any) -> list[StandingRow]:
        """Read defensively: yahoofantasy sets these by setattr at runtime, so
        a team missing its standings block is a shape question, not an error."""
        rows: list[tuple[int, StandingRow]] = []
        for team in self.yahoo.league.teams():
            standings = getattr(team, "team_standings", None)
            if standings is None:
                continue
            outcome = getattr(standings, "outcome_totals", None)
            rank = int(getattr(standings, "rank", 0) or 0)
            rows.append(
                (
                    rank,
                    StandingRow(
                        rank=rank,
                        name=str(getattr(team, "name", "")),
                        record=self._record(outcome),
                        team_id=str(getattr(team, "team_key", "")),
                        points=str(getattr(standings, "points_for", "") or ""),
                        is_mine=getattr(team, "team_key", None) == getattr(mine, "team_key", object()),
                    ),
                )
            )
        return [row for _, row in sorted(rows, key=lambda pair: pair[0])]

    @staticmethod
    def _record(outcome: Any) -> str:
        if outcome is None:
            return ""
        wins = getattr(outcome, "wins", 0) or 0
        losses = getattr(outcome, "losses", 0) or 0
        ties = getattr(outcome, "ties", 0) or 0
        base = f"{wins}-{losses}"
        return f"{base}-{ties}" if ties else base

    def build_context(self, league_id: str = "") -> CompetitionContext:
        """Gather league state and render the scouting prompt."""
        self._select_into(league_id)
        return self._build_context()

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster."""
        self._select_into(league_id)

        giving, receiving = resolve_sides(proposal, self._find_player)
        giving_str = self.context_builder.build_context_for_players(giving)
        receiving_str = self.context_builder.build_context_for_players(receiving)

        my_team = self.yahoo.get_user_team()
        matchup = self.yahoo.get_matchup(my_team)

        # Roster context is enrichment: losing it degrades the prompt but must
        # not block the evaluation the user asked for.
        try:
            start = date.fromisoformat(matchup.week_start) if matchup.has_dates else None
            end = date.fromisoformat(matchup.week_end) if matchup.has_dates else None
            roster_str = self.context_builder.build_context_for_players(my_team.players(), start, end)
        except Exception as e:
            logger.warning(f"Failed to build roster context for trade: {e}")
            roster_str = "(Roster data unavailable)"

        prompt = NBA_TRADE_PROMPT.format(
            giving_str=giving_str,
            receiving_str=receiving_str,
            matchup_context=matchup.context,
            roster_str=roster_str,
        )
        return CompetitionContext(prompt=prompt, situation=matchup.context)

    def _find_player(self, name: str) -> Player | None:
        """The Yahoo player a name refers to, or None."""
        players = self.yahoo.search_players(name)

        if not players:
            # The surname alone tolerates casing and first-name spelling
            # differences ("Lebron" vs "LeBron").
            parts = name.split()
            if len(parts) > 1:
                players = self.yahoo.search_players(parts[-1])

        if not players:
            return None
        if len(players) > 1:
            logger.warning(f"{len(players)} matches for {name!r}; using {players[0].name.full!r}")
        return players[0]

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, with recent form where Sleeper has it."""
        return self._cards(self.yahoo.get_user_team().players())

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        self._select_into(league_id)
        mine = self.yahoo.get_user_team()
        my_key = getattr(mine, "team_key", object())
        refs = [
            TeamRef(
                team_id=str(getattr(team, "team_key", "")),
                name=str(getattr(team, "name", "")),
                detail=self._record(getattr(getattr(team, "team_standings", None), "outcome_totals", None)),
                url=self._team_url(str(getattr(team, "team_key", ""))),
                is_mine=getattr(team, "team_key", None) == my_key,
            )
            for team in self.yahoo.league.teams()
        ]
        return sorted([r for r in refs if r.team_id], key=lambda ref: (not ref.is_mine, ref.name.lower()))

    @staticmethod
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

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's roster, in the same columns as your own."""
        self._select_into(league_id)
        team = next((t for t in self.yahoo.league.teams() if str(getattr(t, "team_key", "")) == team_id), None)
        if team is None:
            raise TeamNotFoundError(team_id)
        return self._cards(team.players())

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds.

        Sorted by Yahoo's own season rank rather than by a category: a wire
        browsed one stat at a time is the scout's job, and this is the list you
        read when you just want to see who is out there.
        """
        self._select_into(league_id)
        ranked = self._cards(self.yahoo.fetch_available(AVAILABLE_BROWSE_LIMIT), slot_column=False)
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
                        "PTS": _recent(stats, "PTS"),
                        "REB": _recent(stats, "REB"),
                        "AST": _recent(stats, "AST"),
                        "Status": status,
                    },
                )
            )
        return cards

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, with their last-fifteen line where Sleeper has it."""
        player = next(
            (p for p in self.yahoo.get_user_team().players() if str(p.player_key) == player_id),
            None,
        )
        if player is None:
            raise PlayerNotFoundError([player_id])

        name = str(player.name.full)
        stats = self.nba.get_player_stats(name)
        status = str(getattr(player, "status", "") or "")
        return PlayerDetail(
            player_id=player_id,
            name=name,
            position=str(player.display_position),
            team=str(player.editorial_team_abbr),
            headline=_recent(stats, "PTS").replace(NO_FIGURE, ""),
            headline_label=(
                "points a game over the last 15" if _recent(stats, "PTS") != NO_FIGURE else "No recent form on record"
            ),
            note=status,
            tone="warning" if status else "neutral",
            groups=[
                StatGroup(
                    title="Last 15",
                    stats=[Stat(label=key, value=_recent(stats, key)) for key in NINE_CAT],
                )
            ],
        )

    @property
    def sleeper(self) -> SleeperClient:
        """Lazily constructed — no credentials needed, but no reason to build it
        until a report is actually run."""
        if self._sleeper is None:
            from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperClient

            self._sleeper = SleeperClient()
        return self._sleeper

    def _projection_index(self, start: date | None, end: date | None) -> ProjectionIndex | None:
        """Projected category totals for the matchup period, or None.

        Returns None rather than raising when projections are unavailable —
        Sleeper publishes none before opening night, and a scout report built
        from recent form alone is the behavior this had all along.
        """
        if start is None or end is None:
            return None
        try:
            state = self.sleeper.get_state("nba")
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

    def _build_context(self) -> CompetitionContext:
        """Gather all data and build the initial AI prompt.

        Returns the prompt plus the pieces that make it up, so a follow-up
        briefing can be assembled without re-deriving or re-sending everything.
        """
        my_team = self.yahoo.get_user_team()

        # One matchup fetch supplies both the context block and the dates.
        matchup = self.yahoo.get_matchup(my_team)
        matchup_start: date | None = None
        matchup_end: date | None = None
        if matchup.has_dates:
            matchup_start = date.fromisoformat(matchup.week_start)
            matchup_end = date.fromisoformat(matchup.week_end)

        used_adds = my_team.roster_adds.value
        limit = settings.yahoo_max_weekly_adds
        remaining_adds = max(0, limit - used_adds)
        trans_context = (
            f"TRANSACTION CONTEXT:\n- Adds Used: {used_adds}/{limit}\n"
            f"- Remaining Adds: {remaining_adds}\n"
            "- NOTE: Prioritize aggressive streaming if adds are high, "
            "or conservative quality pickups if adds are low."
        )
        if remaining_adds > 0:
            recommendation_instructions = "Recommend **3 players** to add from the Free Agents list."
        else:
            recommendation_instructions = (
                "You have **0 adds remaining**. You CANNOT add players. Instead, identify "
                "**3 players to MONITOR** for next week who fit the team's needs."
            )

        # Gathered before the schedule so one bulk lookup covers every team
        # either of them touches.
        players_list = my_team.roster().players if hasattr(my_team, "roster") else my_team.players()
        fa_players, fa_annotations = self._rank_free_agents()
        logger.debug(f"Building context for {len(players_list)} rostered and {len(fa_players)} free agents")

        remaining_games: dict[str, int] = {}
        if matchup_start and matchup_end:
            teams = [p.editorial_team_abbr for p in (*players_list, *fa_players)]
            remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        projections = self._projection_index(matchup_start, matchup_end)
        roster_lines = self.context_builder.build_player_lines(
            players_list,
            matchup_start,
            matchup_end,
            remaining_games=remaining_games,
            projections=projections,
        )
        fa_lines = self.context_builder.build_player_lines(
            fa_players,
            matchup_start,
            matchup_end,
            fa_annotations,
            remaining_games,
            projections=projections,
        )

        # Schedule summary, from the counts already in hand.
        schedule_context = ""
        if remaining_games:
            rows = "".join(
                f"- {team}: {count} games left\n"
                for team, count in sorted(remaining_games.items(), key=lambda x: x[1], reverse=True)
            )
            schedule_context = (
                f"MATCHUP PERIOD: {matchup.week_start} to {matchup.week_end}\nREMAINING GAMES BY TEAM:\n{rows}"
            )

        projection_note = (
            "PROJECTIONS: lines marked PROJ carry projected totals for this matchup period — "
            "games, then the nine categories. Prefer them to recent form when the two disagree, "
            "since they already account for the schedule and expected minutes.\n"
            "- The bracketed [NG left] is how many games the player's TEAM has left. The PROJ "
            "game count is how many that PLAYER is expected to play. A player whose PROJ count "
            "is lower than his team's is expected to miss games — treat the gap as a warning, "
            "not a contradiction.\n"
            if projections is not None
            else "PROJECTIONS: unavailable for this period. Reason from recent form and games "
            "remaining, and say so rather than implying a forecast.\n"
        )
        schedule_context = projection_note + schedule_context

        prompt = NBA_SCOUT_PROMPT.format(
            roster_str="".join(roster_lines.values()),
            matchup_context=matchup.context,
            fas_str="".join(fa_lines.values()),
            schedule_context=schedule_context,
            trans_context=trans_context,
            recommendation_instructions=recommendation_instructions,
        )

        return CompetitionContext(
            prompt=prompt,
            situation=matchup.context,
            constraints=trans_context,
            extra=schedule_context,
            roster_lines=roster_lines,
            candidate_lines=fa_lines,
            headline=[
                Stat(label="Team", value=str(my_team.name)),
                Stat(label="Roster", value=str(len(roster_lines))),
                Stat(label="Adds used", value=f"{used_adds}/{limit}"),
                # An exhausted add budget is the constraint the whole report
                # bends around — it turns every recommendation into a MONITOR.
                Stat(
                    label="Adds left",
                    value=str(remaining_adds),
                    tone="good" if remaining_adds else "warning",
                ),
            ],
        )

    def _rank_free_agents(self) -> tuple[list[Player], dict[str, str]]:
        """Top available players per category, deduplicated, most versatile first.

        A player leading several categories appears once, annotated with all of
        them, and ahead of single-category players — the ordering the prompt
        relies on when it asks for the three best adds.
        """
        stat_leaders = self.yahoo.fetch_top_by_stat(per_stat=10)

        categories_by_key: dict[str, list[str]] = {}
        player_by_key: dict[str, Player] = {}
        for stat_name, players in stat_leaders.items():
            for p in players:
                # player_key comes off the untyped SDK object.
                key = str(p.player_key)
                if key not in categories_by_key:
                    categories_by_key[key] = []
                    player_by_key[key] = p
                categories_by_key[key].append(stat_name)

        ranked = sorted(categories_by_key.items(), key=lambda kv: len(kv[1]), reverse=True)
        players = [player_by_key[key] for key, _ in ranked]
        annotations = {key: f"[Top in: {', '.join(cats)}]" for key, cats in ranked}
        return players, annotations
