"""What a basketball week asks of the manager, as a list of things to do.

Three kinds besides the IL move (`week.off_il`): a bench player to start over
a starter today, a free agent to add — a streamer for this week's games or a
keeper for the season's — and the player to drop for him.

Yahoo sets a basketball lineup day by day, so a start is today's: a bench
player whose game today is still to come, in for a starter who has no game
today or is ruled out of it, or for one clearly weaker a game. Nobody with no
game today is ever started, however much his week is worth. A stream is
weighed on worth this week — a game's value × minutes nudge × the nights he
would fill an open slot (`lineup`) — but never at the cost of a better player
a game, nor for less than `STREAM_GAMES` of the player let go: the games are
this week's, the player let go is gone for good, and an add is one of few. A
player on waivers is a claim, weighed on the games from the day he clears them
(`rules.playable_from`) and named as one.

The adds are one plan within the adds left (`streams`): no two share a drop
or a pickup, an open roster or IL spot goes first, and a week all but
decided either way spends them on the season rather than its own games.

Form and news reach the plan as they reach each reading: a player whose last
games ran well under his projection (a slump, `worth.streak`) is never kept,
one running well over it is never let go, and a keeper his own news puts in
trade talk (`Reading.talk`) ranks behind every clean one and says so. A streak
weighs this week three to one; a keeper, and who is kept, a third of the way
(`worth.season_line`), and a slump alone never makes a player the first let
go: a slump with his role falling, or with news, does.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import day_month, span, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.injuries import approximately
from thefrontoffice.adapters.outbound.competitions.nba import lineup, views
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.news import TRADE_TALK
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    INJURED_SLOTS,
    RESERVABLE,
    chance,
    clears,
    fits,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import RETURN_SOON, Leaning
from thefrontoffice.adapters.outbound.competitions.nba.week import BENCH, Today, if_streamed, off_il
from thefrontoffice.adapters.outbound.competitions.nba.worth import (
    HOT_MINUTES,
    ROLE,
    Reading,
    Targeting,
    counted,
    edges,
    falling,
    game_value,
    kept_value,
)
from thefrontoffice.domain.models import Action, Held, Pickup

MARGIN = 0.2
"""How much more a player must be worth than the one he would replace — a game, or this week: a fifth.

Below that a move is a coin flip a projection cannot settle, and every add
spends one of the week's few, so the list names only the clear ones.
"""

STREAM_GAMES = 1.5
"""What a stream must add this week, in games of the player let go: a game and a half.

One extra game of a player no better a game is a stream's whole case at 1, and
a single rest night or blowout takes it back; an add, one of the week's few,
has to buy a second night or a clearly better player. Counted in the drop's
games, so letting go a weak player is cheap and a solid one costs a real edge.
"""

STARTS = 3
"""Start-over items at once: the clearest few, not every reshuffle the bench allows."""

STREAMS = 2
"""Pickups at once, and never more than the adds left."""

KEPT = 0.5
"""The share of your roster never offered as a drop: the better half by value a game.

Worth this week is a week's figure, and a star with one game left reads low on
it; what a player gives a game says whether he is one to keep at all.
"""


def build(
    roster: Sequence[Player],
    free_agents: Sequence[Player],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
    today: Today | None = None,
    plan: Plan | None = None,
) -> list[Action]:
    """Every decision the week asks for: IL moves first, then today's starts, then pickups each with its drop.

    `today` is the day's games while it falls inside the week; None leaves out starts, which turn on it.
    `plan` is what weighs a pickup beyond the readings (`Plan`). A player out moved to an open injured slot
    (`reserving`) frees his roster spot for an add, and plays no part in the week's lineups until activated.
    """
    plan = plan or Plan()
    moves = reserving(roster, readings, plan.reserve)
    items = off_il(list(roster))
    items += [_to_reserve(player, slot, readings.get(player.player_key)) for player, slot in moves]
    items += starts(roster, readings, by_points, today)
    named = {pid for item in items for pid in (item.player_id, item.replaces) if pid}
    # In an injured slot he plays no part in the week's lineups, and no drop frees his spot.
    moved = {player.player_key for player, _ in moves}
    after = [p for p in roster if p.player_key not in moved]
    plan = replace(plan, open_spots=plan.open_spots + len(moves))
    added = adds(after, free_agents, readings, adds_left, by_points, named, plan)
    returns = _returns([player for player, _ in moves], after, readings, named | plan.untouchable, added)
    return [_with_return(item, returns) for item in items] + added.items


def reserving(
    roster: Sequence[Player], readings: Mapping[str, Reading], reserve: Sequence[str]
) -> list[tuple[Player, str]]:
    """Each active player out for the rest of the week (`rules.RESERVABLE`, no games left) whom one of the open
    `reserve` slots takes, and the slot: the longest out first, each slot once.

    Never one due back before the week ends: there he would sit out games he
    plays, and activating him would need a drop of its own.
    """
    open_slots = list(reserve)
    out = [
        (p, r)
        for p in roster
        if p.slot not in INJURED_SLOTS
        and p.status.upper() in RESERVABLE
        and (r := readings.get(p.player_key))
        and r.games == 0
    ]
    out.sort(key=lambda pair: pair[1].back or date.max, reverse=True)
    return [(player, open_slots.pop(0)) for player, _ in out[: len(open_slots)]]


def _returns(
    moved: Sequence[Player], roster: Sequence[Player], readings: Mapping[str, Reading], keep: set[str], added: Added
) -> dict[str, Reading | None]:
    """For each player moved to an injured slot, by Yahoo key, who to drop to activate him when he is back: the
    weakest the roster will hold once the week's adds are made (`droppable`, and the adds themselves), a falling
    role first, never one another item lets go, nor one already named for another return. None where nobody is."""
    pool = [
        *droppable(roster, readings, keep | added.dropped),
        *(r for r in added.joined if r.player.player_key not in keep),
    ]
    found: dict[str, Reading | None] = {}
    for player in moved:
        drop = next(
            (d for d in _weakest_first(pool, _kept) if d is not None and d not in found.values()),
            None,
        )
        found[player.player_key] = drop
    return found


def _with_return(item: Action, returns: Mapping[str, Reading | None]) -> Action:
    """An injured-slot move with his return planned: ' Back ~10 Dec: activate him then, dropping Gobert.'"""
    if not item.key.startswith(RESERVE) or item.player_id not in returns:
        return item
    drop = returns[item.player_id]
    plan = f" Activate him when back, dropping {drop.player.name}." if drop else " Activating him needs a drop."
    return item.model_copy(update={"reason": item.reason + plan})


RESERVE = "reserve:"
"""What an injured-slot move's key leads with."""


def _to_reserve(player: Player, slot: str, reading: Reading | None) -> Action:
    """'Move OG Anunoby to IL': he is out for the week, and the slot frees his roster spot for an add with no drop."""
    back = f", back {approximately(reading.back)}" if reading is not None and reading.back else ""
    return Action(
        kind="lineup",
        urgency="now",
        title=f"Move {player.name} to {slot}",
        reason=f"{player.name} is out for the week{back}. {slot} open: frees his roster spot, so an add needs no drop.",
        when="first",
        player_id=player.player_key,
        key=f"{RESERVE}{player.player_key}:{player.status.upper()}",
    )


def beats(theirs: float, mine: float) -> bool:
    """Whether `theirs` is worth more than `mine` by `MARGIN` of it; any worth beats nought."""
    return theirs > mine + abs(mine) * MARGIN and theirs > mine


def held(player: Player) -> Held:
    """Where he stands to you: in the lineup, on the bench, in an injured slot, on waivers, or free to add."""
    if not player.slot:
        return "waivers" if player.waiver_date else "free agent"
    if player.slot in INJURED_SLOTS:
        return "reserve"
    return "bench" if player.slot == BENCH else "starter"


def _unit(by_points: bool) -> str:
    return "fpts" if by_points else "value"


def starts(
    roster: Sequence[Player], readings: Mapping[str, Reading], by_points: bool, today: Today | None
) -> list[Action]:
    """Bench players to start today over a starter whose slot they can fill, the biggest gain a game first.

    Only a bench player whose game today has not tipped off, and who is not
    ruled out of it, goes in. He goes in for a starter who will score nothing
    today — no game, or ruled out — or for one whose game is also still to
    come and whom he beats by `MARGIN` a game. A starter whose game is under
    way is locked. Each starter is named once, against the weakest he could
    replace, and only a bench player Yahoo lets into that slot (`rules.fits`).
    None without `today`: a start set on the week rather than the day can put
    in a player with no game tonight.
    """
    if today is None:
        return []
    lineup = [
        r for p in roster if held(p) == "starter" and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    bench = [
        r
        for p in roster
        if held(p) == "bench"
        and not ruled_out(p.status)
        and _to_come(today, p)
        and (r := readings.get(p.player_key))
        and r.per_game is not None
    ]
    pairs = []
    for candidate in bench:
        for starter in lineup:
            game = today.game(starter.player.team)
            if not fits(starter.player.slot, candidate.player.position) or (game and game.status in STARTED):
                continue
            idle = game is None or ruled_out(starter.player.status)
            if idle or beats(_game(candidate), _game(starter)):
                gain = _game(candidate) - (0.0 if idle else _game(starter))
                pairs.append((idle, gain, candidate, starter))
    pairs.sort(key=lambda pair: (not pair[0], -pair[1]))
    taken: set[str] = set()
    items = []
    for idle, gain, candidate, starter in pairs:
        if len(items) == STARTS:
            break
        if candidate.player.player_key in taken or starter.player.player_key in taken:
            continue
        taken |= {candidate.player.player_key, starter.player.player_key}
        why = (
            f"{starter.player.name} {'is ruled out' if today.game(starter.player.team) else 'has no game'} today"
            if idle
            else f"+{gain:.1f} {_unit(by_points)} a game at {starter.player.slot}"
        )
        items.append(
            Action(
                kind="lineup",
                urgency="now",
                title=f"Start {candidate.player.name} over {starter.player.name} today",
                reason=f"{why}; {candidate.player.name} plays {_matchup(today, candidate.player)}.",
                player_id=candidate.player.player_key,
                replaces=starter.player.player_key,
                players=views.compared(
                    [("in", "bench", candidate), ("out", "starter", starter)],
                    by_points,
                ),
                key=f"start:{today.day.isoformat()}:{candidate.player.player_key}:{starter.player.player_key}",
            )
        )
    return items


def _to_come(today: Today, player: Player) -> bool:
    """Whether his club plays today and has yet to tip off: the lineup can still be changed for it."""
    game = today.game(player.team)
    return game is not None and game.status not in STARTED


STARTED = frozenset({"in_game", "complete"})
"""Sleeper's statuses for a game that has tipped off: its players are locked in or out."""


def _matchup(today: Today, player: Player) -> str:
    """'vs TOR' or '@ BOS': his game today."""
    game = today.game(player.team)
    found = game.opponent_of(player.team.upper()) if game else None
    if found is None:
        return "today"
    opponent, home = found
    return f"vs {opponent}" if home else f"@ {opponent}"


def droppable(roster: Sequence[Player], readings: Mapping[str, Reading], keep: set[str]) -> list[Reading]:
    """Who you could let go: a falling role, or a slump with news, first (`_fading`), then the least worth this week.

    Never a player in an injured slot — dropping him frees no active spot —
    nor one in the better `KEPT` of the roster by value a game for the season (`worth.kept_value`), nor one whose
    role is growing (`settled`): his value a game is still catching up with
    his minutes, however cold his last few nights. Nor one on a hot run
    (`Reading.hot`): a cold player goes before him. Nor one another item
    already moves, nor one with nothing to read him by: an unknown is not a
    weak player.
    """
    active = [
        r
        for p in roster
        if p.slot not in INJURED_SLOTS and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    ranked = sorted(active, key=lambda r: -_kept(r))
    kept = {r.player.player_key for r in ranked[: round(len(ranked) * KEPT)]}
    open_to = [
        r for r in active if r.player.player_key not in kept | keep and r.worth is not None and settled(r) and not r.hot
    ]
    return sorted(open_to, key=lambda r: (not _fading(r), _worth(r)))


def _fading(reading: Reading) -> bool:
    """Whether he is the first to let go: his minutes falling (`worth.falling`), or a slump his own news is in too
    (`Reading.talk`). A slump alone is a few games, which the season's value already reads a third of."""
    return falling(reading.role) or (reading.cold and bool(reading.talk))


DECIDED = 0.1
"""How sure the week must be, either way, for its adds to go to the rest of the season: a chance to win at or below
a tenth, or at or above nine tenths. A stream buys a few games of one player, which moves a week that close to
settled too little to be worth an add the season could use."""


@dataclass(frozen=True)
class Plan:
    """What weighs a pickup beyond each player's reading: the week's nights, teammates due back, the race in games.

    Without a `week` (no lineup slots in the settings, lineups set weekly, or a
    schedule that would not load) a pickup is weighed on every game his club
    has left, as his reading counts them, and no keeper hurt now is offered.
    """

    week: lineup.Week | None = None
    returning: Mapping[str, Leaning] = field(default_factory=dict)
    """What each free agent's role leans on, by Yahoo key: a teammate due back (`teammates.Leaning`)."""
    volume: tuple[int, int] | None = None
    """The games each side's lineups can start over the rest of the week: yours, then your opponent's."""
    streams: int = 0
    """The starts your opponent's adds left could still put into its open slots (`lineup.streamed`)."""
    targeting: Targeting | None = None
    """In a category league with a forecast, each category weighed by how winnable it is this week
    (`worth.Targeting`): what a stream or its drop is worth this week. None weighs every category alike."""
    needs: Targeting | None = None
    """In a category league, each category weighed by how short of it your roster is (`worth.needs`): what a keeper
    adds for the rest of the season. None weighs every category alike."""
    win: float | None = None
    """Your chance of winning the week, from the forecast; None where it would not run."""
    priority: int = 0
    """Your place in the league's waiver order, which decides a claim others make too; 0 where unknown."""
    untouchable: frozenset[str] = frozenset()
    """Your players the manager marked untouchable, by Yahoo key: never offered as a drop."""
    open_spots: int = 0
    """Active roster spots open now: an add into one lets nobody go."""
    reserve: tuple[str, ...] = ()
    """The injured slots open now, once per place: ('IL',)."""

    @property
    def behind(self) -> bool:
        """Whether your opponent can start more games than you this week, counting the starts its adds left could
        still stream in (`streams`): a stream is then urged now."""
        return self.volume is not None and self.volume[0] < self.volume[1] + self.streams

    @property
    def decided(self) -> bool:
        """Whether the week is all but lost or won (`DECIDED`): its adds then go to the rest of the season."""
        return self.win is not None and min(self.win, 1.0 - self.win) <= DECIDED


@dataclass(frozen=True)
class Swap:
    """One pickup weighed against one drop, or against a roster spot already open."""

    pickup: Reading
    drop: Reading | None
    """Who he is added in place of; None for an open roster spot."""
    term: Pickup
    gain: float
    """What the swap adds this week."""
    nights: int | None
    """The games he would start this week (`lineup.open_nights`); None where there is no week to place them."""
    add_on: date | None = None
    """For a keeper out now, the day without games to add him on: the drop plays until then."""
    targets: tuple[str, ...] = ()
    """The categories he adds most to over the drop, as the league names them: this week's close ones for a
    streamer (`Plan.targeting`), the roster's weakest for a keeper (`Plan.needs`)."""
    season: float = 0.0
    """What he adds a game over the drop for the rest of the season, as the roster's needs weigh it (`Weigh.season`)."""
    costs: tuple[str, ...] = ()
    rival: Reading | None = None
    """For a keeper, the runner-up for the same drop within `CLOSE` of him for the season (`Weigh.rival`), named on
    the same item as the other way to make it; None otherwise."""
    """The categories he gives up against the drop: this week's close ones for a streamer, the roster's weakest for
    a keeper (`Weigh.spent`)."""


def settled(reading: Reading) -> bool:
    """Whether his role has held: his minutes not grown lately (`worth.rising`), nor his last five above the
    window's by `ROLE.moved`. A role just handed to him is as often a teammate's absence as a promotion, so it
    streams until it holds."""
    role = reading.role
    return not reading.rising and (role is None or role.minutes - role.window < ROLE.moved)


class Weigh:
    """A roster's week, read once for every pickup and drop weighed against it."""

    def __init__(self, roster: Sequence[Player], readings: Mapping[str, Reading], plan: Plan) -> None:
        self.roster = roster
        self.plan = plan
        self.backs = {key: r.back for key, r in readings.items()}
        self.costs: dict[tuple[str, date | None, date | None], float] = {}

    def game(self, reading: Reading) -> float:
        """What a game of him adds this week, nudged by his minutes: in a category league with a forecast, each
        category weighed by how winnable it is (`Plan.targeting`); his value a game otherwise."""
        return _weighed(self.plan.targeting, reading)

    def season(self, reading: Reading | None) -> float:
        """What a game of him adds for the rest of the season, nudged by his minutes: each category weighed by how
        short of it the roster is (`Plan.needs`); his value a game otherwise. Nought for an open spot."""
        return 0.0 if reading is None else _weighed(self.plan.needs, reading, season=True)

    def _week(self, reading: Reading) -> float:
        """His whole week at this week's value a game: every game his club has left."""
        return self.game(reading) * reading.games if reading.per_game is not None and reading.games else 0.0

    def gained(self, pickup: Reading, drop: Reading | None, before: date | None = None) -> tuple[float, int | None]:
        """What he adds this week in `drop`'s place, and the games behind it: each night he fills an open slot,
        before `before` where given, those from the return of a teammate his role leans on at what is left of it
        (`Leaning.cut`), and his first at his chance of playing it (`rules.chance`). Every game his club has left
        without a week to place them."""
        week = self.plan.week
        if week is None:
            return self._week(pickup), None
        rest = [p for p in self.roster if drop is None or p.player_key != drop.player.player_key]
        nights = [
            night
            for night in lineup.open_nights(pickup.player, rest, week, self.backs)
            if before is None or night < before
        ]
        found = self.plan.returning.get(pickup.player.player_key)
        back = found.returns if found else None
        played = sum(found.cut if found and back is not None and night >= back else 1.0 for night in nights)
        return self.game(pickup) * _doubted(played, nights, pickup), len(nights)

    def cost(self, drop: Reading | None, after: date | None = None, before: date | None = None) -> float:
        """What letting him go costs this week: each night, after `after` and before `before` where given, the
        lineup could seat nobody in his place, his first at his chance of playing it. His whole week where there
        is no week to place him; nothing for an open spot."""
        if drop is None:
            return 0.0
        week = self.plan.week
        if week is None:
            return self._week(drop)
        key = (drop.player.player_key, after, before)
        if key not in self.costs:
            nights = [
                night
                for night in lineup.needed_nights(drop.player, self.roster, week, self.backs)
                if (after is None or night > after) and (before is None or night < before)
            ]
            self.costs[key] = self.game(drop) * _doubted(len(nights), nights, drop)
        return self.costs[key]

    def back_soon(self, pickup: Reading) -> bool:
        """Whether he plays now, or is out with ESPN expecting him back within `RETURN_SOON`: a keeper may be."""
        if not ruled_out(pickup.player.status):
            return True
        week = self.plan.week
        return week is not None and pickup.back is not None and pickup.back <= week.today + RETURN_SOON

    def streamer(self, pickup: Reading, drops: Sequence[Reading | None]) -> Swap | None:
        """Him into an open spot, else against the weakest drop a game, then this week, whom he is worth an add
        over (`worth_an_add`). Never one ruled out: what he would add this week is games he misses."""
        if ruled_out(pickup.player.status):
            return None
        for drop in _weakest_first(drops, lambda d: (_game(d), self.cost(d))):
            gain, nights = self.gained(pickup, drop)
            cost = self.cost(drop)
            if worth_an_add(pickup, drop, gain, cost, self.game):
                return self._streamed(pickup, drop, gain - cost, nights)
        return None

    def keeper(self, pickup: Reading, drop: Reading | None, floor: float = 0.0) -> Swap | None:
        """Him against `drop`, whom he beats by `MARGIN` a game — or into an open spot, beating `floor` so — for the
        rest of the season.

        Never one whose role leans on a teammate due back (`Plan.returning`) — one at his position he has barely
        played beside, or one his split says he does clearly more without —
        nor one whose minutes have just grown (`settled`), nor one out beyond `RETURN_SOON` or with no firm
        return (`Reading.missed`), nor one in a slump (`Reading.cold`), nor one on a hot run his minutes or
        health do not back (`Reading.unproven`), nor one under `worth.HOT_MINUTES` a game, nor one whose role is
        falling (`worth.falling`, a teammate taking it where `Reading.taking` names one) — as it makes a player the
        first let go — nor one the roster's needs (`Plan.needs`) read as no better than the drop. One who keeps going
        missing (`Reading.fragile`) is weighed on the games he has played (`worth.kept_value`). One out now is added on the week's first day without
        games before his return, where it has one, so the drop plays until then.
        """
        if pickup.player.player_key in self.plan.returning or not settled(pickup) or not self.back_soon(pickup):
            return None
        if pickup.cold or pickup.missed or pickup.unproven or not _plays(pickup) or falling(pickup.role):
            return None
        season = self.season(pickup) - self.season(drop)
        if not beats(_kept(pickup), floor if drop is None else _kept(drop)) or season <= 0:
            return None
        week = self.plan.week
        out = ruled_out(pickup.player.status) and pickup.back is not None
        quiet = week.quiet(pickup.back) if week is not None and out and pickup.back is not None else []
        add_on = quiet[0] if quiet else None
        gain, nights = self.gained(pickup, drop)
        cost = self.cost(drop, add_on)
        return Swap(
            pickup,
            drop,
            "keeper",
            gain - cost,
            nights,
            add_on,
            self.needed(pickup, drop),
            season,
            self.spent(pickup, drop),
        )

    def best_keeper(self, pickup: Reading, drops: Sequence[Reading | None]) -> Swap | None:
        """Him as a keeper into an open spot, else over the weakest drop a game he beats (`keeper`)."""
        floor = min((_kept(d) for d in drops if d is not None), default=0.0)
        return next((s for d in _weakest_first(drops, _kept) if (s := self.keeper(pickup, d, floor))), None)

    def rival(self, kept: Swap, wire: Sequence[Reading], taken: Collection[str]) -> Swap:
        """`kept` with the runner-up for his drop: the best other keeper over it (`keeper`) whose value a game for
        the season is within `CLOSE` of his — a projection cannot tell the two apart, so the item names both."""
        bar = _kept(kept.pickup) * (1 - CLOSE)
        floor = _kept(kept.drop) if kept.drop is not None else 0.0
        found = [
            r
            for r in wire
            if r.player.player_key not in taken
            and r.player.player_key != kept.pickup.player.player_key
            and _kept(r) >= bar
            and self.keeper(r, kept.drop, floor) is not None
        ]
        best = max(found, key=lambda r: self.season(r), default=None)
        return replace(kept, rival=best) if best is not None else kept

    def _streamed(self, pickup: Reading, drop: Reading | None, gain: float, nights: int | None) -> Swap:
        """A stream of `pickup` over `drop`, with the close categories this week he really lifts and those he gives
        up (`Targeting.raised`, `Targeting.lowered`): by a material margin, a lift from at least an average figure.
        None without a forecast."""
        targeting = self.plan.targeting
        if targeting is None:
            return Swap(pickup, drop, "streamer", gain, nights)
        drop_line = drop.line if drop is not None else None
        return Swap(
            pickup,
            drop,
            "streamer",
            gain,
            nights,
            targets=tuple(targeting.raised(pickup.line, drop_line)),
            costs=tuple(targeting.lowered(pickup.line, drop_line)),
        )

    def needed(self, pickup: Reading, drop: Reading | None) -> tuple[str, ...]:
        """The categories the roster is shortest of that a game of `pickup` really raises over one of `drop`
        (`Targeting.raised`): by a material margin, from at least an average figure."""
        needs = self.plan.needs
        drop_line = drop.held if drop is not None else None
        return tuple(needs.raised(pickup.held, drop_line, counting=1.0)) if needs is not None else ()

    def spent(self, pickup: Reading, drop: Reading | None) -> tuple[str, ...]:
        """The categories the roster is shortest of that a game of `pickup` gives up against one of `drop`."""
        needs = self.plan.needs
        if needs is None or drop is None:
            return ()
        return tuple(needs.lowered(pickup.held, drop.held, counting=1.0))

    def bridge(self, keeper: Swap, day: date, wire: Sequence[Reading]) -> Swap | None:
        """For a keeper added on `day`, when nobody plays (`Swap.add_on`), the stream to hold his drop's spot until it:
        the one of `wire` adding most over the drop on the nights before it, worth an add on them alone
        (`worth_an_add`). He is let go for the keeper that day, so the drop goes now rather than then.

        Never one ruled out, nor a claim: waivers would eat the few nights he is there for.
        """
        drop = keeper.drop
        cost = self.cost(drop, before=day)
        found = []
        for pickup in wire:
            if ruled_out(pickup.player.status) or pickup.player.waiver_date is not None:
                continue
            gain, nights = self.gained(pickup, drop, before=day)
            if worth_an_add(pickup, drop, gain, cost, self.game):
                found.append(self._streamed(pickup, drop, gain - cost, nights))
        return max(found, key=lambda s: s.gain, default=None)


def _weighed(targeting: Targeting | None, reading: Reading, season: bool = False) -> float:
    """A game of him as `targeting` weighs its categories, nudged by his minutes; his value a game without one —
    this week's, or the season's (`season`)."""
    figures = reading.held if season else reading.line
    value = targeting.value(figures) if targeting is not None else None
    if value is None:
        return _kept(reading) if season else _game(reading)
    return value * reading.usage * (counted(reading) if season else 1.0)


def _doubted(played: float, nights: Sequence[date], reading: Reading) -> float:
    """`played` with his first night at his chance of playing it (`rules.chance`): a game-time call may sit."""
    return played - (1.0 - chance(reading.player.status)) if nights else played


def _weakest_first(
    drops: Sequence[Reading | None], key: Callable[[Reading], float | tuple[float, ...]]
) -> list[Reading | None]:
    """Open spots first, then a falling role or a slump (`_fading`), then by `key`, weakest first."""
    spots: list[Reading | None] = [d for d in drops if d is None]
    players = sorted((d for d in drops if d is not None), key=lambda d: (not _fading(d), key(d)))
    return [*spots, *players]


def _left(drops: Sequence[Reading | None], chosen: Sequence[Swap]) -> list[Reading | None]:
    """`drops` less those `chosen` already let go: each open spot, and each player, once."""
    left = list(drops)
    for swap in chosen:
        at = next((i for i, d in enumerate(left) if d is swap.drop), None)
        if at is not None:
            left.pop(at)
    return left


@dataclass(frozen=True)
class Added:
    """The week's adds as planned: the items, and who the planned ones bring in and let go — alternatives aside."""

    items: list[Action] = field(default_factory=list)
    joined: list[Reading] = field(default_factory=list)
    """Who the roster holds once the adds are made: each keeper, and each stream not let go again."""
    dropped: frozenset[str] = frozenset()
    """Who the planned adds let go, by Yahoo key."""


def _added(planned: Sequence[Swap], items: list[Action], held: Sequence[Swap] | None = None) -> Added:
    """`items`, with who `planned` lets go and who `held` (all of `planned` unless given) brings in for good."""
    kept = planned if held is None else held
    return Added(
        items,
        [s.pickup for s in kept],
        frozenset(s.drop.player.player_key for s in planned if s.drop is not None),
    )


def streams(
    roster: Sequence[Player],
    free_agents: Sequence[Player],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
    named: set[str],
    plan: Plan | None = None,
) -> list[Action]:
    """The week's adds as to-do items (`adds`)."""
    return adds(roster, free_agents, readings, adds_left, by_points, named, plan).items


def adds(
    roster: Sequence[Player],
    free_agents: Sequence[Player],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
    named: set[str],
    plan: Plan | None = None,
) -> Added:
    """The week's adds, planned within the adds left, each with its own drop and labelled a streamer or a keeper.

    A streamer is this week's games: over the weakest drop a game he is worth
    an add over (`worth_an_add`) on the nights he would start (`Plan.week`). A keeper is the rest of the
    season: better a game than the weakest drop a game by `MARGIN`, whatever
    his week, even out for a few days, but never one whose role leans on a
    teammate due back or has only just grown (`settled`).

    No two items name one pickup, nor one drop: an open roster spot
    (`Plan.open_spots`) is a drop of nobody, and is used first. Where the week
    is in play its games come first (`_chase`); where it is all but decided
    (`Plan.decided`) every add goes to the season (`_season`). Never more adds
    are planned than are left: a keeper offered beyond them is named as the
    alternative to the planned one it would replace.
    """
    if adds_left <= 0:
        return Added()
    plan = plan or Plan()
    weigh = Weigh(roster, readings, plan)
    owned = {p.player_key for p in roster}
    wire = [
        r
        for p in free_agents
        if p.player_key not in owned and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    drops: list[Reading | None] = [None] * plan.open_spots
    drops += droppable(roster, readings, named | plan.untouchable)
    if plan.decided:
        return _season(weigh, wire, drops, adds_left, by_points)
    return _chase(weigh, wire, drops, adds_left, by_points)


def _chase(
    weigh: Weigh, wire: Sequence[Reading], drops: Sequence[Reading | None], adds_left: int, by_points: bool
) -> Added:
    """A week in play: streams take the adds, never more than `STREAMS` nor
    than the adds left. A keeper takes one of them, where another is left for a
    stream or he adds more this week than the best stream, the best a game
    first; the next best, on a drop of his own, is named as his alternative.

    A keeper out now, added on the week's day without games, plans the adds as
    one sequence where two are left: a stream now in his drop's place, let go
    for him that day (`Weigh.bridge`). The plan takes the place of the stream
    the second add would have bought, where it adds more than that stream; a
    stream that still fits beside it stays.
    """
    plan = weigh.plan
    room = min(STREAMS, adds_left)
    chosen: list[Swap] = []

    def taken() -> set[str]:
        return {s.pickup.player.player_key for s in chosen}

    def best_stream() -> Swap | None:
        left = _left(drops, chosen)
        found = (s for r in wire if r.player.player_key not in taken() and (s := weigh.streamer(r, left)))
        return max(found, key=lambda s: s.gain, default=None)

    def best_keeper() -> Swap | None:
        left = _left(drops, chosen)
        found = (s for r in wire if r.player.player_key not in taken() and (s := weigh.best_keeper(r, left)))
        return min(
            found,
            key=lambda s: (bool(s.pickup.talk), -weigh.season(s.pickup), -s.gain),
            default=None,
        )

    first = best_stream()
    kept = best_keeper()
    if kept is not None and not (room > 1 or first is None or kept.gain >= first.gain):
        kept = None
    if kept is not None:
        chosen.append(kept)
    streamed: list[Swap] = []
    while len(streamed) < room - bool(kept) and (found := best_stream()):
        streamed.append(found)
        chosen.append(found)
    planned = _sequence(weigh, kept, streamed, wire, adds_left, room)
    if planned is not None and kept is not None:
        bridge, beside = planned
        chosen = [*beside, bridge, kept]
        alternative = best_keeper()
        items = [
            *(_item(s, by_points, plan) for s in beside),
            _chained(bridge, kept, by_points, plan),
            *([_item(alternative, by_points, plan, instead=kept)] if alternative else []),
        ]
        # The bridge is let go for the keeper: only the keeper and the streams beside stay.
        return _added([*beside, bridge], items, [*beside, kept])
    alternative = best_keeper() if kept is not None else None
    if kept is not None and alternative is None:
        kept = weigh.rival(kept, wire, taken())
    items = [
        *(_item(s, by_points, plan) for s in streamed),
        *([_item(kept, by_points, plan)] if kept else []),
        *([_item(alternative, by_points, plan, instead=kept)] if alternative and kept else []),
    ]
    return _added([*streamed, *([kept] if kept else [])], items)


SEASON_ADDS = 3
"""The most adds a decided week plans for the season: past three, each is a marginal keeper over a marginal drop."""

SEASON_POOL = 2
"""How many more pickups and drops than it plans a decided week weighs against each other (`_assign`)."""


def _season(
    weigh: Weigh, wire: Sequence[Reading], drops: Sequence[Reading | None], adds_left: int, by_points: bool
) -> Added:
    """A week all but decided: every add goes to a keeper, up to `SEASON_ADDS` and the adds left.

    A keeper in trade talk (`Reading.talk`) is planned only where no clean one is, and is otherwise at most the
    alternative. The keepers and drops are paired as a whole (`_assign`), so the best
    pickup does not take the one drop a second keeper needed. The best keeper
    left over, on a drop of his own, is named as the alternative to the
    planned one who adds least. In the order they are made: one out now on
    the day he is added.
    """
    budget = min(SEASON_ADDS, adds_left)
    pool = budget + SEASON_POOL
    keepers = [r for r in wire if weigh.best_keeper(r, drops) is not None]
    pickups = sorted(keepers, key=lambda r: (bool(r.talk), -weigh.season(r)))[:pool]
    entries = list(enumerate(_weakest_first(drops, _kept)[:pool]))
    floor = min((_kept(d) for d in drops if d is not None), default=0.0)
    pairs = [(at, swap) for r in pickups for at, d in entries if (swap := weigh.keeper(r, d, floor)) is not None]
    clean = [(at, swap) for at, swap in pairs if not swap.pickup.talk]
    chosen = _assign(clean, budget) or _assign(pairs, budget)
    if not chosen:
        return Added()
    places = {at for at, _ in chosen}
    picked = {s.pickup.player.player_key for _, s in chosen}
    spare = [s for at, s in pairs if at not in places and s.pickup.player.player_key not in picked]
    planned = sorted((s for _, s in chosen), key=lambda s: (s.add_on or date.min, -s.season))
    least = min(planned, key=lambda s: s.season)
    alternative = max(spare, key=lambda s: s.season, default=None)
    named = picked | ({alternative.pickup.player.player_key} if alternative else set())
    planned = [weigh.rival(s, wire, named) for s in planned]
    least = next(s for s in planned if s.pickup is least.pickup)
    items = [
        *(_item(s, by_points, weigh.plan) for s in planned),
        *([_item(alternative, by_points, weigh.plan, instead=least)] if alternative else []),
    ]
    return _added(planned, items)


def _assign(pairs: Sequence[tuple[int, Swap]], budget: int) -> list[tuple[int, Swap]]:
    """The pairs, at most `budget`, no two sharing a pickup or a drop (by its place in the list), that add most for
    the season between them. Every set is tried: the pool is a few of each."""
    best: list[tuple[int, Swap]] = []
    most = 0.0

    def walk(start: int, chosen: list[tuple[int, Swap]], total: float) -> None:
        nonlocal best, most
        if total > most:
            best, most = list(chosen), total
        if len(chosen) == budget:
            return
        for at in range(start, len(pairs)):
            place, swap = pairs[at]
            if any(place == p or swap.pickup.player.player_key == s.pickup.player.player_key for p, s in chosen):
                continue
            walk(at + 1, [*chosen, pairs[at]], total + swap.season)

    walk(0, [], 0.0)
    return best


PLAN_ADDS = 2
"""What a planned sequence spends: the stream now, and the keeper on the day nobody plays."""


def _sequence(
    weigh: Weigh, kept: Swap | None, streamed: Sequence[Swap], wire: Sequence[Reading], adds_left: int, room: int
) -> tuple[Swap, list[Swap]] | None:
    """The stream to bridge the keeper's wait, and the streams still beside it; None where no plan beats the
    single suggestions.

    The streams that fit beside it are those the adds left after the plan
    still cover; the plan must add more than those it displaces.
    """
    day = kept.add_on if kept else None
    if kept is None or day is None or adds_left < PLAN_ADDS:
        return None
    fits = max(0, min(room - 1, adds_left - PLAN_ADDS))
    beside = list(streamed[:fits])
    taken = {s.pickup.player.player_key for s in [kept, *beside]}
    bridge = weigh.bridge(kept, day, [r for r in wire if r.player.player_key not in taken])
    if bridge is None or bridge.gain < sum(s.gain for s in streamed[fits:]):
        return None
    return bridge, beside


def _chained(bridge: Swap, keeper: Swap, by_points: bool, plan: Plan) -> Action:
    """A stream now and the keeper it makes way for, as one item: 'Stream Turner now, drop Gobert; Thu 26 Nov drop
    Turner for Robinson'."""
    stream, kept = bridge.pickup.player, keeper.pickup.player
    drop = bridge.drop.player if bridge.drop is not None else None
    day = weekday_day_month(keeper.add_on) if keeper.add_on else ""
    games = f", {bridge.nights} games in open slots" if bridge.nights is not None else ""
    lead = f"Streamer until {day}: +{bridge.gain:.1f} {_unit(by_points)}{games}." + _targets(bridge) + " Then keeper: "
    dropped = f", drop {drop.name}" if drop else ""
    return Action(
        kind="waiver",
        urgency="now",
        title=f"Stream {stream.name} now{dropped}; {day} drop {stream.name} for {kept.name}",
        reason=lead
        + _item(replace(keeper, targets=(), costs=()), by_points, plan).reason.removeprefix("Keeper: ")
        + _pending(bridge.pickup),
        when=_today(plan),
        player_id=stream.player_key,
        drop=drop.player_key if drop else "",
        pickup="streamer",
        players=views.compared(
            [
                ("in", held(stream), bridge.pickup),
                *([("out", held(drop), bridge.drop)] if drop and bridge.drop else []),
                ("in", held(kept), keeper.pickup),
            ],
            by_points,
        ),
        key=f"plan:{stream.player_key}:{drop.player_key if drop else OPEN}:{kept.player_key}",
    )


OPEN = "open"
"""What a pickup's key names in place of a drop where it goes into an open roster spot."""


def _item(swap: Swap, by_points: bool, plan: Plan, instead: Swap | None = None) -> Action:
    """A pickup as the to-do list words it; `instead` is the planned add it is the alternative to, where it is one."""
    pickup, drop = swap.pickup, swap.drop
    claimed = pickup.player.waiver_date is not None
    unit = _unit(by_points)
    if swap.term == "keeper":
        against = f" against {_kept(drop):.1f}" if drop is not None else ""
        why = (
            f"Keeper: {_kept(pickup):.1f} {unit} a game{against}, for the rest of the season. "
            + _let_go(swap, "weakest a game you can drop")
            + _close(swap)
            + _needs(swap)
            + _out(swap)
            + _talk(pickup)
            + _shooting(pickup)
            + _history(pickup)
            + _rival(swap, plan)
        )
    else:
        games = f", {swap.nights} games in open slots" if swap.nights is not None else ""
        why = (
            f"Streamer: +{swap.gain:.1f} {unit} this week{games}. "
            + _let_go(swap, "weakest you can drop")
            + _targets(swap)
            + _leans(plan.returning.get(pickup.player.player_key))
            + _behind(plan)
        )
    lead = f"Alternative to {instead.pickup.player.name}: the same add. " if instead is not None else ""
    title = acquire(pickup.player, pickup.games if claimed else None)
    return Action(
        kind="waiver",
        urgency="now" if swap.term == "streamer" and plan.behind and not plan.decided else "soon",
        title=f"{title}, drop {drop.player.name}" if drop is not None else title,
        reason=lead
        + why
        + _form(pickup)
        + _form(drop)
        + _stakes(plan, swap)
        + _pending(pickup)
        + _waiting(pickup, plan.priority),
        when=weekday_day_month(swap.add_on) if swap.add_on else _today(plan),
        player_id=pickup.player.player_key,
        drop=drop.player.player_key if drop is not None else "",
        pickup=swap.term,
        players=views.compared(
            [
                ("in", held(pickup.player), pickup),
                *([("out", held(drop.player), drop)] if drop is not None else []),
                *([("in", held(swap.rival.player), swap.rival)] if swap.rival is not None else []),
            ],
            by_points,
        ),
        key=f"stream:{pickup.player.player_key}:{drop.player.player_key if drop is not None else OPEN}",
    )


CLOSE = 0.05
"""How near the `MARGIN` bar a keeper's value a game may clear it and still be called close: within a twentieth of
it. 11.1 over a drop's 9.2 clears 11.04 by half a percent: a projection cannot tell those two apart."""


def _close(swap: Swap) -> str:
    """' Close: 11.80 a game clears the 11.76 a keeper needs by 0%.' for a keeper only just over the bar, to the
    hundredth so the two never print alike; nothing otherwise."""
    if swap.drop is None:
        return ""
    bar = _kept(swap.drop) * (1 + MARGIN)
    mine = _kept(swap.pickup)
    if not bar or mine >= bar * (1 + CLOSE):
        return ""
    return f" Close: {mine:.2f} a game clears the {bar:.2f} a keeper needs by {mine / bar - 1:.1%}."


def _form(reading: Reading | None) -> str:
    """' Slump, Rudy Gobert: 4.1/g over his last 5 vs 6.8 projected · FG% .226, proj .470.' for a player on a
    streak (`worth.streak`), whom the item weighs on it; nothing otherwise."""
    found = reading.streak if reading is not None else None
    if found is None or reading is None:
        return ""
    return f" {found.label}, {reading.player.name}: {found.short()}."


def _shooting(reading: Reading) -> str:
    """' Shooting drags him: FG% .373.' where a percentage is among what drags his value (`Reading.weak`);
    nothing otherwise."""
    drags = views.weak(reading, rates=True)
    return f" Shooting drags him: {drags}." if drags else ""


def _history(reading: Reading) -> str:
    """' Injury history (Hip): out 28 Oct–2 Nov, 20–23 Nov; 12 of 18 games played, the season counted at 67%.' for
    a keeper who keeps going missing (`Reading.fragile`); nothing otherwise."""
    found = reading.availability
    if found is None or not reading.fragile:
        return ""
    spells = ", ".join(span(first, last) for first, last in found.spells)
    hurt = f" ({reading.injury})" if reading.injury else ""
    return (
        f" Injury history{hurt}: out {spells}; {found.played} of {found.scheduled} games played,"
        f" the season counted at {found.share:.0%}."
    )


def _rival(swap: Swap, plan: Plan) -> str:
    """' Or Brook Lopez, 10.4 a game: Turner leads in BLK, REB; Lopez in 3PTM, FT%.' for a keeper with a runner-up
    for the same drop (`Swap.rival`), the categories each leads in for the season by `worth.MATERIAL`; nothing
    otherwise."""
    rival = swap.rival
    if rival is None:
        return ""
    mine, theirs = swap.pickup, rival
    scaled = plan.needs.scales if plan.needs is not None else {}
    ahead, behind = edges(scaled, mine.held, theirs.held), edges(scaled, theirs.held, mine.held)
    lead = f" Or {theirs.player.name}, {_kept(theirs):.1f} a game"
    if not ahead and not behind:
        return lead + "."
    said = [
        f"{who.player.name.split()[-1]} leads in {', '.join(cats)}"
        for who, cats in ((mine, ahead), (theirs, behind))
        if cats
    ]
    return f"{lead}: {'; '.join(said)}."


def _talk(reading: Reading) -> str:
    """' Trade talk: Fri 21 Nov: Bucks open to trading Myles Turner.' for a player his news puts in it."""
    return f" {TRADE_TALK}: {reading.talk}." if reading.talk else ""


def _today(plan: Plan) -> str:
    """The day an add made now is made on, where there is a week to place it; empty otherwise."""
    return weekday_day_month(plan.week.today) if plan.week is not None else ""


def _let_go(swap: Swap, weakest: str) -> str:
    """'Gobert: weakest a game you can drop (FT% .441).', 'Gobert: role falling, 22 min a game, was 29.', 'Gobert: in
    a slump, and in trade talk.', or the open spot it goes into."""
    drop = swap.drop
    if drop is None:
        return "Into an open roster spot."
    role = drop.role
    if falling(role) and role is not None:
        return f"{drop.player.name}: role falling, {role.minutes:.0f} min a game, was {role.window:.0f}."
    if _fading(drop):
        return f"{drop.player.name}: in a slump, and in trade talk."
    return f"{drop.player.name}: {weakest}" + _drags(drop) + "."


def _stakes(plan: Plan, swap: Swap) -> str:
    """Why the add is for this week or the season: ' Week all but lost (2% to win): adds go to the season.', or for
    a stream, ' Week in play (35% to win).'; nothing without a forecast."""
    if plan.win is None:
        return ""
    chance_to_win = f"{plan.win:.0%} to win"
    if plan.decided:
        state = "lost" if plan.win < 0.5 else "won"
        return f" Week all but {state} ({chance_to_win}): adds go to the season."
    return f" Week in play ({chance_to_win})." if swap.term == "streamer" else ""


def _out(swap: Swap) -> str:
    """For a keeper out now: ' Out, back ~27 Nov: add him Thu 26 Nov, when nobody plays.'; nothing otherwise."""
    back = swap.pickup.back
    if not ruled_out(swap.pickup.player.status) or back is None:
        return ""
    if swap.add_on is None:
        return f" Out, back {approximately(back)}."
    return f" Out, back {approximately(back)}: add him {weekday_day_month(swap.add_on)}, when nobody plays."


def _targets(swap: Swap) -> str:
    """' This week targets BLK, FT%. This week costs REB.': the close categories he really lifts, then those he
    gives up; nothing for neither."""
    lifts = f" This week targets {', '.join(swap.targets)}." if swap.targets else ""
    return lifts + (f" This week costs {', '.join(swap.costs)}." if swap.costs else "")


def _needs(swap: Swap) -> str:
    """' Adds to your weakest: FT%, BLK. Costs your weakest: REB.': the categories the roster is shortest of that he
    really raises, then those he gives up; nothing for neither."""
    adds = f" Adds to your weakest: {', '.join(swap.targets)}." if swap.targets else ""
    return adds + (f" Costs your weakest: {', '.join(swap.costs)}." if swap.costs else "")


def _leans(found: Leaning | None) -> str:
    """For a streamer whose role leans on an absent teammate: ' Role leans on Duren back ~24 Nov: games after count
    50%.'; nothing otherwise."""
    return f" Role leans on {found.cell()}: games after count {found.cut:.0%}." if found else ""


def _behind(plan: Plan) -> str:
    """' Behind on games: 39 to 41 left (+3 if they stream).' where the opponent can start more, or could by
    streaming; nothing otherwise."""
    if not plan.behind or plan.volume is None:
        return ""
    mine, theirs = plan.volume
    return f" Behind on games: {mine} to {theirs} left{if_streamed(plan.streams)}."


def acquire(player: Player, games: int | None = None, *about: str, as_of: date | None = None) -> str:
    """How a to-do item has him: 'Pick up Jalen Duren (C, DET, 3 games)', or for a player on waivers a claim, with
    the day he clears them: 'Claim Brook Lopez (C, MIL, clears 25 Nov, 2 games)'. `about` leads the brackets, and
    `games` closes them where given; no brackets for nothing in them. `as_of` reads him as he will stand that day:
    a pickup, not a claim, where he clears waivers before it."""
    cleared = player.waiver_date
    if cleared is not None and as_of is not None and cleared < as_of:
        cleared = None
    parts = [
        *about,
        *([f"clears {day_month(cleared)}"] if cleared else []),
        *([f"{games} games"] if games is not None else []),
    ]
    named = f"{'Claim' if cleared else 'Pick up'} {player.name}"
    return f"{named} ({', '.join(parts)})" if parts else named


def fit(
    pickup: Reading,
    roster: Sequence[Player],
    readings: Mapping[str, Reading],
    by_points: bool,
    untouchable: Collection[str] = (),
) -> str:
    """'streams over Kel'el Ware: +12.3 value this week (4G vs 2G)'; empty where he clears no drop.

    The weakest player a game the to-do list would let go (`droppable`), never an
    `untouchable` one, he streams over (`streams_over`): what a stream of him would cost, read the
    way the list reads its own pickups.
    """
    drops = sorted(droppable(roster, readings, set(untouchable)), key=lambda d: (_game(d), _worth(d)))
    drop = next((d for d in drops if streams_over(pickup, d)), None)
    if drop is None:
        return ""
    gain = _worth(pickup) - _worth(drop)
    return (
        f"streams over {drop.player.name}: +{gain:.1f} {_unit(by_points)} this week ({pickup.games}G vs {drop.games}G)"
    )


def streams_over(pickup: Reading, drop: Reading) -> bool:
    """Whether `pickup` is worth an add over `drop` on their weeks as read (`worth_an_add`)."""
    return worth_an_add(pickup, drop, _worth(pickup), _worth(drop))


def worth_an_add(
    pickup: Reading, drop: Reading | None, gain: float, cost: float, game: Callable[[Reading], float] | None = None
) -> bool:
    """Whether `pickup`, adding `gain` this week where `drop` would have added `cost`, is worth an add: by `MARGIN`
    of the cost, by `STREAM_GAMES` of the drop's games, and at least as good a game — each game as `game` reads
    it, his value a game where none is given. Into an open spot (`drop` None), by `STREAM_GAMES` of his own.

    The extra games are this week's and the player let go is gone for good, so
    a stream never trades down a game for them, nor a solid player for a night.
    """
    per = game or _game
    if drop is None:
        return gain > 0 and gain >= STREAM_GAMES * max(per(pickup), 0.0)
    floor = STREAM_GAMES * max(per(drop), 0.0)
    return beats(gain, cost) and gain - cost >= floor and per(pickup) >= per(drop)


PROVISIONAL = " Provisional: schedule not final."
"""What an item weighed on games left adds while the NBA has days of the week to schedule."""


def _drags(reading: Reading) -> str:
    """What drags his value, in a category league: ' (FG% .380 · 2.9 TO)'; nothing where nothing does."""
    drags = views.weak(reading)
    return f" ({drags})" if drags else ""


def _waiting(reading: Reading, priority: int = 0) -> str:
    """For a claim, when he clears, your place in the order, and which of his games count:
    ' Waivers · clears Wed 25 Nov · you're #7: 2 games from then.'; nothing otherwise."""
    if reading.player.waiver_date is None:
        return ""
    return f" {clears(reading.player, priority)}: {views.games_left(reading) or 'no'} games from then."


def _pending(reading: Reading) -> str:
    return PROVISIONAL if reading.provisional else ""


def _worth(reading: Reading) -> float:
    return reading.worth or 0.0


def _plays(reading: Reading) -> bool:
    """Whether he plays a keeper's minutes, `worth.HOT_MINUTES` a game over his last few; true where unread."""
    return reading.minutes is None or reading.minutes >= HOT_MINUTES


def _kept(reading: Reading) -> float:
    return kept_value(reading) or 0.0


def _game(reading: Reading) -> float:
    return game_value(reading) or 0.0
