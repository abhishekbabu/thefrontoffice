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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nfl import (
    actions,
    evidence,
    league,
    market,
    news,
    outcomes,
    outlook,
    prompt,
    views,
)
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nfl.forecast import Forecasts, seed
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    current_lineup,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    SCORING_LABELS,
    Scoreboard,
    Week,
    opponent_entry,
    projection_for,
    week_dates,
    zero_projection,
)
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.client import NFL, SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.config.constants import NFL_TRADE_PROMPT, NFL_WIRE_PROMPT
from thefrontoffice.domain.errors import LeagueNotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    LeagueSchedule,
    MatchupInput,
    PlayedMatchup,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    SeasonInput,
    Side,
    Summary,
    Swap,
    TeamRef,
    TradeMarket,
    TradeProposal,
    WeekAhead,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Where the moves are actually made. Sleeper routes on these — an invented
# path 404s — so they are addresses rather than guesses.
LEAGUE_URL = "https://sleeper.com/leagues/{league_id}"


class SleeperNFLProvider:
    """CompetitionProvider for Sleeper points-league football."""

    sport = "football"
    competition = "nfl"
    label = "NFL (Sleeper)"

    def __init__(self, username: str | None, *, client: SleeperNFLSource, espn: ESPNSource):
        """Every collaborator from bootstrap, which is the one place a real client is built."""
        self.username = username
        self.client = client
        self.espn = espn
        self.scoreboard = Scoreboard(client, espn)
        self.forecasts = Forecasts(client)
        self._user_id: str | None = None
        # One request's week, kept for that request: the summary and the
        # forecast beside it both need it, and gathering it is most of the wait.
        self._weeks: dict[str, Week] = {}

    # ── leagues ─────────────────────────────────────────────────────

    def _resolve_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        if not self.username:
            raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")
        self._user_id = self.client.get_user(self.username).user_id
        return self._user_id

    def list_leagues(self) -> list[LeagueRef]:
        state = self.client.get_nfl_state()
        leagues = self.client.get_leagues(self._resolve_user_id(), state.season)
        return [
            LeagueRef(
                league_id=lg.league_id,
                name=lg.name,
                competition=self.competition,
                detail=f"{lg.total_rosters}-team · {SCORING_LABELS.get(lg.scoring_format, lg.scoring_format)}",
                url=LEAGUE_URL.format(league_id=lg.league_id),
            )
            for lg in leagues
        ]

    def _league(self, league_id: str) -> SleeperLeague:
        state = self.client.get_nfl_state()
        for lg in self.client.get_leagues(self._resolve_user_id(), state.season):
            if lg.league_id == league_id:
                return lg
        raise LeagueNotFoundError(f"league {league_id} is not one of yours this season")

    def _my_roster(self, league_id: str) -> SleeperRoster:
        user_id = self._resolve_user_id()
        for roster in self.client.get_rosters(league_id):
            if roster.owner_id == user_id:
                return roster
        raise LeagueNotFoundError(f"you do not own a roster in league {league_id}")

    def _owned(self, league_id: str) -> set[str]:
        """Every player on a roster in this league: who is not on the wire."""
        return {pid for r in self.client.get_rosters(league_id) for pid in r.player_ids}

    @staticmethod
    def _signable(state: Week) -> Callable[[str], bool]:
        """Whether a player could be added at all, by id — the wire's own rule, for those who look ahead."""
        return lambda pid: views.is_signing(state.players.get(pid) or PlayerMeta())

    # ── players ─────────────────────────────────────────────────────

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The full roster, with the depth and experience a week view leaves out."""
        state = self._week(league_id)
        return views.cards(state, views.lineup_order(state, state.roster), set(state.roster.starter_ids))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        state = self._week(league_id)
        names = self.client.get_league_users(league_id)
        refs = [
            TeamRef(
                team_id=str(r.roster_id),
                name=names.get(r.owner_id, f"Roster {r.roster_id}"),
                detail=f"{r.record} · {r.points_for:.1f} pts",
                is_mine=r.roster_id == state.roster.roster_id,
            )
            for r in self.client.get_rosters(league_id)
        ]
        return sorted(refs, key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Somebody else's squad, in the same columns as your own."""
        state = self._week(league_id)
        roster = next((r for r in self.client.get_rosters(league_id) if str(r.roster_id) == team_id), None)
        if roster is None:
            raise TeamNotFoundError(f"roster {team_id}")
        return views.cards(state, views.lineup_order(state, roster), set(roster.starter_ids))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """Everyone nobody in the league holds, best projection first.

        The catalog is twelve thousand players and all but a couple of hundred
        are free, so the pool is cut to the positions a fantasy league actually
        scores — the rest is practice-squad depth nobody is deciding about.
        That still leaves four thousand, which is why this is a page.
        """
        state = self._week(league_id)
        owned = self._owned(league_id)
        available = [
            (state.projections.get(pid), pid, meta)
            for pid, meta in state.players.items()
            if pid not in owned and views.is_signing(meta)
        ]
        # Ranked on the projection, and among the unprojected on depth chart —
        # a starter with no projection yet is worth more than a fourth-stringer.
        available.sort(
            key=lambda row: (-(row[0].points if row[0] else 0.0), int(row[2].get("depth_chart_order") or 99))
        )
        ranked = views.cards(state, [pid for _, pid, _ in available], starters=set(), owned_column=False, fits=True)
        return paging.page(ranked, query)

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player: the week, what makes the projection, and who they are."""
        return views.detail(self.client, self._week(league_id), player_id)

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster."""
        league = self._league(league_id)
        roster = self._my_roster(league_id)
        state = self.client.get_state(NFL)
        week, season = self._current_week(), state.season

        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        index = self._name_index(projections, players)

        giving, receiving = resolve_sides(proposal, index.lookup)

        rostered = [projection_for(pid, projections, players) for pid in roster.player_ids]
        known = self._evidence(season, week, league.scoring_format, state.is_regular_season)
        heard = self._news(players)
        roster_lines = {
            p.name: prompt.player_line(p, known, heard)
            for p in sorted((p for p in rostered if p), key=lambda x: -x.points)
        }

        situation, _ = prompt.matchup(self.client, league, roster, league_id, week)
        constraints = (
            f"LINEUP SLOTS: {', '.join(league.starting_slots)}\n"
            "- Only points from the starting lineup score. Bench depth has value only as "
            "insurance or as a future starter."
        )
        text = NFL_TRADE_PROMPT.format(
            giving_str="".join(prompt.player_line(p, known, heard) for p in giving),
            receiving_str="".join(prompt.player_line(p, known, heard) for p in receiving),
            situation=situation,
            constraints=constraints,
            roster_str="".join(roster_lines.values()),
            scoring_label=SCORING_LABELS.get(league.scoring_format, league.scoring_format),
        )
        return CompetitionContext(prompt=text, situation=situation, constraints=constraints, roster_lines=roster_lines)

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
        owned = self._owned(league_id)
        unavailable = [pid for pid in player_ids if pid in owned or pid not in state.players]
        if unavailable:
            raise PlayerNotFoundError(unavailable)

        candidates = [p for p in (projection_for(pid, state.projections, state.players) for pid in player_ids) if p]
        targets = {p.player_id: self._wire_line(p, state) for p in candidates}
        candidate_lines = {p.name: targets[p.player_id] for p in candidates}
        roster_lines = {
            p.name: prompt.player_line(p, state.evidence, state.news)
            for p in sorted(state.projected, key=lambda x: -x.points)
        }
        situation, _ = prompt.matchup(self.client, state.league, state.roster, league_id, state.week)
        constraints = (
            f"LINEUP SLOTS: {', '.join(state.league.starting_slots)}\n"
            "- Only the starting lineup scores; a bench spot is insurance or a future starter."
        )
        text = NFL_WIRE_PROMPT.format(
            scoring_label=SCORING_LABELS.get(state.league.scoring_format, state.league.scoring_format),
            situation=situation,
            constraints=constraints,
            roster_str="".join(roster_lines.values()),
            candidates_str="".join(candidate_lines.values()),
        )
        return CompetitionContext(
            prompt=text,
            situation=situation,
            constraints=constraints,
            roster_lines=roster_lines,
            candidate_lines=candidate_lines,
            targets=targets,
        )

    def _wire_line(self, player: WeeklyProjection, state: Week) -> str:
        """One candidate as the model reads him: his id, his line, and how he fits."""
        line = prompt.player_line(player, state.evidence, state.news)
        fit = views.fit(state, player)
        return f"- [id {player.player_id}] {line[2:]}" + (f"  fits: {fit[1]}\n" if fit else "")

    @staticmethod
    def _name_index(
        projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
    ) -> NameIndex[WeeklyProjection]:
        """Every projectable player, looked up by the name a user would type."""
        index: NameIndex[WeeklyProjection] = NameIndex()
        for projection in projections.values():
            index.add(projection.name, projection)
        # Players with no projection are still tradeable — a bye, or a stash.
        for player_id, meta in players.items():
            name = meta.get("name")
            if name and player_id not in projections and meta.get("position"):
                index.add(name, zero_projection(player_id, meta))
        return index

    # ── the week ────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather the week, then render it as the text a model reads.

        Carries the same to-do list the page shows, numbered, so the model
        judges the moves somebody is looking at rather than inventing its own.
        """
        state = self._week(league_id)
        tasks = self._actions(state, league_id, self.scoreboard.games(state))
        return prompt.build(self.client, state, league_id, tasks)

    def _current_week(self) -> int:
        """The week the report is about; the opener while still in preseason."""
        state = self.client.get_state(NFL)
        return max(1, state.week if state.is_regular_season else 1)

    def _week(self, league_id: str) -> Week:
        """The week, gathered once per provider — which is once per request."""
        if league_id not in self._weeks:
            self._weeks[league_id] = self._gather_week(league_id)
        return self._weeks[league_id]

    def _gather_week(self, league_id: str) -> Week:
        """Everything both the header and the prompt are derived from.

        Gathered once because the two would otherwise fetch the same
        projections and re-run the same lineup solve, and could then disagree
        about the totals by a rounding.
        """
        league = self._league(league_id)
        roster = self._my_roster(league_id)
        state = self.client.get_state(NFL)
        week, season = self._current_week(), state.season

        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        projected = [p for p in (projection_for(pid, projections, players) for pid in roster.player_ids) if p]

        slots = league.starting_slots
        lineup = current_lineup(slots, roster.starter_ids, projected)
        best = optimal_lineup(slots, projected)
        current_points = round(lineup_points(lineup), 1)
        best_points = round(lineup_points(best), 1)

        return Week(
            evidence=self._evidence(season, week, league.scoring_format, state.is_regular_season),
            news=self._news(players),
            is_regular_season=state.is_regular_season,
            league=league,
            roster=roster,
            week=week,
            season=season,
            projections=projections,
            players=players,
            projected=projected,
            lineup=lineup,
            best=best,
            changes=lineup_changes(slots, roster.starter_ids, projected),
            current_points=current_points,
            best_points=best_points,
            on_bench=round(best_points - current_points, 1),
        )

    def _evidence(self, season: str, week: int, scoring: str, started: bool) -> evidence.Evidence:
        """Roles and matchups from every week finished so far.

        The current week is left out even when it is part played: a player
        whose game is on Monday has a line of noughts until then, and a
        role computed from it says he has none.
        """
        played = list(range(1, week)) if started else []
        if not played:
            return evidence.Evidence()
        try:
            lines = self.client.get_nfl_game_lines(season, played)
        except SleeperAPIError as e:
            # Enrichment: a week with no evidence is the week as it was before.
            logger.warning(f"Continuing without role and matchup evidence: {e}")
            return evidence.Evidence()
        return evidence.gather(lines, scoring)

    def _news(self, players: dict[str, PlayerMeta]) -> news.PlayerNews:
        """Recent articles about every player, from each club's own feed."""
        clubs = sorted(
            {espn_club(str(m.get("team"))) for m in players.values() if m.get("team") not in (None, "", "FA")}
        )
        try:
            feeds = self.espn.get_team_news(espn.NFL, clubs)
        except ESPNAPIError as e:
            # Enrichment, like the evidence: the week stands without it.
            logger.warning(f"Continuing without player news: {e}")
            return news.PlayerNews()
        return news.attach(feeds, players, datetime.now(UTC))

    def summary(self, league_id: str) -> Summary:
        """The week as it stands: both lineups, the swaps, the byes. No model."""
        state = self._week(league_id)
        _, matchup_stats = prompt.matchup(self.client, state.league, state.roster, league_id, state.week)
        live = self.scoreboard.live(state, league_id)
        starters = {slot.player.player_id for slot in state.lineup if slot.player}
        # No fixture notes: a bye is on the player's own row, and on the to-do
        # list when it costs a starter, so a list of clubs would say it twice.
        games = self.scoreboard.games(state)

        return Summary(
            headline=prompt.headline(state.roster, state.week, state.current_points, state.best_points, state.on_bench)
            + matchup_stats,
            mine=Side(
                name="Your lineup",
                detail=state.roster.record,
                points=views.side_total(state, live),
                lineup=[views.lineup_spot(slot, state.scheduled, live) for slot in state.lineup],
                bench=[
                    views.reserved(views.spot(p, state.scheduled, live=live), state.roster)
                    for p in sorted(
                        (p for p in state.projected if p.player_id not in starters), key=lambda p: -p.points
                    )
                ],
            ),
            opponent=self._opponent(state, league_id),
            swaps=[
                Swap(
                    start=f"{change.start.name} ({change.slot})",
                    out=change.bench.name if change.bench else "",
                    gain=f"+{change.gain:.1f} proj pts",
                )
                for change in state.changes
            ],
            actions=self._with_short_week(state, league_id, self._actions(state, league_id, games)),
            window=self._window(state, games),
        )

    def _actions(self, state: Week, league_id: str, games: dict[int, list[ScheduledGame]]) -> list[Action]:
        return actions.build(state, games, actions.wire(state, self._owned(league_id), self._signable(state)))

    def _with_short_week(self, state: Week, league_id: str, listed: list[Action]) -> list[Action]:
        """The list with next week flagged where byes and injuries leave it short, in place of its bye items."""
        try:
            ahead = outlook.build(self.client, state, league_id, self._signable(state))
        except SleeperAPIError as e:
            logger.warning(f"Continuing without the weeks ahead: {e}")
            return listed
        short = outlook.to_do(ahead, state)
        if short is None:
            return listed
        return [a for a in listed if not a.key.startswith(f"bye:{state.week + 1}:")] + [short]

    def _window(self, state: Week, games: dict[int, list[ScheduledGame]]) -> str:
        """Which week, and when it is actually played.

        A week with no dates on it is a number, and the number is the one thing
        somebody already knows.
        """
        span = week_dates(games.get(state.week, []))
        return f"Week {state.week} · {span}" if span else f"Week {state.week}"

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, this week's real games, and what the league did."""
        return league.build(self.client, self._week(league_id), league_id)

    def _opponent(self, state: Week, league_id: str) -> Side | None:
        """The team you are playing, and what they are starting; None on a bye or an unpaired week.

        Their lineup is the other half of the only question this week asks, and
        it costs one roster fetch that has already been cached.
        """
        found = self._opponent_roster(state, league_id)
        if found is None:
            return None
        roster, entry = found
        name = self.client.get_league_users(league_id).get(roster.owner_id, "Opponent")
        return views.opponent_side(state, roster, entry, name, self.scoreboard.live(state, league_id))

    def _opponent_roster(self, state: Week, league_id: str) -> tuple[SleeperRoster, dict] | None:
        """The roster you play this week and its matchup entry; None on a bye, an unpaired week or no scoreboard."""
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without the opponent: {e}")
            return None
        entry = opponent_entry(state, matchups)
        if entry is None:
            return None
        by_roster = {r.roster_id: r for r in self.client.get_rosters(league_id)}
        roster = by_roster.get(int(entry.get("roster_id", 0)))
        return (roster, entry) if roster is not None else None

    # ── the matchup, simulated ──────────────────────────────────────

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        """This week's matchup, ready to simulate; None where there is no opponent to play."""
        state = self._week(league_id)
        found = self._opponent_roster(state, league_id)
        if found is None:
            return None
        to_do = [] if candidates else self._actions(state, league_id, self.scoreboard.games(state))
        return self.forecasts.matchup(
            state,
            league_id,
            self.scoreboard,
            opponent=found[0],
            to_do=to_do,
            candidates=candidates,
            owned=self._owned(league_id) if candidates else set(),
            seeded=seed(self.label, league_id, state.week),
        )

    def played_week(
        self, league_id: str, week: int
    ) -> tuple[evidence.Evidence, evidence.Evidence, list[tuple[WeeklyProjection, float]]]:
        """A finished week's players, for scoring ranges: what was known before it, and what each scored."""
        return self.forecasts.played_week(self._league(league_id), week)

    def played_matchups(
        self, league_id: str, week: int, settings: outcomes.RangeSettings = outcomes.DEFAULT
    ) -> list[PlayedMatchup]:
        """Every matchup of `week`, rebuilt as it stood before kickoff, with how it ended."""
        return self.forecasts.played_matchups(
            self._league(league_id), week, settings, lambda matchup_id: seed(self.label, league_id, week, matchup_id)
        )

    # ── the season ──────────────────────────────────────────────────

    def season_input(self, league_id: str) -> SeasonInput | None:
        """The rest of the regular season, ready to simulate to the playoffs."""
        state = self._week(league_id)
        return league.season_input(
            self.client, state, league_id, seed=seed(self.label, league_id, "season", state.week)
        )

    def weeks_ahead(self, league_id: str) -> list[WeekAhead]:
        """The next few weeks as your roster stands, with a pickup for any that byes and injuries leave short."""
        state = self._week(league_id)
        return outlook.build(self.client, state, league_id, self._signable(state))

    def trade_market(self, league_id: str) -> TradeMarket | None:
        """The rest of the season, with the one-for-one trades that would help both lineups."""
        state = self._week(league_id)
        return market.build(self.client, state, league_id, seed=seed(self.label, league_id, "season", state.week))
