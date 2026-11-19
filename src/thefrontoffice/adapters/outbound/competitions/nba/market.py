"""The basketball trades worth offering: one or two of yours for one of theirs, near even in worth, that your
weeks come out ahead on and theirs do too.

What a trade does is measured in the league's own terms, week by week, from
each roster's daily lineups (`strength.py`): a points league's fantasy points a
week, or a category league's categories you expect to take — against the team
you actually play each regular-season week, and against the field in a playoff
week, whose opponent is not drawn yet. The other side is measured the same way
over every week left, which is the case for him saying yes.

A trade lands after the league's review, so it changes the weeks after this
one. The season engine plays those out for the playoff race; a category week
has no one score to draw, so its fixtures carry each side's chance of taking
it (`Fixture.chances`), and a trade replaces the chances of every fixture
either team plays.

What a trade costs in worth is a player's game in the league's scoring over the
best free agent's, times the games his club has left (`competitions.trades.offers`
prices the offers). Players on an injured slot neither move nor are moved for:
their slot would not follow them. They still play for their own side from the
day ESPN expects them back. A two-for-one leaves the other side a player over
its roster where it is full, so it drops its least valuable one, which its weeks
are measured without; the spot it frees on yours is named with the free agent
who would help most in it, and not counted in the trade's worth — a drop could
open it anyway.
"""

import logging
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, ruled_out
from thefrontoffice.adapters.outbound.competitions.nba.strength import (
    POINTS,
    Profile,
    Scored,
    Totals,
    category_chances,
    points_spread,
    started,
    week_chances,
    week_totals,
)
from thefrontoffice.adapters.outbound.competitions.trades import offers
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import (
    Fixture,
    SeasonInput,
    TeamRecord,
    TeamWeek,
    TradeMarket,
    TradeMeasure,
    TradeOption,
)

logger = logging.getLogger(__name__)

THEIR_GAIN: dict[TradeMeasure, float] = {"points": 10.0, "categories": 0.1}
"""What a week the other side must gain to say yes: a tenth of a regular's week in points, or a category every
ten weeks — small beside a week, and still more than a trade's rounding."""

TOTAL_GAIN: dict[TradeMeasure, float] = {"points": 50.0, "categories": 0.5}
"""What a trade must add for you over the rest of the season: half a regular's week in points, or half a
category — less is a trade not worth the asking."""

STRENGTH_ERROR = 0.04
"""How far a team's real strength may sit off its means, as a share of a typical week's points: a rotation
change or a slump that lasts, not a night's swing."""

PICKUPS_TRIED = 5
"""The best free agents tried in the spot a two-for-one frees: past them, none is a pickup worth naming."""


@dataclass(frozen=True)
class Week:
    """One matchup week, as a roster's lineups play it."""

    week: int
    days: Mapping[str, frozenset[date]]
    """The nights each player can play, by Yahoo key: his club's, from his return while he is ruled out — for the
    week being played, only those still to come."""

    pairs: Sequence[tuple[str, str]] = ()
    """Its matchups by team key; none for a playoff week not drawn yet."""


@dataclass(frozen=True)
class League:
    """Everything a basketball trade is measured against."""

    mine: str
    teams: Sequence[TeamRecord]
    rosters: Mapping[str, Sequence[YahooPlayer]]
    profiles: Mapping[str, Profile]
    """What a game of each player gives, rostered or free, by key."""
    weeks: Sequence[Week]
    """The week being played, then every week to the end of the playoffs."""
    playoff_start: int
    spots: int
    slots: int
    """Lineup slots that score each night."""
    roster_size: int = 0
    """Players a team may hold outside its injured slots; nought for no limit known."""
    categories: Sequence[Scored] = ()
    """What a week is won on; none in a points league."""
    banked: Mapping[str, Totals] = field(default_factory=dict)
    """What each team has scored this week so far, by key."""
    wire: Sequence[YahooPlayer] = ()
    weekly: bool = False
    deadline: date | None = None
    seed: int = 0

    @property
    def measure(self) -> TradeMeasure:
        return "categories" if self.categories else "points"


def build(league: League) -> TradeMarket | None:
    """The rest of the season, and every trade near even in worth that improves your weeks; None once the
    regular season is over."""
    current = league.weeks[0].week if league.weeks else 0
    if not current or current >= league.playoff_start or league.mine not in league.rosters:
        return None
    model = _Model(league)
    after = [w for w in league.weeks if w.week > current]
    regular = [w for w in after if w.week < league.playoff_start]
    playoffs = [w for w in after if w.week >= league.playoff_start]
    options: list[TradeOption] = []
    for team in league.rosters:
        if team != league.mine:
            options += _Search(model, team, regular, playoffs).options()
    logger.info(f"Found {len(options)} basketball trades near even in worth that help your weeks")
    return TradeMarket(
        season=_season(model),
        options=tuple(options),
        regular_weeks=len(regular),
        playoff_weeks=len(playoffs),
        measure=league.measure,
        deadline=league.deadline,
        least_their_gain=THEIR_GAIN[league.measure],
        least_total_gain=TOTAL_GAIN[league.measure],
    )


Lineup = tuple[str, ...]
"""A roster's players best first, which is the order its nights are filled in."""


class _Model:
    """The league's weeks, with every roster's totals and every pairing's chances kept as they are worked out:
    the search asks the same lineup again and again."""

    def __init__(self, league: League) -> None:
        self.league = league
        self.value = {key: found.value for key, found in league.profiles.items()}
        self.players = {p.player_key: p for players in [*league.rosters.values(), league.wire] for p in players}
        self.injured = {p.player_key for players in league.rosters.values() for p in players if p.slot in INJURED_SLOTS}
        self.base = {team: self.lineup(p.player_key for p in players) for team, players in league.rosters.items()}
        self.opponents = {
            w.week: {team: other for home, away in w.pairs for team, other in ((home, away), (away, home))}
            for w in league.weeks
        }
        self._totals: dict[tuple[Lineup, int], Totals] = {}
        self._expected: dict[tuple[Lineup, Lineup, int], list[float]] = {}

    def lineup(self, keys: Iterable[str]) -> Lineup:
        """Players best first, ties broken by key so the same roster is always the same lineup."""
        return tuple(sorted(set(keys), key=lambda key: (-self.value.get(key, 0.0), key)))

    def totals(self, lineup: Lineup, week: Week) -> Totals:
        if (lineup, week.week) not in self._totals:
            counts = started(lineup, week.days, self.league.slots, weekly=self.league.weekly)
            self._totals[lineup, week.week] = week_totals(counts, self.league.profiles)
        return self._totals[lineup, week.week]

    def chances(self, mine: Lineup, theirs: Lineup, week: Week) -> list[float]:
        """Your chance of taking each category from them that week."""
        key = (mine, theirs, week.week)
        if key not in self._expected:
            self._expected[key] = category_chances(
                self.totals(mine, week), self.totals(theirs, week), self.league.categories
            )
        return self._expected[key]

    def worth(self, team: str, rosters: Mapping[str, Lineup], week: Week) -> float:
        """A team's week in the league's measure: its fantasy points, or the categories it expects to take from
        the team it plays — from each of the others in turn where nobody is drawn yet."""
        mine = rosters[team]
        if not self.league.categories:
            return self.totals(mine, week).mean.get(POINTS, 0.0)
        opponent = self.opponents[week.week].get(team)
        faced = [opponent] if opponent else [other for other in rosters if other != team]
        return statistics.fmean(sum(self.chances(mine, rosters[other], week)) for other in faced) if faced else 0.0

    def per_week(self, team: str, rosters: Mapping[str, Lineup], weeks: Sequence[Week]) -> float:
        return statistics.fmean(self.worth(team, rosters, w) for w in weeks) if weeks else 0.0

    def fixture(self, home: str, away: str, rosters: Mapping[str, Lineup], week: Week) -> Fixture:
        """A category week between two rosters, as each side's chance of taking it."""
        chances = week_chances(self.chances(rosters[home], rosters[away], week))
        return Fixture(week.week, home, away, chances=chances)

    def scored(self, team: str, lineup: Lineup, week: Week) -> TeamWeek:
        """A points week of a roster as the season draws it."""
        totals = self.totals(lineup, week)
        return TeamWeek(team, week.week, totals.mean.get(POINTS, 0.0), points_spread(totals))


def _season(model: _Model) -> SeasonInput:
    """The regular season left, the week being played with what each side has banked in it."""
    league = model.league
    current = league.weeks[0]
    regular = [w for w in league.weeks if w.week < league.playoff_start]
    rosters = model.base
    scoring: list[TeamWeek] = []
    fixtures: list[Fixture] = []
    for week in regular:
        banked = league.banked if week is current else {}
        if league.categories:
            for home, away in week.pairs:
                mine, theirs = (model.totals(rosters[team], week).plus(_banked(banked, team)) for team in (home, away))
                chances = week_chances(category_chances(mine, theirs, league.categories))
                fixtures.append(Fixture(week.week, home, away, chances=chances))
            continue
        fixtures += [Fixture(week.week, home, away) for home, away in week.pairs]
        for team, lineup in rosters.items():
            row = model.scored(team, lineup, week)
            so_far = _banked(banked, team).mean.get(POINTS, 0.0)
            scoring.append(TeamWeek(team, week.week, row.mean + so_far, row.spread))
    means = [row.mean for row in scoring if row.week != current.week]
    return SeasonInput(
        teams=tuple(league.teams),
        fixtures=tuple(fixtures),
        scoring=tuple(scoring),
        spots=league.spots,
        mine=league.mine,
        week=current.week,
        strength_error=STRENGTH_ERROR * statistics.median(means) if means else 0.0,
        seed=league.seed,
    )


def _banked(banked: Mapping[str, Totals], team: str) -> Totals:
    return banked.get(team, Totals())


class _Search:
    """Every trade with one team that improves your weeks and is near even in worth."""

    def __init__(self, model: _Model, partner: str, regular: Sequence[Week], playoffs: Sequence[Week]) -> None:
        self.model = model
        self.league = model.league
        self.partner = partner
        self.regular, self.playoffs = regular, playoffs
        self.every = [*regular, *playoffs]
        self.games = {key: sum(len(w.days.get(key, ())) for w in self.every) for key in self.league.profiles}
        self.replacement = max(
            (
                model.value.get(p.player_key, 0.0)
                for p in self.league.wire
                if p.player_key in self.league.profiles and not ruled_out(p.status)
            ),
            default=0.0,
        )

    def worth(self, key: str) -> float:
        """What he is worth to anyone: his game over the best free agent's, times the games he has left."""
        return max(0.0, self.model.value.get(key, 0.0) - self.replacement) * self.games.get(key, 0)

    def options(self) -> list[TradeOption]:
        model, mine, partner = self.model, self.league.mine, self.partner
        base = model.base
        my_regular = model.per_week(mine, base, self.regular)
        my_playoffs = model.per_week(mine, base, self.playoffs)
        theirs_now = model.per_week(partner, base, self.every)
        my_ids, their_ids = self._tradeable(mine), self._tradeable(partner)

        def gain_for_you(rosters: Mapping[str, Lineup]) -> tuple[float, float]:
            regular = model.per_week(mine, rosters, self.regular) - my_regular
            playoffs = model.per_week(mine, rosters, self.playoffs) - my_playoffs
            return regular, playoffs

        def total(gain: tuple[float, float]) -> float:
            return gain[0] * len(self.regular) + gain[1] * len(self.playoffs)

        # Losing a player never helps a lineup, so a trade can only help you if
        # what you get improves it on its own; that alone prunes most of theirs.
        wanted = [pid for pid in their_ids if total(gain_for_you({**base, mine: self._with(mine, add=[pid])})) > 0]
        found = []
        for get in wanted:
            for give in offers(my_ids, self.worth, self.worth(get)):
                rosters = {
                    **base,
                    mine: self._with(mine, add=[get], drop=give),
                    partner: self._fitted(self._with(partner, add=give, drop=[get]), give),
                }
                gain = gain_for_you(rosters)
                if total(gain) <= 0:
                    continue
                # Both sides must come out ahead: a manager out of the race still says no to a worse team.
                theirs = model.per_week(partner, rosters, self.every) - theirs_now
                if theirs < THEIR_GAIN[self.league.measure]:
                    continue
                found.append(self._option(rosters, give, get, gain, theirs))
        return sorted(found, key=lambda option: -(option.playoff_points or option.points))

    def _option(
        self, rosters: Mapping[str, Lineup], give: Sequence[str], get: str, gain: tuple[float, float], theirs: float
    ) -> TradeOption:
        model, mine, partner = self.model, self.league.mine, self.partner
        changed = (mine, partner)
        return TradeOption(
            team_id=partner,
            giving=tuple(self._label(pid) for pid in give),
            receiving=(self._label(get),),
            giving_ids=tuple(give),
            receiving_ids=(get,),
            points=gain[0],
            their_points=theirs,
            playoff_points=gain[1] if self.playoffs else None,
            pickup=self._pickup(rosters) if len(give) > 1 else "",
            scoring=()
            if self.league.categories
            else tuple(model.scored(team, rosters[team], week) for team in changed for week in self.regular),
            fixtures=tuple(
                model.fixture(home, away, rosters, week)
                for week in self.regular
                for home, away in week.pairs
                if home in changed or away in changed
            )
            if self.league.categories
            else (),
        )

    def _tradeable(self, team: str) -> list[str]:
        """Players who could move: not those on an injured slot, whose slot would not follow them."""
        return [p.player_key for p in self.league.rosters[team] if p.player_key not in self.model.injured]

    def _with(self, team: str, add: Iterable[str] = (), drop: Iterable[str] = ()) -> Lineup:
        dropped = set(drop)
        return self.model.lineup([*(key for key in self.model.base[team] if key not in dropped), *add])

    def _fitted(self, lineup: Lineup, arriving: Sequence[str]) -> Lineup:
        """A roster within its limit: over it, less its least valuable player outside an injured slot who is not
        one just arriving — the drop Yahoo asks of a team taking two for one."""
        held = [key for key in lineup if key not in self.model.injured]
        size = self.league.roster_size
        if not size or len(held) <= size:
            return lineup
        cut = [key for key in reversed(held) if key not in arriving][: len(held) - size]
        return tuple(key for key in lineup if key not in cut)

    def _pickup(self, rosters: Mapping[str, Lineup]) -> str:
        """The free agent who would help your weeks most in the spot a two-for-one frees, where one would."""
        mine = self.league.mine
        rostered = {key for lineup in self.model.base.values() for key in lineup}
        candidates = sorted(
            (
                p
                for p in self.league.wire
                if p.player_key in self.league.profiles and p.player_key not in rostered and not ruled_out(p.status)
            ),
            key=lambda p: -self.model.value.get(p.player_key, 0.0),
        )[:PICKUPS_TRIED]
        now = self.model.per_week(mine, rosters, self.every)
        best, gain = "", 0.0
        for player in candidates:
            added = {**rosters, mine: self.model.lineup([*rosters[mine], player.player_key])}
            more = self.model.per_week(mine, added, self.every) - now
            if more > gain:
                best, gain = self._label(player.player_key), more
        return best

    def _label(self, key: str) -> str:
        player = self.model.players[key]
        return f"{player.name} ({player.position})" if player.position else player.name
