"""The rules of the game: who plays, what a pick scores, picking an eleven, pricing a transfer.

Everything else in the competition asks here rather than restating a rule, so
that the market, the lineups and the live score cannot disagree about one.

Lineups and transfers have exact answers, so neither is asked of the model. Which legal eleven
maximises expected points is a small search over formations; what a transfer
costs is arithmetic on prices the game publishes. The model's job is the part
that is genuinely judgement — whether a projection is believable, whether a
run of fixtures is as kind as its difficulty ratings suggest, whether a knock
reported on Friday will clear by Saturday.

FPL constrains a lineup differently from a slot-based league: there are no named
slots, only a count of each position that must fall between a minimum and a
maximum. That is why this does not reuse the football lineup solver.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    FORMATION_LIMITS,
    STARTING_SIZE,
    ChipPlay,
    Fixture,
    GameweekResult,
    LiveStat,
    Opponent,
    Pick,
    Player,
    Squad,
    TransferMade,
)

RULED_OUT = frozenset({"i", "s", "u", "n"})
"""Injured, suspended, unavailable, not in the squad. Doubtful ("d") is not
among them: a doubt is flagged, priced and started like anyone else."""

MAX_FREE_TRANSFERS = 5
"""Free transfers bank up to five: one, plus the game's `max_extra_free_transfers` of four."""

TRANSFER_HIT = 4
"""Points deducted per transfer beyond the free allowance."""

TRANSFER_CHIPS = frozenset({"wildcard", "freehit"})
"""Chips whose week's transfers are free and leave the banked allowance where it was."""


def plays(player: Player) -> bool:
    """Whether the game expects this player to be able to feature.

    The one availability rule, read by the market and the lineups alike: a
    ruled-out status or a published nought percent says no, and anything else —
    a doubt included — says yes, with the doubt shown beside the player.
    """
    return player.chance_of_playing != 0 and player.status not in RULED_OUT


def effective_points(player: Player) -> float:
    """Expected points, zeroed for a player who will not feature.

    The game leaves a stale `ep_next` on a ruled-out player, and starting one is
    a guaranteed blank rather than a small return.
    """
    return player.expected_points if plays(player) else 0.0


def free_transfers(history: list[GameweekResult], upcoming: int, *, chips: Iterable[ChipPlay]) -> int:
    """How many free transfers are available going into gameweek `upcoming`.

    The public API does not expose this — only `my-team`, which needs a login —
    but it is fully determined by the rules and by transfers already made:

    - The squad is picked free for the manager's first gameweek, and the first free
      transfer arrives for the one after it.
    - Each later gameweek adds one, after its own transfers are spent; a hit takes the
      bank to nought, never below. The bank is capped at five.
    - A Wildcard or Free Hit week spends nothing and adds nothing: the bank carries
      over unchanged — the game's rule since 2024/25, which the hits charged in real
      histories bear out week for week.

    Falls back to a single transfer when the history is missing, which is the
    floor: it is never wrong in the manager's favor.
    """
    chip_weeks = {chip.event for chip in chips if chip.name in TRANSFER_CHIPS}
    played = sorted((row for row in history if row.event < upcoming), key=lambda row: row.event)
    if not played:
        return 1
    available = 1  # earned by the first gameweek, which the squad itself was picked for
    for row in played[1:]:
        if row.event in chip_weeks:
            continue
        available = min(MAX_FREE_TRANSFERS, max(0, available - row.transfers_made) + 1)
    return available


@dataclass(frozen=True)
class Roster:
    """A manager's fifteen for one gameweek, each player beside the pick that placed them.

    In pick order rather than expected-points order: the bench order is itself
    a decision, since auto-subs come on in the order the manager listed them.
    """

    squad: Squad
    picked: list[tuple[Pick, Player]]

    @property
    def players(self) -> list[Player]:
        return [player for _, player in self.picked]

    @property
    def starters(self) -> list[Player]:
        return [player for pick, player in self.picked if pick.is_starting]

    @property
    def bench(self) -> list[Player]:
        return [player for pick, player in self.picked if not pick.is_starting]

    @property
    def captain(self) -> Player | None:
        return next((player for pick, player in self.picked if pick.is_captain), None)

    def scored(self, live: dict[int, LiveStat]) -> int | None:
        """What the gameweek has scored so far, or None before anyone counted has played.

        Each player counts by their pick's multiplier, which is the game's own
        statement of the week's chips: 2 for the captain, 3 under Triple
        Captain, 0 on the bench unless Bench Boost made it 1.
        """
        counted = [(pick, live[player.id]) for pick, player in self.picked if pick.multiplier and player.id in live]
        if not any(stat.has_played for _, stat in counted):
            return None
        return sum(stat.points * pick.multiplier for pick, stat in counted)

    def projected(self) -> float:
        """What the gameweek being played was projected to score, counted as `scored` counts it."""
        return sum(player.expected_this * pick.multiplier for pick, player in self.picked)


def roster(squad: Squad, catalog: dict[int, Player]) -> Roster:
    """The picks joined to the players they name, in the order the manager set them."""
    picked = [(pick, catalog[pick.element]) for pick in squad.picks if pick.element in catalog]
    picked.sort(key=lambda pair: pair[0].position)
    return Roster(squad=squad, picked=picked)


def points_of(pick: Pick, stat: LiveStat) -> int:
    """What one row scored as the manager sees it: multiplied for an armband, raw on the bench."""
    return stat.points * max(pick.multiplier, 1)


def projected_of(pick: Pick, player: Player) -> float:
    """What one row was projected for the gameweek being played, multiplied as `points_of` multiplies."""
    return player.expected_this * max(pick.multiplier, 1)


def fixtures_by_club(fixtures: list[Fixture], clubs: Iterable[str]) -> dict[str, list[Opponent]]:
    """Each club's matches this gameweek.

    No match is a blank — every player of that club scores nothing — and two is
    a double; those are the two cases that change what a squad is worth.
    """
    return {club: [m for f in fixtures if (m := f.opponent_of(club))] for club in sorted(set(clubs))}


def formations() -> list[dict[str, int]]:
    """Every legal distribution of eleven players across the four positions."""
    legal = []
    gk_min, gk_max = FORMATION_LIMITS["GKP"]
    for goalkeepers in range(gk_min, gk_max + 1):
        for defenders in range(*_span("DEF")):
            for midfielders in range(*_span("MID")):
                forwards = STARTING_SIZE - goalkeepers - defenders - midfielders
                low, high = FORMATION_LIMITS["FWD"]
                if low <= forwards <= high:
                    legal.append({"GKP": goalkeepers, "DEF": defenders, "MID": midfielders, "FWD": forwards})
    return legal


def _span(position: str) -> tuple[int, int]:
    low, high = FORMATION_LIMITS[position]
    return low, high + 1


@dataclass(frozen=True)
class Lineup:
    """A starting eleven, its captain, and the bench behind it."""

    starters: list[Player]
    bench: list[Player]
    captain: Player | None
    formation: str
    """The shape in the game's own notation, outfielders only: '3-5-2'."""

    @property
    def points(self) -> float:
        """Expected points with the captain counted twice."""
        return points_with_captain(self.starters, self.captain)


def points_with_captain(starters: list[Player], captain: Player | None) -> float:
    """What an eleven expects, counting its captain twice.

    Comparing a captained total against an uncaptained one overstates the gap by
    roughly a captain's score, which is the largest single number on the page —
    so every comparison between two lineups has to go through here.
    """
    total = sum(effective_points(p) for p in starters)
    return round(total + (effective_points(captain) if captain else 0.0), 2)


def best_lineup(squad: list[Player]) -> Lineup:
    """The highest-expecting legal eleven from a fifteen.

    Searched over every legal formation rather than filled greedily: taking the
    best eleven players outright routinely produces an illegal shape, and
    filling the tightest position first can strand points on the bench when a
    cheap defender would have freed a midfield slot.
    """
    by_position: dict[str, list[Player]] = {}
    for player in squad:
        by_position.setdefault(player.position, []).append(player)
    for players in by_position.values():
        players.sort(key=lambda p: (-effective_points(p), -p.form, p.name))

    best: list[Player] = []
    best_total = -1.0
    best_shape: dict[str, int] = {}
    for shape in formations():
        if any(len(by_position.get(pos, [])) < count for pos, count in shape.items()):
            continue
        eleven = [p for pos, count in shape.items() for p in by_position[pos][:count]]
        total = sum(effective_points(p) for p in eleven)
        if total > best_total:
            best, best_total, best_shape = eleven, total, shape

    starting_ids = {p.id for p in best}
    bench = sorted(
        (p for p in squad if p.id not in starting_ids),
        # Goalkeepers can only be substituted for goalkeepers, so the reserve
        # keeper sits apart from the ordered outfield bench.
        key=lambda p: (p.position != "GKP", -effective_points(p)),
    )
    captain = max(best, key=effective_points) if best else None
    shape = "-".join(str(best_shape.get(pos, 0)) for pos in ("DEF", "MID", "FWD")) if best_shape else ""
    return Lineup(starters=best, bench=bench, captain=captain, formation=shape)


@dataclass(frozen=True)
class LineupChange:
    """A player who should start, and the one they displace."""

    start: Player
    drop: Player | None

    @property
    def gain(self) -> float:
        return round(effective_points(self.start) - (effective_points(self.drop) if self.drop else 0.0), 2)


def lineup_changes(current_starters: list[Player], best: Lineup) -> list[LineupChange]:
    """Every swap between the eleven as set and `best`, largest gain first.

    The set difference between the two elevens, paired so each swap is one a manager can
    make: a keeper only for a keeper, and like for like wherever a position has someone
    on each side. What is left changes the formation — a defender in, a midfielder out —
    and always brings in a position the best eleven holds more of for one it holds fewer
    of, so every swap, made in any order, leaves a legal eleven.

    Nothing is filtered on its own gain: a swap that loses a little can be the one that
    makes room for a bigger one, and together they add up to the best eleven's total.
    A same-position swap that changes nothing is left out, since it reaches no further.
    """
    current_ids = {p.id for p in current_starters}
    best_ids = {p.id for p in best.starters}
    coming_in = [p for p in best.starters if p.id not in current_ids]
    going_out = [p for p in current_starters if p.id not in best_ids]

    def strongest_first(players: list[Player]) -> list[Player]:
        return sorted(players, key=lambda p: (-effective_points(p), p.name))

    changes: list[LineupChange] = []
    unpaired_in: list[Player] = []
    unpaired_out: list[Player] = []
    for position in FORMATION_LIMITS:
        ins = strongest_first([p for p in coming_in if p.position == position])
        outs = list(reversed(strongest_first([p for p in going_out if p.position == position])))
        pairs = min(len(ins), len(outs))
        changes += [LineupChange(start=ins[i], drop=outs[i]) for i in range(pairs)]
        unpaired_in += ins[pairs:]
        unpaired_out += outs[pairs:]

    # Each position left over is in surplus on one side only, so any pairing across
    # them moves one place from a position with spare to one short of it.
    unpaired_in = strongest_first(unpaired_in)
    unpaired_out = list(reversed(strongest_first(unpaired_out)))
    changes += [
        LineupChange(start=player, drop=unpaired_out[i] if i < len(unpaired_out) else None)
        for i, player in enumerate(unpaired_in)
    ]
    kept = [c for c in changes if not (c.drop and c.drop.position == c.start.position and c.gain == 0)]
    return sorted(kept, key=lambda c: -c.gain)


MAX_OPTIONS_PER_PLAYER = 3
"""How many replacements to list for any one outgoing player."""


def selling_price(bought: int, now: int) -> int:
    """What the game pays for a player, in tenths of a million.

    A fall is passed on in full; a rise is halved, rounded down to the tenth — the
    game's `transfers_sell_on_fee` of 50%. Bought at £7.5m and now £7.8m, he sells for £7.6m.
    """
    if now <= bought:
        return now
    return bought + (now - bought) // 2


def purchase_prices(
    owned: Iterable[Player], transfers: list[TransferMade], chips: Iterable[ChipPlay]
) -> dict[int, int]:
    """What each owned player was bought for, by element id.

    The latest transfer that brought him in names its price. A Free Hit week's transfers
    are undone at the next deadline, so they price nobody. A player never transferred in
    was in the squad picked before the first deadline, at the season's opening price —
    and where the catalog does not carry that, his current price stands in.
    """
    free_hit_weeks = {chip.event for chip in chips if chip.name == "freehit"}
    bought: dict[int, TransferMade] = {}
    for transfer in transfers:
        if transfer.event in free_hit_weeks:
            continue
        latest = bought.get(transfer.element_in)
        if latest is None or transfer.time > latest.time:
            bought[transfer.element_in] = transfer
    return {
        p.id: bought[p.id].element_in_cost if p.id in bought else (p.start_cost if p.start_cost is not None else p.cost)
        for p in owned
    }


@dataclass(frozen=True)
class Transfer:
    """Swapping one squad player for one who is not in the squad."""

    out: Player
    incoming: Player
    sale: int
    """What the game pays for `out`, in tenths of a million: his selling price, not his price."""

    @property
    def cost(self) -> int:
        """What the swap costs from the bank, in tenths of a million.

        Negative when the incoming player is cheaper than the sale brings in, which frees money.
        """
        return self.incoming.cost - self.sale

    @property
    def gain(self) -> float:
        return round(effective_points(self.incoming) - effective_points(self.out), 2)


def affordable_transfers(
    squad: list[Player],
    market: list[Player],
    bank: int,
    *,
    selling: dict[int, int],
    limit: int,
) -> list[Transfer]:
    """The best single-player upgrades this squad can pay for, best gain first.

    `selling` is each squad player's selling price by element id; one it does not name
    sells at his current price.

    Only same-position swaps: FPL fixes how many of each position a squad holds,
    so a midfielder can only ever be replaced by a midfielder.
    """
    owned = {p.id for p in squad}
    candidates: dict[str, list[Player]] = {}
    for player in market:
        if player.id not in owned and plays(player):
            candidates.setdefault(player.position, []).append(player)

    # One row per incoming player, paired with whoever they most improve on.
    # Ranking raw pairs instead fills the list with the same premium striker
    # opposite each of the squad's forwards — one suggestion wearing five hats.
    best_by_target: dict[int, Transfer] = {}
    for out in squad:
        for incoming in candidates.get(out.position, []):
            transfer = Transfer(out=out, incoming=incoming, sale=selling.get(out.id, out.cost))
            if transfer.cost > bank or transfer.gain <= 0:
                continue
            existing = best_by_target.get(incoming.id)
            if existing is None or transfer.gain > existing.gain:
                best_by_target[incoming.id] = transfer
    # And at most a few alternatives for any one outgoing player, so the list
    # does not collapse onto the single weakest squad member.
    ranked = sorted(best_by_target.values(), key=lambda t: t.gain, reverse=True)
    seen: dict[int, int] = {}
    spread = []
    for transfer in ranked:
        count = seen.get(transfer.out.id, 0)
        if count >= MAX_OPTIONS_PER_PLAYER:
            continue
        seen[transfer.out.id] = count + 1
        spread.append(transfer)
    return spread[:limit]
