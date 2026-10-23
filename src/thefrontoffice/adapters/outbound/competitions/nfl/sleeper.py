"""NFL on Sleeper.

Points-scoring football: the forward-looking number is Sleeper's own weekly
projection in the league's scoring currency, and the binding constraints are the
starting lineup slots rather than a transaction budget.

Unlike the Yahoo path there is no OAuth — Sleeper's API is public, so a username
is the only configuration.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nfl import actions, evidence, league, market, news, outcomes, prompt
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import (
    LineupSlot,
    best_upgrade,
    current_lineup,
    fits,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    SCORING_LABELS,
    Live,
    Week,
    games_by_week,
    projection_for,
    week_dates,
    zero_projection,
)
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.espn import types as espn
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNClient, ESPNSource
from thefrontoffice.adapters.outbound.platforms.sleeper.client import NFL, SleeperClient, SleeperNFLSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    FANTASY_POSITIONS,
    PlayerMeta,
    ScheduledGame,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.config.constants import NFL_TRADE_PROMPT, NFL_WIRE_PROMPT
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import (
    ESPNAPIError,
    LeagueNotFoundError,
    PlayerNotFoundError,
    SleeperAPIError,
    TeamNotFoundError,
)
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    Action,
    CompetitionContext,
    LeagueSchedule,
    LineupMove,
    MatchupInput,
    Outcomes,
    PlayedMatchup,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    SeasonInput,
    Side,
    Spot,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
    Summary,
    Swap,
    TeamRef,
    Tone,
    TradeMarket,
    TradeProposal,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Sleeper's projection keys, in the order a box score reads them. Only the ones
# a fantasy line is actually made of — the payload carries dozens more, most of
# which are zero for any given player.
PROJECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("pass_att", "Pass att"),
    ("pass_cmp", "Completions"),
    ("pass_yd", "Pass yards"),
    ("pass_td", "Pass TD"),
    ("pass_int", "Interceptions"),
    ("rush_att", "Carries"),
    ("rush_yd", "Rush yards"),
    ("rush_td", "Rush TD"),
    ("rec_tgt", "Targets"),
    ("rec", "Receptions"),
    ("rec_yd", "Rec yards"),
    ("rec_td", "Rec TD"),
    ("fum_lost", "Fumbles lost"),
)


def _projection_lines(stats: dict[str, float]) -> list[Stat]:
    """The projection broken out, skipping what does not apply.

    A receiver has no passing line, and printing a column of zeroes for one
    buries the three numbers that matter.
    """
    return [
        Stat(label=label, value=f"{stats[key]:.1f}".rstrip("0").rstrip(".") or "0")
        for key, label in PROJECTION_LABELS
        if stats.get(key)
    ]


# Sleeper serves portraits off its own CDN, keyed by the same player_id the
# rest of the API uses, with no key and no lookup.
PORTRAIT_URL = "https://sleepercdn.com/content/nfl/players/{player_id}.jpg"
# Lowercase or it 404s, and the abbreviation everywhere else in this file is
# upper.
TEAM_LOGO_URL = "https://sleepercdn.com/images/team_logos/nfl/{team}.png"

# Where the moves are actually made. Sleeper routes on these — an invented
# path 404s — so they are addresses rather than guesses.
LEAGUE_URL = "https://sleeper.com/leagues/{league_id}"
PLAYER_URL = "https://sleeper.com/players/nfl/{player_id}"

SPLIT_LABELS = (
    ("pass_yd", "Passing yards"),
    ("pass_td", "Passing TDs"),
    ("pass_int", "Interceptions"),
    ("cmp_pct", "Completion %"),
    ("rush_yd", "Rushing yards"),
    ("rush_td", "Rushing TDs"),
    ("rec", "Receptions"),
    ("rec_tgt", "Targets"),
    ("rec_yd", "Receiving yards"),
    ("rec_td", "Receiving TDs"),
)


def _split_value(key: str, value: float | None) -> str:
    """A production figure, or nothing where that position never records one."""
    if not value:
        return NOT_APPLICABLE
    return f"{value:.1f}%" if key == "cmp_pct" else f"{value:.0f}"


# A week made and a week wasted, on a points-league scale where a startable
# flex is worth around ten.
HAUL_POINTS = 20.0
BLANK_POINTS = 5.0


class SleeperNFLProvider:
    """CompetitionProvider for Sleeper points-league football."""

    sport = "football"
    competition = "nfl"
    label = "NFL (Sleeper)"

    def __init__(
        self, username: str | None = None, *, client: SleeperNFLSource | None = None, espn: ESPNSource | None = None
    ):
        self.username = username or settings.sleeper_username
        self.client = client or SleeperClient()
        self.espn = espn or ESPNClient()
        self._user_id: str | None = None
        # One request's week, kept for that request: the summary and the
        # forecast beside it both need it, and gathering it is most of the wait.
        self._weeks: dict[str, Week] = {}
        self._previous: dict[str, evidence.Evidence] = {}

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

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The full roster, with the depth and experience a week view leaves out."""
        state = self._week(league_id)
        return self._cards(state, state.roster.player_ids, set(state.roster.starter_ids))

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
        return self._cards(state, roster.player_ids, set(roster.starter_ids))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """Everyone nobody in the league holds, best projection first.

        The catalog is twelve thousand players and all but a couple of hundred
        are free, so the pool is cut to the positions a fantasy league actually
        scores — the rest is practice-squad depth nobody is deciding about.
        That still leaves four thousand, which is why this is a page.
        """
        state = self._week(league_id)
        owned = {pid for r in self.client.get_rosters(league_id) for pid in r.player_ids}

        available = [
            (state.projections.get(pid), pid, meta)
            for pid, meta in state.players.items()
            if pid not in owned and self._is_signing(meta)
        ]
        # Ranked on the projection, and among the unprojected on depth chart —
        # a starter with no projection yet is worth more than a fourth-stringer.
        available.sort(
            key=lambda row: (-(row[0].points if row[0] else 0.0), int(row[2].get("depth_chart_order") or 99))
        )
        ranked = self._cards(state, [pid for _, pid, _ in available], starters=set(), owned_column=False, fits=True)
        return paging.page(ranked, query)

    @staticmethod
    def _is_signing(meta: PlayerMeta) -> bool:
        """Whether adding this player could do anything.

        Two cuts, both about what the wire is for. The catalog carries every
        position the sport has, and a fantasy league scores six of them. It
        also never forgets anybody: Reggie Wayne retired in 2014 and is still
        in it, unsigned, which the default ranking hid because he has no
        projection — and sorting by experience put him on the first page.
        A player on no NFL roster cannot score for yours.
        """
        return str(meta.get("position") or "") in FANTASY_POSITIONS and str(meta.get("team") or "FA") != "FA"

    def _cards(
        self,
        state: Week,
        player_ids: list[str],
        starters: set[str],
        owned_column: bool = True,
        fits: bool = False,
    ) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows.

        `fits` adds what each would add to your lineup — for the wire, where
        "how good is he" is only half the question and "how good is he for
        me" is the other.
        """
        scheduled = any(p.opponent for p in state.projected)

        cards = []
        for player_id in player_ids:
            meta = state.players.get(player_id)
            if not meta:
                continue
            projection = state.projections.get(player_id)
            injury = str(meta.get("injury_status") or "")
            depth = int(meta.get("depth_chart_order") or 0)
            fit = self._fit(state, projection) if fits and projection else None
            trend = state.evidence.trends.get(player_id) if fits else None
            cards.append(
                PlayerCard(
                    player_id=player_id,
                    tone="warning" if injury else "neutral",
                    values={
                        **({"Fits": fit[0]} if fit else {}),
                        **({"Usage": trend.rise} if trend else {}),
                        "Proj": projection.points if projection else 0.0,
                        "Depth": float(depth) if depth else 0.0,
                        "Exp": float(meta.get("years_exp") or 0),
                    },
                    columns={
                        "Player": str(meta.get("name") or player_id),
                        "Pos": str(meta.get("position") or ""),
                        "Team": str(meta.get("team") or "FA"),
                        # A free-agent list has no lineup to be in, so the
                        # column would read "BN" down its whole length.
                        **({"Slot": "START" if player_id in starters else "BN"} if owned_column else {}),
                        "Proj": f"{projection.points:.1f}" if projection else "0.0",
                        **({"Fits": fit[1] if fit else "—"} if fits else {}),
                        # Whose role just grew: the pickups a projection has
                        # not caught up with yet. Sorts by the size of the jump.
                        **({"Usage": trend.short() if trend else "—"} if fits else {}),
                        "Opponent": self._opponent_label(projection, scheduled),
                        "Depth": str(depth) if depth else "—",
                        "Exp": f"{int(meta.get('years_exp') or 0)}y",
                        "Status": injury,
                    },
                )
            )
        return cards

    @staticmethod
    def _headline_label(projection: WeeklyProjection | None, scheduled: bool, week: int) -> str:
        """What the figure is, or why there is not one.

        The two reasons differ and a reader can act on the difference: nothing
        is published yet, versus published and this player is not in it.
        """
        if projection:
            return f"projected for week {week}"
        if not scheduled:
            return f"Week {week} projections are not published yet"
        return f"Not projected to feature in week {week}"

    @staticmethod
    def _fit(state: Week, projection: WeeklyProjection) -> tuple[float, str] | None:
        """How he compares with your weakest starter he could replace, either way.

        A shortfall is shown as plainly as a gain: in a deep league nobody on
        the wire outprojects a starter, and which of them comes closest is
        then the whole question — a column of blanks would answer none of it.
        None only where he could fill no slot at all.
        """
        upgrade = best_upgrade(state.lineup, projection)
        if upgrade is None:
            return None
        gain, slot = upgrade
        if slot.player is None:
            return gain, f"+{gain:.1f} at {slot.slot}, empty"
        return (
            (gain, f"+{gain:.1f} over {slot.player.name}") if gain > 0 else (gain, f"{gain:.1f} vs {slot.player.name}")
        )

    @staticmethod
    def _role_and_matchup(projection: WeeklyProjection, state: Week) -> StatGroup | None:
        """What sits behind the projection: the defense he faces, and how he has been used."""
        stats = []
        if matchup := state.evidence.matchup(projection):
            stats.append(Stat(label="Matchup", value=matchup.describe(), tone=matchup.tone))
        if role := state.evidence.roles.get(projection.player_id):
            games = f"last {role.games}" if role.games > 1 else "last game"
            if role.snap_share is not None:
                stats.append(Stat(label=f"Snap share, {games}", value=f"{role.snap_share:.0%}"))
            if role.position in evidence.CARRY_POSITIONS:
                stats.append(Stat(label="Carries a game", value=f"{role.carries:.1f}"))
            if role.position in evidence.TARGET_POSITIONS:
                stats.append(Stat(label="Targets a game", value=f"{role.targets:.1f}"))
                if role.target_share is not None:
                    stats.append(Stat(label="Target share", value=f"{role.target_share:.0%}"))
            stats.append(Stat(label=f"Points a game, {games}", value=f"{role.points:.1f}"))
        return StatGroup(title="Role and matchup", stats=stats) if stats else None

    @staticmethod
    def _team_name(team: str, players: dict[str, PlayerMeta]) -> str:
        """A club in full, at no extra request.

        Sleeper files every team defense in the player catalog under the club's
        own abbreviation, named the way somebody would say it — so the catalog
        this provider already holds is also the lookup from 'DET' to
        'Detroit Lions'. Falls back to the abbreviation, which is what a caller
        would have shown anyway.
        """
        meta = players.get(team)
        return str(meta.get("name") or team) if meta else team

    @classmethod
    def _opponent_label(
        cls, projection: WeeklyProjection | None, scheduled: bool, players: dict[str, PlayerMeta] | None = None
    ) -> str:
        """Who they play. In full where a caller has room for it — the drawer
        does, a table column does not."""
        if projection and projection.opponent:
            opponent = cls._team_name(projection.opponent, players) if players else projection.opponent
            return f"vs {opponent}"
        return "no game" if scheduled else "—"

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player: the week, what makes the projection, and who they are."""
        state = self._week(league_id)
        meta = state.players.get(player_id)
        if meta is None:
            raise PlayerNotFoundError([player_id])

        projection = state.projections.get(player_id)
        scheduled = any(p.opponent for p in state.projected)
        depth = int(meta.get("depth_chart_order") or 0)
        injury = str(meta.get("injury_status") or "")
        body = str(meta.get("injury_body_part") or "")

        groups = [
            StatGroup(
                title=f"Week {state.week}",
                stats=[
                    Stat(label="Opponent", value=self._opponent_label(projection, scheduled, state.players)),
                    Stat(label="Projected", value=f"{projection.points:.1f}" if projection else "—"),
                    Stat(
                        label="Status",
                        value=injury or "active",
                        tone="warning" if injury else "good",
                    ),
                    *([Stat(label="Injury", value=body)] if body else []),
                ],
            )
        ]
        if projection and projection.stats:
            groups.append(StatGroup(title="Projected line", stats=_projection_lines(projection.stats)))
        if projection and (context := self._role_and_matchup(projection, state)):
            groups.append(context)
        if headlines := state.news.stats(player_id):
            groups.append(StatGroup(title="Latest news", stats=headlines))
        groups.append(
            StatGroup(
                title="Player",
                stats=[
                    Stat(label="Depth chart", value=f"{depth}" if depth else "unlisted"),
                    Stat(label="Experience", value=f"{int(meta.get('years_exp') or 0)} seasons"),
                    *([Stat(label="Age", value=str(meta["age"]))] if meta.get("age") else []),
                    *([Stat(label="Number", value=f"#{meta['number']}")] if meta.get("number") else []),
                    *([Stat(label="College", value=str(meta["college"]))] if meta.get("college") else []),
                ],
            )
        )

        return PlayerDetail(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=(team := str(meta.get("team") or "FA")),
            team_name=self._team_name(team, state.players),
            team_logo_url=TEAM_LOGO_URL.format(team=team.lower()) if team != "FA" else "",
            headline=f"{projection.points:.1f}" if projection else "",
            headline_label=self._headline_label(projection, scheduled, state.week),
            note=str(meta.get("injury_notes") or injury),
            # A team defense has no headshot — the CDN 404s on its abbreviation —
            # and the crest beside the club name already says who it is.
            image_url="" if meta.get("position") == "DEF" else PORTRAIT_URL.format(player_id=player_id),
            url=PLAYER_URL.format(player_id=player_id),
            tables=[table] if (table := self._season_table(player_id, state)) else [],
            tone="warning" if injury else "neutral",
            groups=groups,
        )

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
        owned = {pid for r in self.client.get_rosters(league_id) for pid in r.player_ids}
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
        fit = self._fit(state, player)
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

    # ── context ─────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather the week, then render it as the text a model reads.

        Carries the same to-do list the page shows, numbered, so the model
        judges the moves somebody is looking at rather than inventing its own.
        """
        state = self._week(league_id)
        tasks = self._actions(state, league_id, games_by_week(self.client, state.season))
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
            {news.espn_club(str(m.get("team"))) for m in players.values() if m.get("team") not in (None, "", "FA")}
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
        live = self._live(state, league_id)
        starters = {slot.player.player_id for slot in state.lineup if slot.player}
        # Before the season opens Sleeper publishes no fixtures at all, and
        # flagging every player for having no game turns the page amber over a
        # date rather than a decision. It only means something when others do.
        scheduled = any(p.opponent for p in state.projected)
        games = games_by_week(self.client, state.season)

        return Summary(
            headline=prompt.headline(state.roster, state.week, state.current_points, state.best_points, state.on_bench)
            + matchup_stats,
            mine=Side(
                name="Your lineup",
                detail=state.roster.record,
                points=self._side_total(state, live),
                lineup=[self._lineup_spot(slot, scheduled, live) for slot in state.lineup],
                bench=[
                    self._spot(p, scheduled, live=live)
                    for p in sorted(
                        (p for p in state.projected if p.player_id not in starters), key=lambda p: -p.points
                    )
                ],
            ),
            opponent=self._opponent(state, league_id, scheduled, live),
            swaps=[
                Swap(
                    start=f"{change.start.name} ({change.slot})",
                    out=change.bench.name if change.bench else "",
                    gain=f"+{change.gain:.1f} proj pts",
                )
                for change in state.changes
            ],
            fixtures=[
                Stat(label=club, value="no game this week", tone="warning")
                for club in sorted({p.team for p in state.projected if scheduled and not p.opponent})
            ],
            actions=self._actions(state, league_id, games),
            window=self._window(state, games),
        )

    def _actions(self, state: Week, league_id: str, games: dict[int, list[ScheduledGame]]) -> list[Action]:
        return actions.build(state, games, self._wire(state, league_id))

    def _wire(self, state: Week, league_id: str) -> list[WeeklyProjection]:
        """Who could be picked up and play this week, best projection first.

        Cut to players with a game and no ruling against them: the wire is
        asked to fill a hole, and a player on bye fills nothing.
        """
        owned = {pid for r in self.client.get_rosters(league_id) for pid in r.player_ids}
        return sorted(
            (
                p
                for pid, p in state.projections.items()
                if pid not in owned
                and p.opponent
                and p.injury_status.upper() not in actions.RULED_OUT
                and self._is_signing(state.players.get(pid) or PlayerMeta())
            ),
            key=lambda p: -p.points,
        )

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

    def _live(self, state: Week, league_id: str) -> Live:
        """What has actually been scored, and whose clubs have kicked off."""
        started = {
            club
            for game in games_by_week(self.client, state.season).get(state.week, [])
            if game.status and game.status != "pre_game"
            for club in (game.home, game.away)
        }
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without live scores: {e}")
            return Live(started=started, points={})

        points: dict[str, float] = {}
        for entry in matchups:
            for player_id, scored in (entry.get("players_points") or {}).items():
                points[str(player_id)] = float(scored or 0)
        return Live(started=started, points=points)

    @staticmethod
    def _side_total(state: Week, live: Live) -> str:
        """The projection until the ball is rolling, then what is on the board."""
        if not live.under_way:
            return f"{state.current_points:.1f} proj"
        scored = sum(live.scored(slot.player.player_id, slot.player.team) or 0 for slot in state.lineup if slot.player)
        return f"{scored:.1f} pts"

    def _opponent(self, state: Week, league_id: str, scheduled: bool, live: Live) -> Side | None:
        """The team you are playing, and what they are starting.

        Their lineup is the other half of the only question this week asks, and
        it costs one roster fetch that has already been cached.
        """
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"Skipping the opponent: {e}")
            return None

        found = self._opponent_roster(state, league_id, matchups)
        if found is None:
            return None
        roster, theirs = found

        names = self.client.get_league_users(league_id)
        projected = [
            p for p in (projection_for(pid, state.projections, state.players) for pid in roster.player_ids) if p
        ]
        starting = set(roster.starter_ids)
        by_id = {p.player_id: p for p in projected}

        # Walked in slot order rather than filtered out of `player_ids`, which
        # Sleeper returns in no order at all. Both sides are read across, so an
        # opponent listed QB-first against your kicker is not a comparison.
        # `starter_ids` is positionally aligned with the league's starting
        # slots, which is the only thing that makes the two columns rows.
        slots = state.league.starting_slots
        if len(roster.starter_ids) == len(slots):
            lineup = [
                self._spot(by_id[pid], scheduled, slot=slot, live=live)
                if pid in by_id
                else Spot(slot=slot, player="—", detail="empty", value="0.0", tone="warning")
                for slot, pid in zip(slots, roster.starter_ids, strict=True)
            ]
        else:
            # Off-length means the positions cannot be trusted, and a WR
            # labelled QB is worse than a row carrying no label at all.
            logger.warning(f"Roster {roster.roster_id} starts {len(roster.starter_ids)} into {len(slots)} slots")
            lineup = [self._spot(p, scheduled, live=live) for p in projected if p.player_id in starting]
        return Side(
            name=names.get(roster.owner_id, "Opponent"),
            detail=roster.record,
            points=f"{float(theirs.get('points') or 0):.1f}",
            lineup=lineup,
            bench=[self._spot(p, scheduled, live=live) for p in projected if p.player_id not in starting],
        )

    def _opponent_roster(
        self, state: Week, league_id: str, matchups: list[dict[str, Any]]
    ) -> tuple[SleeperRoster, dict[str, Any]] | None:
        """The roster you play this week and its matchup entry; None on a bye or an unpaired week."""
        mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
        if not mine or mine.get("matchup_id") is None:
            return None
        theirs = next(
            (
                m
                for m in matchups
                if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != state.roster.roster_id
            ),
            None,
        )
        if not theirs:
            return None
        by_roster = {r.roster_id: r for r in self.client.get_rosters(league_id)}
        roster = by_roster.get(int(theirs.get("roster_id", 0)))
        return (roster, theirs) if roster is not None else None

    # ── the matchup, simulated ──────────────────────────────────────

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        """This week's matchup, ready to simulate: both lineups, and the moves worth pricing.

        The moves are every single swap your bench allows — the simulation
        finds the one a projection would not — and every waiver pickup the
        to-do list names. With `candidates` they are instead every legal
        start of each of those free agents, priced as if already claimed.
        """
        state = self._week(league_id)
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"No forecast without the matchup: {e}")
            return None
        found = self._opponent_roster(state, league_id, matchups)
        if found is None:
            return None
        roster, _ = found

        games = games_by_week(self.client, state.season)
        status = {club: game.status for game in games.get(state.week, []) for club in (game.home, game.away)}
        live = self._live(state, league_id)
        spread = outcomes.spreads(
            state.evidence, pool_from=self._last_season(state.season, state.league.scoring_format)
        )

        def outcome(player: WeeklyProjection) -> Outcomes:
            return outcomes.outcomes(
                player,
                spread,
                status=status.get(player.team, ""),
                scored=live.points.get(player.player_id, 0.0),
            )

        mine = tuple(outcome(slot.player) for slot in state.lineup if slot.player)
        theirs = tuple(
            outcome(p)
            for p in (projection_for(pid, state.projections, state.players) for pid in roster.starter_ids if pid != "0")
            if p
        )
        started = {club for club, s in status.items() if s and s != "pre_game"}
        if candidates:
            owned = {pid for r in self.client.get_rosters(league_id) for pid in r.player_ids}
            wire = [state.projections[pid] for pid in candidates if pid in state.projections and pid not in owned]
            moves = self._starts(state, wire, outcome, started)
        else:
            bench = [p for p in state.projected if p.player_id not in state.starter_ids]
            moves = self._starts(state, bench, outcome, started) + self._pickups(state, league_id, games, outcome)
        return MatchupInput(mine=mine, theirs=theirs, moves=moves, seed=_seed(self.label, league_id, state.week))

    def _last_season(self, season: str, scoring: str) -> evidence.Evidence:
        """Last season's games, for the shape of each position's spread. Empty where they will not load."""
        key = f"{season}:{scoring}"
        if key not in self._previous:
            try:
                lines = self.client.get_nfl_game_lines(str(int(season) - 1), list(range(1, SEASON_WEEKS + 1)))
            except (SleeperAPIError, ValueError) as e:
                logger.warning(f"Shaping ranges without last season: {e}")
                lines = []
            self._previous[key] = evidence.gather(lines, scoring)
        return self._previous[key]

    @staticmethod
    def _starts(
        state: Week,
        players: list[WeeklyProjection],
        outcome: Callable[[WeeklyProjection], Outcomes],
        started: set[str],
    ) -> tuple[LineupMove, ...]:
        """Every single start of one of `players` that leaves a legal lineup, among players not yet locked.

        A lineup is a set of starters, so a swap is one in and one out — legal
        if the new set fills the slots any way at all. Hall for Bernard is one,
        though Hall cannot play Bernard's WR slot: the flex slides across.
        The same for a bench player and a free agent: who he is does not
        change which lineups he makes.
        """
        starters = [slot.player for slot in state.lineup if slot.player]
        slots = state.league.starting_slots
        eligible = [
            p
            for p in players
            if p.team not in started and p.injury_status.upper() not in actions.RULED_OUT and p.opponent
        ]
        moves = []
        for candidate in eligible:
            if len(starters) < len(slots) and fits(slots, [*starters, candidate]):
                moves.append(
                    LineupMove(
                        key=f"{candidate.player_id}>",
                        title=f"Start {candidate.name} in your empty slot",
                        out=(),
                        into=(outcome(candidate),),
                    )
                )
            for out in starters:
                if out.team in started:
                    continue
                lineup = [p for p in starters if p.player_id != out.player_id] + [candidate]
                if fits(slots, lineup):
                    moves.append(
                        LineupMove(
                            key=f"{candidate.player_id}>{out.player_id}",
                            title=f"Start {candidate.name} over {out.name}",
                            out=(out.player_id,),
                            into=(outcome(candidate),),
                        )
                    )
        return tuple(moves)

    def _pickups(
        self,
        state: Week,
        league_id: str,
        games: dict[int, list[ScheduledGame]],
        outcome: Callable[[WeeklyProjection], Outcomes],
    ) -> tuple[LineupMove, ...]:
        """The pickups that fill a hole this week, priced as if already claimed.

        Only those: a bye warning names your own starter, and a breakout is a
        stash for the bench — priced as a start, either would be a player
        added to a full lineup, which no move can do.
        """
        moves = []
        for action in self._actions(state, league_id, games):
            projection = state.projections.get(action.player_id)
            if action.kind != "waiver" or not action.key.startswith("hole:") or projection is None:
                continue
            moves.append(
                LineupMove(
                    key=f"{action.player_id}>{action.replaces}",
                    title=action.title,
                    out=(action.replaces,) if action.replaces else (),
                    into=(outcome(projection),),
                )
            )
        return tuple(moves)

    def played_week(
        self, league_id: str, week: int
    ) -> tuple[evidence.Evidence, evidence.Evidence, list[tuple[WeeklyProjection, float]]]:
        """A finished week's players, for scoring ranges: what was known before it, and what each scored.

        Every player who took the field and was projected at least a few
        points — the ones a range is ever drawn for — paired with his actual
        score. What was known is the games before it alone, so nothing a
        range is scored against shaped it.
        """
        league = self._league(league_id)
        season = self.client.get_state(NFL).season
        lines = self.client.get_nfl_game_lines(season, list(range(1, week + 1)))
        before = evidence.gather([line for line in lines if line.week < week], league.scoring_format)
        last = self._last_season(season, league.scoring_format)
        projections = self.client.get_projections(season, week, league.scoring_format)
        that_week = evidence.gather([line for line in lines if line.week == week], league.scoring_format)
        played = [
            (projections[pid], games[0])
            for pid, games in that_week.games.items()
            if pid in projections and projections[pid].points >= SCORED_FROM
        ]
        return before, last, played

    def played_matchups(
        self, league_id: str, week: int, settings: outcomes.RangeSettings = outcomes.DEFAULT
    ) -> list[PlayedMatchup]:
        """Every matchup of `week`, rebuilt as it stood before kickoff, with how it ended.

        As it stood: that week's projections and starters, and only the games
        played before it — a range shaped by the week being predicted would
        be the answer leaking into the question.
        """
        league = self._league(league_id)
        season = self.client.get_state(NFL).season
        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        earlier = list(range(1, week))
        lines = self.client.get_nfl_game_lines(season, earlier) if earlier else []
        spread = outcomes.spreads(
            evidence.gather(lines, league.scoring_format),
            settings,
            pool_from=self._last_season(season, league.scoring_format),
        )

        def side(entry: dict[str, Any]) -> tuple[Outcomes, ...]:
            starters = [str(pid) for pid in entry.get("starters") or [] if str(pid) not in ("0", "")]
            return tuple(
                outcomes.outcomes(p, spread, settings=settings)
                for p in (projection_for(pid, projections, players) for pid in starters)
                if p
            )

        paired: dict[Any, list[dict[str, Any]]] = {}
        for entry in self.client.get_matchups(league_id, week):
            if entry.get("matchup_id") is not None:
                paired.setdefault(entry["matchup_id"], []).append(entry)

        played = []
        for matchup_id, entries in paired.items():
            if len(entries) != 2:
                continue
            first, second = sorted(entries, key=lambda e: int(e.get("roster_id") or 0))
            played.append(
                PlayedMatchup(
                    week=week,
                    matchup=MatchupInput(
                        mine=side(first), theirs=side(second), seed=_seed(self.label, league_id, week, matchup_id)
                    ),
                    mine=float(first.get("points") or 0),
                    theirs=float(second.get("points") or 0),
                )
            )
        return played

    def season_input(self, league_id: str) -> SeasonInput | None:
        """The rest of the regular season, ready to simulate to the playoffs."""
        state = self._week(league_id)
        return league.season_input(
            self.client, state, league_id, seed=_seed(self.label, league_id, "season", state.week)
        )

    def trade_market(self, league_id: str) -> TradeMarket | None:
        """The rest of the season, with the one-for-one trades that would help both lineups."""
        state = self._week(league_id)
        return market.build(self.client, state, league_id, seed=_seed(self.label, league_id, "season", state.week))

    def _season_table(self, player_id: str, state: Week) -> StatTable | None:
        """This season beside the two before it, read across rather than down.

        A projection is a guess; these are the seasons it is a guess about, and
        a page showing only the guess gives no way to weigh it. Stacked groups
        make you hold last year's yards in your head while scrolling to this
        year's; a row puts them side by side.

        Per game as well as total, because a total mostly measures availability
        — twelve games is not a worse week.

        Degrades to nothing rather than failing the page: a rookie has no
        history, and neither does a season Sleeper has not published.
        """
        scoring = state.league.scoring_format
        columns = [state.season, *self._recent_seasons(state.season)]
        by_season: dict[str, SeasonStats | None] = {}
        for season in columns:
            try:
                by_season[season] = self.client.get_season_stats(season).get(player_id)
            except SleeperAPIError as e:
                logger.warning(f"Skipping {season} totals: {e}")
                by_season[season] = None

        # A season nobody has played yet has no answers, and a column of
        # noughts claims it does.
        if not state.is_regular_season:
            by_season[state.season] = None
        if not any(stats and stats.games for stats in by_season.values()):
            return None

        def played(season: str) -> SeasonStats | None:
            """The season's totals, or nothing where it was never played."""
            stats = by_season.get(season)
            return stats if stats and stats.games else None

        def row(label: str, of: Callable[[SeasonStats], str]) -> StatRow:
            return StatRow(
                label=label,
                values=[of(stats) if (stats := played(c)) else NOT_APPLICABLE for c in columns],
            )

        rows = [
            row("Per game", lambda st: f"{st.per_game(scoring):.1f}"),
            row("Total", lambda st: f"{st.scored(scoring):.1f}"),
            row("Games", lambda st: str(st.games)),
            row("Position rank", lambda st: f"#{st.position_rank}" if st.position_rank else NOT_APPLICABLE),
        ]
        # Only the splits somebody actually records: a running back has no
        # completion percentage, and a whole row of N/A is a row of nothing.
        for key, label in SPLIT_LABELS:
            if any(stats and stats.splits.get(key) for stats in by_season.values()):
                rows.append(row(label, lambda st, k=key: _split_value(k, st.splits.get(k))))

        return StatTable(title="By season", columns=columns, rows=rows)

    @staticmethod
    def _recent_seasons(season: str) -> list[str]:
        """The two seasons before this one, newest first.

        Two rather than a career: three years back is a different team, a
        different scheme and usually a different player.
        """
        try:
            year = int(season)
        except ValueError:
            return []
        return [str(year - 1), str(year - 2)]

    def _lineup_spot(self, slot: LineupSlot, scheduled: bool, live: Live | None = None) -> Spot:
        if slot.player is None:
            return Spot(slot=slot.slot, player="—", detail="empty", value="0.0", tone="warning")
        return self._spot(slot.player, scheduled, slot=slot.slot, live=live, projected=slot.points)

    def _spot(
        self,
        projection: WeeklyProjection,
        scheduled: bool,
        slot: str = "",
        live: Live | None = None,
        projected: float | None = None,
    ) -> Spot:
        """One row, showing what happened where the game has started.

        Once a club has kicked off, what its players actually scored is the
        number somebody is looking for, and the projection beside it is a guess
        about a question already being answered.
        """
        scored = live.scored(projection.player_id, projection.team) if live else None
        points = projection.points if projected is None else projected
        return Spot(
            player_id=projection.player_id,
            slot=slot,
            player=projection.name,
            detail=self._spot_detail(projection, scheduled, slot),
            value=f"{scored:.1f} pts" if scored is not None else f"{points:.1f}",
            tone=self._live_tone(scored) if scored is not None else self._spot_tone(projection, scheduled),
        )

    @staticmethod
    def _live_tone(scored: float) -> Tone:
        """A game already played answers its own question: a doubt about
        somebody who has been on the field is no longer a doubt."""
        if scored >= HAUL_POINTS:
            return "good"
        return "warning" if scored <= BLANK_POINTS else "neutral"

    @staticmethod
    def _spot_detail(projection: WeeklyProjection, scheduled: bool, slot: str = "") -> str:
        if projection.opponent:
            opponent = f"vs {projection.opponent}"
        else:
            opponent = "no game" if scheduled else "not scheduled yet"
        # The slot column already says "QB", so repeating it here reads as two
        # different facts about one row. A FLEX is the case worth keeping: the
        # place and the position genuinely differ, and which of them is filling
        # it is the whole question the row is asking.
        if projection.position == slot:
            return f"{projection.team} {opponent}"
        return f"{projection.position} · {projection.team} {opponent}"

    @staticmethod
    def _spot_tone(projection: WeeklyProjection | None, scheduled: bool) -> Tone:
        """A player who will not play is a zero, not a small number.

        Unless nobody is playing, in which case the week simply has not been
        published and there is nothing to notice about any single player.
        """
        if projection is None:
            return "warning"
        if projection.is_questionable:
            return "warning"
        return "warning" if scheduled and not projection.opponent else "neutral"

    # ── helpers ─────────────────────────────────────────────────────


SEASON_WEEKS = 18
"""A regular season's weeks; last season's are read whole for its spreads."""

SCORED_FROM = 3.0
"""Projected points below which a player is nobody's start, and his range not worth scoring."""


def _seed(*parts: object) -> int:
    """The same simulation for the same week, so the numbers hold still between reloads."""
    return int(hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).hexdigest()[:12], 16)
