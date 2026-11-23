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
player on waivers is a claim, weighed on the games after he clears them
(`rules.playable_from`) and named as one.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.injuries import approximately
from thefrontoffice.adapters.outbound.competitions.nba import lineup, views
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, fits, ruled_out
from thefrontoffice.adapters.outbound.competitions.nba.teammates import RETURN_SOON, Leaning
from thefrontoffice.adapters.outbound.competitions.nba.week import BENCH, Today, if_streamed, off_il
from thefrontoffice.adapters.outbound.competitions.nba.worth import ROLE, Reading, Targeting, game_value
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

KEEPERS = 2
"""Keepers named at once: alternatives for the one add the list spends on the rest of the season."""

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
    `plan` is what weighs a pickup beyond the readings (`Plan`).
    """
    items = off_il(list(roster))
    items += starts(roster, readings, by_points, today)
    named = {pid for item in items for pid in (item.player_id, item.replaces) if pid}
    items += streams(roster, free_agents, readings, adds_left, by_points, named, plan)
    return items


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
    """Who you could let go, least worth this week first.

    Never a player in an injured slot — dropping him frees no active spot —
    nor one in the better `KEPT` of the roster by value a game, nor one whose
    minutes are growing now (`worth.rising`): his value a game is still
    catching up with his role. Nor one another item already moves, nor one
    with nothing to read him by: an unknown is not a weak player.
    """
    active = [
        r
        for p in roster
        if p.slot not in INJURED_SLOTS and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    ranked = sorted(active, key=lambda r: -_game(r))
    kept = {r.player.player_key for r in ranked[: round(len(ranked) * KEPT)]}
    open_to = [r for r in active if r.player.player_key not in kept | keep and r.worth is not None and not r.rising]
    return sorted(open_to, key=_worth)


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
    (`worth.Targeting`): what a pickup or drop is worth this week. None weighs every category alike."""

    @property
    def behind(self) -> bool:
        """Whether your opponent can start more games than you this week, counting the starts its adds left could
        still stream in (`streams`): a stream is then urged now."""
        return self.volume is not None and self.volume[0] < self.volume[1] + self.streams


@dataclass(frozen=True)
class Swap:
    """One pickup weighed against one drop."""

    pickup: Reading
    drop: Reading
    term: Pickup
    gain: float
    """What the swap adds this week."""
    nights: int | None
    """The games he would start this week (`lineup.open_nights`); None where there is no week to place them."""
    add_on: date | None = None
    """For a keeper out now, the day without games to add him on: the drop plays until then."""
    targets: tuple[str, ...] = ()
    """The close categories this week he adds most to over the drop (`Targeting.targets`), as the league names
    them."""


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
        targeting = self.plan.targeting
        value = targeting.value(reading.line) if targeting is not None else None
        return _game(reading) if value is None else value * reading.usage

    def targets(self, pickup: Reading, drop: Reading) -> tuple[str, ...]:
        """The close categories this week a game of `pickup` adds most to over one of `drop`; none without a
        forecast."""
        targeting = self.plan.targeting
        return tuple(targeting.targets(pickup.line, drop.line)) if targeting is not None else ()

    def _week(self, reading: Reading) -> float:
        """His whole week at this week's value a game: every game his club has left."""
        return self.game(reading) * reading.games if reading.per_game is not None and reading.games else 0.0

    def gained(self, pickup: Reading, drop: Reading, before: date | None = None) -> tuple[float, int | None]:
        """What he adds this week in `drop`'s place, and the games behind it: each night he fills an open slot,
        before `before` where given, those from the return of a teammate his role leans on at what is left of it
        (`Leaning.cut`). Every game his club has left without a week to place them."""
        week = self.plan.week
        if week is None:
            return self._week(pickup), None
        rest = [p for p in self.roster if p.player_key != drop.player.player_key]
        nights = [
            night
            for night in lineup.open_nights(pickup.player, rest, week, self.backs)
            if before is None or night < before
        ]
        found = self.plan.returning.get(pickup.player.player_key)
        back = found.returns if found else None
        played = sum(found.cut if found and back is not None and night >= back else 1.0 for night in nights)
        return self.game(pickup) * played, len(nights)

    def cost(self, drop: Reading, after: date | None = None, before: date | None = None) -> float:
        """What letting him go costs this week: each night, after `after` and before `before` where given, the
        lineup could seat nobody in his place. His whole week where there is no week to place him."""
        week = self.plan.week
        if week is None:
            return self._week(drop)
        key = (drop.player.player_key, after, before)
        if key not in self.costs:
            nights = lineup.needed_nights(drop.player, self.roster, week, self.backs)
            self.costs[key] = self.game(drop) * sum(
                1 for night in nights if (after is None or night > after) and (before is None or night < before)
            )
        return self.costs[key]

    def back_soon(self, pickup: Reading) -> bool:
        """Whether he plays now, or is out with ESPN expecting him back within `RETURN_SOON`: a keeper may be."""
        if not ruled_out(pickup.player.status):
            return True
        week = self.plan.week
        return week is not None and pickup.back is not None and pickup.back <= week.today + RETURN_SOON

    def streamer(self, pickup: Reading, drops: Sequence[Reading]) -> Swap | None:
        """Him against the weakest drop a game, then this week, whom he is worth an add over (`worth_an_add`)."""
        if ruled_out(pickup.player.status):
            return None
        for drop in sorted(drops, key=lambda d: (_game(d), self.cost(d))):
            gain, nights = self.gained(pickup, drop)
            if worth_an_add(pickup, drop, gain, self.cost(drop), self.game):
                cost = self.cost(drop)
                return Swap(pickup, drop, "streamer", gain - cost, nights, targets=self.targets(pickup, drop))
        return None

    def keeper(self, pickup: Reading, drops: Sequence[Reading]) -> Swap | None:
        """Him against the weakest drop a game he beats by `MARGIN` a game: better for the rest of the season.

        Never one whose role leans on a teammate due back (`Plan.returning`) — one at his position he has barely
        played beside, or one his split says he does clearly more without —
        nor one whose minutes have just grown (`settled`), nor one out beyond `RETURN_SOON`. One out now is added on the week's
        first day without games before his return, where it has one, so the
        drop plays until then.
        """
        if pickup.player.player_key in self.plan.returning or not settled(pickup) or not self.back_soon(pickup):
            return None
        drop = next((d for d in sorted(drops, key=_game) if beats(_game(pickup), _game(d))), None)
        if drop is None:
            return None
        week = self.plan.week
        out = ruled_out(pickup.player.status) and pickup.back is not None
        quiet = week.quiet(pickup.back) if week is not None and out and pickup.back is not None else []
        add_on = quiet[0] if quiet else None
        gain, nights = self.gained(pickup, drop)
        cost = self.cost(drop, add_on)
        return Swap(pickup, drop, "keeper", gain - cost, nights, add_on, self.targets(pickup, drop))

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
                found.append(Swap(pickup, drop, "streamer", gain - cost, nights, targets=self.targets(pickup, drop)))
        return max(found, key=lambda s: s.gain, default=None)


def streams(
    roster: Sequence[Player],
    free_agents: Sequence[Player],
    readings: Mapping[str, Reading],
    adds_left: int,
    by_points: bool,
    named: set[str],
    plan: Plan | None = None,
) -> list[Action]:
    """Free agents to add, each paired with a drop and labelled a streamer or a keeper.

    A streamer is this week's games: over the weakest drop a game he is worth
    an add over (`worth_an_add`) on the nights he would start (`Plan.week`). A keeper is the rest of the
    season: better a game than the weakest drop a game by `MARGIN`, whatever
    his week, even out for a few days, but never one whose role leans on a
    teammate due back or has only just grown (`settled`).

    The week comes first: streams take the adds, never more than `STREAMS`
    nor than the adds left. Keepers take one add between them, offered only
    where another is left for a stream or the best of them adds more this week
    than the best stream; up to `KEEPERS` are named, the best a game first, as
    alternatives that may share a drop.

    A keeper out now, added on the week's day without games, plans the adds as
    one sequence where two are left: a stream now in his drop's place, let go
    for him that day (`Weigh.bridge`). The plan takes the place of the stream
    the second add would have bought, where it adds more than that stream; a
    stream that still fits beside it stays. No more adds are planned than are left.
    """
    if adds_left <= 0:
        return []
    plan = plan or Plan()
    weigh = Weigh(roster, readings, plan)
    owned = {p.player_key for p in roster}
    wire = [
        r
        for p in free_agents
        if p.player_key not in owned and (r := readings.get(p.player_key)) and r.per_game is not None
    ]
    drops = droppable(roster, readings, named)
    room = min(STREAMS, adds_left)
    keepers = sorted((s for r in wire if (s := weigh.keeper(r, drops))), key=lambda s: (-_game(s.pickup), -s.gain))
    chosen: list[Swap] = []

    def best_stream() -> Swap | None:
        taken = {key for s in chosen for key in (s.pickup.player.player_key, s.drop.player.player_key)}
        left = [d for d in drops if d.player.player_key not in taken]
        found = (s for r in wire if r.player.player_key not in taken and (s := weigh.streamer(r, left)))
        return max(found, key=lambda s: s.gain, default=None)

    first = best_stream()
    kept = keepers[:KEEPERS] if keepers and (room > 1 or first is None or keepers[0].gain >= first.gain) else []
    chosen.extend(kept)
    streamed: list[Swap] = []
    while len(streamed) < room - bool(kept) and (found := best_stream()):
        streamed.append(found)
        chosen.append(found)
    planned = _sequence(weigh, kept, streamed, wire, adds_left, room)
    if planned is None:
        return [_item(s, by_points, plan) for s in [*streamed, *kept]]
    bridge, beside = planned
    return [
        *(_item(s, by_points, plan) for s in beside),
        _chained(bridge, kept[0], by_points, plan),
        *(_item(s, by_points, plan) for s in kept[1:]),
    ]


PLAN_ADDS = 2
"""What a planned sequence spends: the stream now, and the keeper on the day nobody plays."""


def _sequence(
    weigh: Weigh, kept: Sequence[Swap], streamed: Sequence[Swap], wire: Sequence[Reading], adds_left: int, room: int
) -> tuple[Swap, list[Swap]] | None:
    """The stream to bridge the first keeper's wait, and the streams still beside it; None where no plan beats the
    single suggestions.

    The streams that fit beside it are those the adds left after the plan
    still cover; the plan must add more than those it displaces.
    """
    day = kept[0].add_on if kept else None
    if day is None or adds_left < PLAN_ADDS:
        return None
    fits = max(0, min(room - 1, adds_left - PLAN_ADDS))
    beside = list(streamed[:fits])
    taken = {s.pickup.player.player_key for s in [*kept, *beside]} | {s.drop.player.player_key for s in beside}
    bridge = weigh.bridge(kept[0], day, [r for r in wire if r.player.player_key not in taken])
    if bridge is None or bridge.gain < sum(s.gain for s in streamed[fits:]):
        return None
    return bridge, beside


def _chained(bridge: Swap, keeper: Swap, by_points: bool, plan: Plan) -> Action:
    """A stream now and the keeper it makes way for, as one item: 'Stream Turner now, drop Gobert; Thu 26 Nov drop
    Turner for Robinson'."""
    stream, drop, kept = bridge.pickup.player, bridge.drop.player, keeper.pickup.player
    day = weekday_day_month(keeper.add_on) if keeper.add_on else ""
    games = f", {bridge.nights} games in open slots" if bridge.nights is not None else ""
    lead = f"Streamer until {day}: +{bridge.gain:.1f} {_unit(by_points)}{games}." + _targets(bridge) + " Then keeper: "
    return Action(
        kind="waiver",
        urgency="now",
        title=f"Stream {stream.name} now, drop {drop.name}; {day} drop {stream.name} for {kept.name}",
        reason=lead
        + _item(replace(keeper, targets=()), by_points, plan).reason.removeprefix("Keeper: ")
        + _pending(bridge.pickup),
        player_id=stream.player_key,
        drop=drop.player_key,
        pickup="streamer",
        players=views.compared(
            [
                ("in", held(stream), bridge.pickup),
                ("out", held(drop), bridge.drop),
                ("in", held(kept), keeper.pickup),
            ],
            by_points,
        ),
        key=f"plan:{stream.player_key}:{drop.player_key}:{kept.player_key}",
    )


def _item(swap: Swap, by_points: bool, plan: Plan) -> Action:
    """A pickup as the to-do list words it."""
    pickup, drop = swap.pickup, swap.drop
    claimed = pickup.player.waiver_date is not None
    unit = _unit(by_points)
    if swap.term == "keeper":
        why = (
            f"Keeper: {_game(pickup):.1f} {unit} a game against {_game(drop):.1f}, for the rest of the season. "
            f"{drop.player.name}: weakest a game you can drop" + _drags(drop) + "." + _targets(swap) + _out(swap)
        )
    else:
        games = f", {swap.nights} games in open slots" if swap.nights is not None else ""
        why = (
            f"Streamer: +{swap.gain:.1f} {unit} this week{games}. {drop.player.name}: weakest you can drop"
            + _drags(drop)
            + "."
            + _targets(swap)
            + _leans(plan.returning.get(pickup.player.player_key))
            + _behind(plan)
        )
    return Action(
        kind="waiver",
        urgency="now" if swap.term == "streamer" and plan.behind else "soon",
        title=f"{acquire(pickup.player, pickup.games if claimed else None)}, drop {drop.player.name}",
        reason=why + _pending(pickup) + _waiting(pickup),
        when=weekday_day_month(swap.add_on) if swap.add_on else "",
        player_id=pickup.player.player_key,
        drop=drop.player.player_key,
        pickup=swap.term,
        players=views.compared(
            [("in", held(pickup.player), pickup), ("out", held(drop.player), drop)],
            by_points,
        ),
        key=f"stream:{pickup.player.player_key}:{drop.player.player_key}",
    )


def _out(swap: Swap) -> str:
    """For a keeper out now: ' Out, back ~27 Nov: add him Thu 26 Nov, when nobody plays.'; nothing otherwise."""
    back = swap.pickup.back
    if not ruled_out(swap.pickup.player.status) or back is None:
        return ""
    if swap.add_on is None:
        return f" Out, back {approximately(back)}."
    return f" Out, back {approximately(back)}: add him {weekday_day_month(swap.add_on)}, when nobody plays."


def _targets(swap: Swap) -> str:
    """' This week targets BLK, FT%, TO.': the close categories he helps most; nothing without them."""
    return f" This week targets {', '.join(swap.targets)}." if swap.targets else ""


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


def fit(pickup: Reading, roster: Sequence[Player], readings: Mapping[str, Reading], by_points: bool) -> str:
    """'streams over Kel'el Ware: +12.3 value this week (4G vs 2G)'; empty where he clears no drop.

    The weakest player a game the to-do list would let go (`droppable`) he
    streams over (`streams_over`): what a stream of him would cost, read the
    way the list reads its own pickups.
    """
    drops = sorted(droppable(roster, readings, set()), key=lambda d: (_game(d), _worth(d)))
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
    pickup: Reading, drop: Reading, gain: float, cost: float, game: Callable[[Reading], float] | None = None
) -> bool:
    """Whether `pickup`, adding `gain` this week where `drop` would have added `cost`, is worth an add: by `MARGIN`
    of the cost, by `STREAM_GAMES` of the drop's games, and at least as good a game — each game as `game` reads
    it, his value a game where none is given.

    The extra games are this week's and the player let go is gone for good, so
    a stream never trades down a game for them, nor a solid player for a night.
    """
    per = game or _game
    floor = STREAM_GAMES * max(per(drop), 0.0)
    return beats(gain, cost) and gain - cost >= floor and per(pickup) >= per(drop)


PROVISIONAL = " Provisional: schedule not final."
"""What an item weighed on games left adds while the NBA has days of the week to schedule."""


def _drags(reading: Reading) -> str:
    """What drags his value, in a category league: ' (FG% .380 · 2.9 TO)'; nothing where nothing does."""
    drags = views.weak(reading)
    return f" ({drags})" if drags else ""


def _waiting(reading: Reading) -> str:
    """For a claim, which of his games count: ' On waivers until Wed 25 Nov: 2 games after.'; nothing otherwise."""
    cleared = reading.player.waiver_date
    if cleared is None:
        return ""
    return f" On waivers until {weekday_day_month(cleared)}: {views.games_left(reading) or 'no'} games after."


def _pending(reading: Reading) -> str:
    return PROVISIONAL if reading.provisional else ""


def _worth(reading: Reading) -> float:
    return reading.worth or 0.0


def _game(reading: Reading) -> float:
    return game_value(reading) or 0.0
