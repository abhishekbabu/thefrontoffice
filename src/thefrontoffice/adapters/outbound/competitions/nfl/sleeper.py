"""NFL on Sleeper.

Points-scoring football: the forward-looking number is Sleeper's own weekly
projection in the league's scoring currency, and the binding constraints are the
starting lineup slots rather than a transaction budget.

Unlike the Yahoo path there is no OAuth — Sleeper's API is public, so a username
is the only configuration.

The port, and the gathering of a week: everything else is a role beside it —
`week.py` (state, the live scoreboard), `views.py` (how a player reads),
`actions.py` (the to-do list), `forecast.py` (the matchup simulated),
`league.py` (the season), `outlook.py` and `market.py` (the weeks ahead and
the trades), `prompt.py` (what a model reads).
"""

import logging
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nfl import (
    actions,
    evidence,
    injuries,
    league,
    market,
    news,
    outlook,
    prompt,
    tuning,
    views,
)
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.forecast import Forecasts, seed
from thefrontoffice.adapters.outbound.competitions.nfl.league import season_end
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    current_lineup,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    FREE_AGENT,
    Game,
    Phase,
    PlayerInfo,
    Projection,
    Trending,
    active,
    fielded,
    let_go,
)
from thefrontoffice.adapters.outbound.competitions.nfl.rules import (
    FANTASY_POSITIONS,
    SEASON_WEEKS,
    ruled_out,
    scoring_label,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Live,
    Scoreboard,
    Week,
    counted,
    pairings,
    projections_for,
    team_name,
    week_dates,
    weeks_played,
    zero_projection,
)
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    SleeperLeague,
    SleeperMatchup,
    SleeperRoster,
)
from thefrontoffice.domain.errors import (
    LeagueNotFoundError,
    NotFoundError,
    PlatformError,
    PlayerNotFoundError,
    TeamNotFoundError,
)
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    LeagueSchedule,
    MatchupInput,
    Outcomes,
    Outlook,
    PlayedMatchup,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    RangeSearch,
    SeasonInput,
    Side,
    Summary,
    TeamRef,
    TradeMarket,
    TradeProposal,
    WeekRange,
    outcome,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Where the moves are actually made. Sleeper routes on these — an invented
# path 404s — so they are addresses rather than guesses.
LEAGUE_URL = "https://sleeper.com/leagues/{league_id}"
PLAYER_URL = "https://sleeper.com/players/nfl/{player_id}"

# Sleeper serves portraits off its own CDN, keyed by the same player_id the
# rest of the API uses, with no key and no lookup.
PORTRAIT_URL = "https://sleepercdn.com/content/nfl/players/{player_id}.jpg"
# Lowercase or it 404s, where a club's abbreviation is upper everywhere else.
TEAM_LOGO_URL = "https://sleepercdn.com/images/team_logos/nfl/{team}.png"


class SleeperNFLProvider:
    """CompetitionProvider for Sleeper points-league football."""

    def __init__(self, username: str, *, client: SleeperNFLSource, espn: ESPNSource):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        The username is required: whether one is set, and what to set when it
        is not, is the registry entry's to say before this is ever built.
        """
        self.username = username
        self.client = client
        self.espn = espn
        self.scoreboard = Scoreboard(client, espn)
        self.forecasts = Forecasts(client)
        self._user_id: str | None = None
        # One request's week, kept for that request: the summary and the
        # forecast beside it both need it, and gathering it is most of the wait.
        self._weeks: dict[tuple[str, int | None], Week] = {}

    # ── leagues ─────────────────────────────────────────────────────

    def _resolve_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        self._user_id = self.client.get_user(self.username).user_id
        return self._user_id

    def list_leagues(self) -> list[LeagueRef]:
        leagues = self.client.get_leagues(self._resolve_user_id(), self.client.get_nfl_state().season)
        return [
            LeagueRef(
                league_id=lg.league_id,
                name=lg.name,
                detail=f"{lg.total_rosters}-team · {scoring_label(lg.scoring_format)}",
                url=LEAGUE_URL.format(league_id=lg.league_id),
            )
            for lg in leagues
        ]

    def _league(self, league_id: str, season: str) -> SleeperLeague:
        for lg in self.client.get_leagues(self._resolve_user_id(), season):
            if lg.league_id == league_id:
                return lg
        raise LeagueNotFoundError(f"league {league_id} is not one of yours this season")

    def _this_season(self, league_id: str) -> SleeperLeague:
        return self._league(league_id, self.client.get_nfl_state().season)

    def _mine(self, rosters: Sequence[SleeperRoster], league_id: str) -> SleeperRoster:
        user_id = self._resolve_user_id()
        for roster in rosters:
            if roster.owner_id == user_id:
                return roster
        raise LeagueNotFoundError(f"you do not own a roster in league {league_id}")

    @staticmethod
    def _signable(state: Week) -> Callable[[str], bool]:
        """Whether a player could be added at all, by id — the wire's own rule, for those who look ahead."""
        return lambda pid: (meta := state.players.get(pid)) is not None and views.is_signing(meta)

    # ── players ─────────────────────────────────────────────────────

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The full roster, with the depth and experience a week view leaves out."""
        state = self._week(league_id)
        return views.cards(
            state, views.lineup_order(state, state.roster), state.starter_ids, reserve=views.held(state.roster)
        )

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first. Records only, so no week is gathered for it."""
        self._this_season(league_id)
        rosters = self.client.get_rosters(league_id)
        mine = self._mine(rosters, league_id)
        names = self.client.get_league_users(league_id)
        refs = [
            TeamRef(
                team_id=str(r.roster_id),
                name=team_name(names, r),
                detail=f"{r.record} · {r.points_for:.2f} pts",
                is_mine=r.roster_id == mine.roster_id,
            )
            for r in rosters
        ]
        return sorted(refs, key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own."""
        state = self._week(league_id)
        roster = next((r for r in state.rosters if str(r.roster_id) == team_id), None)
        if roster is None:
            raise TeamNotFoundError(f"roster {team_id}")
        return views.cards(
            state, views.lineup_order(state, roster), set(roster.starter_ids), reserve=views.held(roster)
        )

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """Everyone nobody in the league holds, best projection first.

        The catalog is twelve thousand players and all but a couple of hundred
        are free, so the pool is cut to the positions a fantasy league actually
        scores — the rest is practice-squad depth nobody is deciding about.
        That still leaves four thousand, which is why this is a page.
        """
        state = self._week(league_id)
        available = [
            (state.projections.get(pid), pid, meta)
            for pid, meta in state.players.items()
            if pid not in state.owned and views.is_signing(meta)
        ]
        # Ranked on the projection, and among the unprojected on depth chart —
        # a starter with no projection yet is worth more than a fourth-stringer.
        available.sort(key=lambda row: (-(row[0].points if row[0] else 0.0), row[2].depth_chart_order or 99))
        ranked = views.cards(state, [pid for _, pid, _ in available], starters=set(), wire=True)
        return paging.page(ranked, query)

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player: the week, what makes the projection, and who they are."""
        state = self._week(league_id)
        detail = views.detail(self.client, state, player_id, self.scoreboard.schedule(state.season))
        return detail.model_copy(
            update={
                "url": PLAYER_URL.format(player_id=player_id),
                "team_logo_url": TEAM_LOGO_URL.format(team=detail.team.lower()) if detail.team != FREE_AGENT else "",
                # A team defense has no headshot — the CDN 404s on its abbreviation —
                # and the crest beside the club name already says who it is.
                "image_url": "" if detail.position == "DEF" else PORTRAIT_URL.format(player_id=player_id),
            }
        )

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster, on the same week every other view reads."""
        state = self._week(league_id)
        index = self._name_index(state.projections, state.players)
        giving, receiving = resolve_sides(proposal, index.lookup)

        return prompt.trade(state, giving, receiving)

    # ── the wire ────────────────────────────────────────────────────

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        """The prompt asking for one call per listed free agent.

        Each candidate carries what every player line carries — projection,
        role, matchup, news — plus how he fits this lineup, and the id the
        call has to name. The roster beside them is who could make way.

        Raises:
            PlayerNotFoundError: an id is rostered in this league, or unknown.
        """
        state = self._week(league_id)
        unavailable = [pid for pid in player_ids if pid in state.owned or pid not in state.players]
        if unavailable:
            raise PlayerNotFoundError(unavailable)

        candidates = {p.player_id: p for p in projections_for(player_ids, state.projections, state.players)}
        fits = {pid: fit[1] for pid, p in candidates.items() if (fit := views.fit(state, p))}
        return prompt.wire(state, candidates, fits)

    @staticmethod
    def _name_index(projections: Mapping[str, Projection], players: Mapping[str, PlayerInfo]) -> NameIndex[Projection]:
        """Every projectable player, looked up by the name a user would type."""
        index: NameIndex[Projection] = NameIndex()
        for projection in projections.values():
            index.add(projection.name, projection)
        # Players with no projection are still tradeable — a bye, or a stash.
        for player_id, meta in players.items():
            if player_id not in projections and meta.position:
                index.add(meta.name, zero_projection(player_id, meta))
        return index

    # ── the week ────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather the week, then render it as the text a model reads.

        Carries the same to-do list the page shows, numbered, so the model
        judges the moves somebody is looking at rather than inventing its own.
        """
        state = self._week(league_id)
        context = prompt.build(state, [item.action for item in self._tasks(state)], self._trending())
        context.movable = self._movable(state)
        return context

    def _movable(self, state: Week) -> frozenset[str]:
        """Who a move could still name: yours outside IR and taxi, and anyone unowned, before their kickoff."""
        started = self.scoreboard.started(state)
        mine = set(active(state.roster))
        return frozenset(
            meta.name
            for pid, meta in state.players.items()
            if (pid in mine or pid not in state.owned) and meta.team not in started
        )

    def _trending(self) -> Sequence[Trending] | None:
        """Who the crowd is adding; None where it will not load — an independent signal, not load-bearing."""
        try:
            return self.client.get_trending("add", lookback_hours=prompt.TRENDING_HOURS, limit=prompt.TRENDING_LIMIT)
        except PlatformError as e:
            logger.warning(f"Skipping trending players: {e}")
            return None

    @staticmethod
    def _current_week(phase: Phase) -> int:
        """The week the report is about; the opener while still in preseason."""
        return max(1, phase.week if phase.is_regular_season else 1)

    def _week(self, league_id: str, browse: int | None = None) -> Week:
        """The week being played, or the one `browse` names, gathered once per provider — which is once per request."""
        key = (league_id, browse)
        if key not in self._weeks:
            self._weeks[key] = self._gather_week(league_id, browse)
        return self._weeks[key]

    def _gather_week(self, league_id: str, browse: int | None = None) -> Week:
        """Everything both the header and the prompt are derived from.

        Gathered once because the two would otherwise fetch the same
        projections and re-run the same lineup solve, and could then disagree
        about the totals by a rounding.

        With `browse`, another week of the season: one played with the rosters
        and lineups that played it, one to come with each roster's best lineup
        on that week's projections. Neither carries the evidence or the news,
        which only the week being played's to-do list and prompt read.
        """
        phase = self.client.get_nfl_state()
        current, season = self._current_week(phase), phase.season
        league = self._league(league_id, season)
        matchups = self._matchups(league_id, current)
        rosters = self.client.get_rosters(league_id)
        if self._played_out(phase, current):
            rosters = banked(rosters, matchups, current, league)
            current += 1
            matchups = self._matchups(league_id, current)

        week = current if browse is None else browse
        if browse is not None and not 1 <= browse <= max(season_end(league), current):
            raise NotFoundError(f"week {week} of the {season} season")
        if week != current:
            matchups = self._matchups(league_id, week)
        if week > current and league.playoff_week_start and week >= league.playoff_week_start:
            # Sleeper fills the bracket weeks with placeholder pairings until the
            # regular season ends; a name there is not who you will play.
            matchups = []
        if week < current:
            rosters = as_played(rosters, matchups)
        rosters = with_lineups(rosters, matchups)

        catalog = self.client.get_nfl_players()
        designations = self._designations(catalog)
        players = injuries.catalog(catalog, designations, lambda meta, status: replace(meta, injury_status=status))
        published = self.client.get_projections(
            season, week, league.scoring_format, FANTASY_POSITIONS, league.scoring_rules
        )
        projections = {pid: counted(p) for pid, p in injuries.reported(published, designations).items()}
        if week > current:
            # Sleeper copies a roster's standing lineup into weeks to come, a dropped
            # player and all: what a week ahead holds is the best each roster can field.
            rosters = best_lineups(rosters, league.starting_slots, projections, players)
        roster = self._mine(rosters, league_id)
        browsing = week != current
        projected = projections_for(fielded(roster), projections, players)
        # Nobody starts from an injured-reserve or taxi slot without a move first.
        startable = projections_for([*active(roster), *let_go(roster)], projections, players)

        slots = league.starting_slots
        lineup = current_lineup(slots, roster.starter_ids, projected)
        best = optimal_lineup(slots, startable)
        current_points = round(lineup_points(lineup), 2)
        best_points = round(lineup_points(best), 2)

        return Week(
            evidence=evidence.Evidence()
            if browsing
            else self._evidence(season, week, league, phase.is_regular_season, players),
            news=news.PlayerNews() if browsing else self._news(catalog),
            current=current if browsing else 0,
            is_regular_season=phase.is_regular_season,
            league=league,
            roster=roster,
            rosters=rosters,
            names=self.client.get_league_users(league_id),
            matchups=matchups,
            week=week,
            season=season,
            projections=projections,
            players=players,
            projected=projected,
            lineup=lineup,
            best=best,
            changes=lineup_changes(slots, roster.starter_ids, startable),
            current_points=current_points,
            best_points=best_points,
            on_bench=round(best_points - current_points, 2),
        )

    def _matchups(self, league_id: str, week: int) -> list[SleeperMatchup]:
        """The week's head-to-heads; none where they will not load, which leaves the week without an opponent."""
        try:
            return self.client.get_matchups(league_id, week)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without the week's matchups, so its opponent, live score and lineups: {e}")
            return []

    def _played_out(self, phase: Phase, week: int) -> bool:
        """Whether the week Sleeper calls current has nothing left to play.

        Sleeper moves on a day or two after the last game — once Monday night is
        over, the week a manager is setting is the next one, and a page still on
        the finished week answers a question nobody can act on.
        """
        return phase.is_regular_season and week < SEASON_WEEKS and self.scoreboard.over(phase.season, week)

    def _evidence(
        self, season: str, week: int, league: SleeperLeague, is_regular_season: bool, players: Mapping[str, PlayerMeta]
    ) -> evidence.Evidence:
        """Roles and matchups from every week finished so far that loads."""
        played = weeks_played(week, is_regular_season)
        if not played:
            return evidence.Evidence()
        scoring = league.scoring_format
        lines = evidence.season_lines(
            self.client.get_nfl_game_lines(season, played, FANTASY_POSITIONS, scoring, league.scoring_rules).values
        )
        out = {pid for pid, meta in players.items() if ruled_out(meta.injury_status)}
        return evidence.gather(lines, scoring, out)

    def _designations(self, players: dict[str, PlayerMeta]) -> dict[str, str]:
        """Each player's designation as ESPN's injury report has it now, where it names him."""
        try:
            reports = self.espn.get_injuries(espn.NFL)
        except ESPNAPIError as e:
            # Sleeper's own designations stand: older, but still a designation.
            logger.warning(f"Continuing on Sleeper's injury designations alone: {e}")
            return {}
        return injuries.designations(reports, players)

    def _news(self, players: dict[str, PlayerMeta]) -> news.PlayerNews:
        """Recent articles about every player, from each club's own feed."""
        clubs = sorted({espn_club(m.team) for m in players.values() if m.team != FREE_AGENT})
        try:
            feeds = self.espn.get_team_news(espn.NFL, clubs)
        except ESPNAPIError as e:
            # Enrichment, like the evidence: the week stands without it.
            logger.warning(f"Continuing without player news: {e}")
            return news.PlayerNews()
        return news.attach(feeds, players, datetime.now(UTC))

    def summary(self, league_id: str) -> Summary:
        """The week as it stands: both lineups and the to-do list, which carries the swaps. No model."""
        state = self._week(league_id)
        return self._summary(state, [item.action for item in self._with_short_week(state, self._tasks(state))])

    def week_of(self, league_id: str, week: int) -> Summary:
        """Any week of the season as it was played or as it projects: both lineups, and no to-do list."""
        return self._summary(self._week(league_id, week), None)

    def _summary(self, state: Week, to_do: list[Action] | None) -> Summary:
        live = self.scoreboard.live(state)
        # The bench as the page shows it, reserve slots included and marked.
        sitting = sorted(state.sitting, key=lambda p: -p.points)
        # No fixture notes: a bye is on the player's own row, and on the to-do
        # list when it costs a starter, so a list of clubs would say it twice.
        return Summary(
            headline=prompt.headline(state),
            mine=Side(
                name="Your lineup",
                detail=state.roster.record,
                points=views.side_total(state, live),
                lineup=[
                    views.released(views.lineup_spot(slot, state.scheduled, live), state.roster)
                    for slot in state.lineup
                ],
                bench=[views.reserved(views.spot(p, state.scheduled, live=live), state.roster) for p in sitting],
            ),
            opponent=self._opponent(state, live),
            actions=to_do,
            window=self._window(state, self.scoreboard.games(state)),
            weeks=WeekRange(
                week=state.week,
                current=state.current or state.week,
                first=1,
                last=max(season_end(state.league), state.current or state.week),
            ),
        )

    def _tasks(self, state: Week) -> list[actions.Item]:
        """The week's to-do list, each item with what it is about."""
        return actions.build(
            state,
            self.scoreboard.games(state),
            self.scoreboard.started(state),
            actions.wire(state, self._signable(state)),
        )

    def _with_short_week(self, state: Week, listed: list[actions.Item]) -> list[actions.Item]:
        """The list with next week flagged where byes and injuries leave it short, in place of its bye items."""
        try:
            ahead = outlook.build(self.client, state, self.scoreboard.schedule(state.season), self._signable(state))
        except SleeperAPIError as e:
            logger.warning(f"Continuing without the weeks ahead: {e}")
            return listed
        short = outlook.to_do(ahead, state)
        if short is None:
            return listed
        return [item for item in listed if item.move != "bye"] + [short]

    def _window(self, state: Week, games: Mapping[int, Sequence[Game]]) -> str:
        """Which week, and when it is actually played.

        A week with no dates on it is a number, and the number is the one thing
        somebody already knows.
        """
        span = week_dates(games.get(state.week, []))
        return f"Week {state.week} · {span}" if span else f"Week {state.week}"

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, this week's real games, and what the league did."""
        state = self._week(league_id)
        return league.build(self.client, state, self.scoreboard.schedule(state.season))

    def _opponent(self, state: Week, live: Live) -> Side | None:
        """The team you are playing, and what they are starting; None on a bye or an unpaired week."""
        if state.matchup is None or state.opponent is None:
            return None
        return views.opponent_side(state, state.opponent, state.matchup[1].points, live)

    # ── the matchup, simulated ──────────────────────────────────────

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        """This week's matchup, ready to simulate; None where there is no opponent to play.

        With `candidates`, the moves priced are every legal start of each of
        those free agents rather than the bench's swaps and the to-do list's pickups.
        """
        state = self._week(league_id)
        if state.opponent is None:
            return None
        seeded = seed(league_id, state.week)
        if candidates:
            return self.forecasts.wire(state, self.scoreboard, state.opponent, candidates, seeded)
        return self.forecasts.matchup(state, self.scoreboard, state.opponent, self._tasks(state), seeded)

    def played_week(self, league_id: str, week: int) -> tuning.PlayedWeek:
        """A finished week's players, for scoring ranges: what was known before it, and what each scored."""
        return self.forecasts.played_week(self._this_season(league_id), week)

    def range_search(self) -> RangeSearch:
        return tuning.SEARCH

    def ranged_games(
        self, league_id: str, weeks: Sequence[int], candidates: Sequence[Mapping[str, float]]
    ) -> list[list[tuple[Outcomes, float]]]:
        """Every player-game of `weeks` under each of `candidates`, each week read once."""
        played = [self.played_week(league_id, week) for week in weeks]
        return [tuning.ranged(played, candidate) for candidate in candidates]

    def played_weeks(self, league_id: str) -> list[int]:
        """Every finished week but the first, which has no games before it to shape a range."""
        return list(range(2, self.client.get_nfl_state().week))

    def played_matchups(
        self, league_id: str, week: int, settings: Mapping[str, float] | None = None
    ) -> list[PlayedMatchup]:
        """Every matchup of `week`, rebuilt as it stood before kickoff, with how it ended.

        Args:
            settings: searched settings to range players with in place of the app's own.
        """
        return self.forecasts.played_matchups(
            self._this_season(league_id),
            week,
            tuning.settings(settings or {}),
            lambda matchup_id: seed(league_id, week, matchup_id),
        )

    # ── the season ──────────────────────────────────────────────────

    def _season_seed(self, league_id: str, state: Week) -> int:
        """The same season simulation all week, for the same league."""
        return seed(league_id, "season", state.week)

    def season_input(self, league_id: str) -> SeasonInput | None:
        """The rest of the regular season, ready to simulate to the playoffs."""
        state = self._week(league_id)
        return league.season_input(self.client, state, seed=self._season_seed(league_id, state))

    def weeks_ahead(self, league_id: str) -> Outlook:
        """The next few weeks as your roster stands, with a pickup for any that byes and injuries leave short."""
        state = self._week(league_id)
        return outlook.build(self.client, state, self.scoreboard.schedule(state.season), self._signable(state))

    def trade_market(self, league_id: str) -> TradeMarket | None:
        """The rest of the season, with the one-for-one trades that would help both lineups."""
        state = self._week(league_id)
        return market.build(self.client, state, seed=self._season_seed(league_id, state))


# ── the week's teams ────────────────────────────────────────────────────


def with_lineups(rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup]) -> list[SleeperRoster]:
    """Every team, each starting the lineup it set for this week.

    A roster's own `starters` lags: Sleeper can keep serving the lineup as
    it stood days after the manager changed it, while the week's matchup
    already carries the new one. So the lineup is read from there, and
    from the roster only for a team with no matchup this week.
    """
    lineups = {entry.roster_id: entry.starters for entry in matchups if entry.starters}
    return [
        replace(roster, starter_ids=list(lineups[roster.roster_id])) if roster.roster_id in lineups else roster
        for roster in rosters
    ]


def banked(
    rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup], week: int, league: SleeperLeague
) -> list[SleeperRoster]:
    """The records with a finished week counted, where Sleeper has not counted it yet.

    Sleeper settles a week's results a day or so after its last game, and the
    page moves on before then: without this the table, and every simulation
    standing on it, would lose a week of wins. Whether Sleeper has counted it is
    read off the records themselves — a week each, two in a league that also
    plays its median — since they arrive in the same response that would carry it.
    A playoff week is never counted: the records are the regular season's.
    """
    per_week = 2 if league.median_game else 1
    if (league.playoff_week_start and week >= league.playoff_week_start) or any(
        r.wins + r.losses + r.ties >= week * per_week for r in rosters
    ):
        return list(rosters)
    sides = {mine.roster_id: (mine, theirs) for a, b in pairings(matchups) for mine, theirs in ((a, b), (b, a))}
    scores = [entry.points for entry in matchups]
    middle = statistics.median(scores) if league.median_game and scores else None
    counted: list[SleeperRoster] = []
    for roster in rosters:
        side = sides.get(roster.roster_id)
        if side is None:
            counted.append(roster)
            continue
        mine, theirs = side
        results = [outcome(mine.points, theirs.points)]
        if middle is not None:
            results.append(outcome(mine.points, middle))
        counted.append(
            replace(
                roster,
                wins=roster.wins + results.count("won"),
                losses=roster.losses + results.count("lost"),
                ties=roster.ties + results.count("drawn"),
                points_for=round(roster.points_for + mine.points, 2),
            )
        )
    return counted


def as_played(rosters: Sequence[SleeperRoster], matchups: Sequence[SleeperMatchup]) -> list[SleeperRoster]:
    """Every team holding who it held that week, which its matchup keeps after a drop or a trade.

    A team the week's matchups do not name keeps the roster it holds now.
    """
    held = {entry.roster_id: entry.players for entry in matchups if entry.players}
    return [
        replace(
            roster,
            player_ids=list(held[roster.roster_id]),
            reserve_ids=[pid for pid in roster.reserve_ids if pid in held[roster.roster_id]],
            ir_ids=[pid for pid in roster.ir_ids if pid in held[roster.roster_id]],
        )
        if roster.roster_id in held
        else roster
        for roster in rosters
    ]


def best_lineups(
    rosters: Sequence[SleeperRoster],
    slots: list[str],
    projections: Mapping[str, Projection],
    players: Mapping[str, PlayerInfo],
) -> list[SleeperRoster]:
    """Every team starting the best lineup its roster makes on these projections, slot by slot."""
    return [
        replace(
            roster,
            starter_ids=[
                slot.player.player_id if slot.player else ""
                for slot in optimal_lineup(slots, projections_for(active(roster), projections, players))
            ],
        )
        for roster in rosters
    ]
