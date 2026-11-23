"""The next few basketball weeks of a roster: how many games its lineups can start, and the stream that adds some.

A basketball week is won on games as much as on who plays them: a club with
two games that week gives its players two, one with four gives four. The
schedule is known all season, so a week where your regulars' clubs barely play
can be seen a month out, while a pickup with four games can still stand in.

Each coming week counts the games your daily lineups can start — each day, the
most of the active players whose clubs play that the lineup's real slots can
seat (`lineup.seated`), as the to-do list counts them — and sets it beside the
usual one of these weeks. It names the regulars with few games, the
injured and when ESPN expects them back, and whether most clubs play four that
week. A stream is named only where it clears the margin every pickup on the
to-do list has to (`actions.streams_over`) and brings more games than the
player it replaces.

A week the NBA has yet to finish scheduling (`week.unsettled`: the Cup's
knockout days, before the eliminated clubs get their games) is provisional:
its counts are a floor, so it is neither short nor light, streams nothing, and
leaves the usual week to the weeks that are final.
"""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from thefrontoffice.adapters.outbound.competitions.injuries import approximately
from thefrontoffice.adapters.outbound.competitions.nba.actions import acquire, droppable, streams_over
from thefrontoffice.adapters.outbound.competitions.nba.lineup import seated
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, ruled_out
from thefrontoffice.adapters.outbound.competitions.nba.strength import club_nights, nights
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.domain.models import Outlook, WeekAhead

WEEKS_AHEAD = 4
"""As far as NFL's outlook looks: far enough to see a light stretch coming, near enough to act on it."""

LIGHT = 2
"""Games in a week that make a regular's light: a typical week gives three or four."""

HEAVY = 4
"""Games a club plays in a heavy week: the streamer's week."""

SHORT_BY = 4
"""Lineup games below the usual week that make one worth acting on: about a regular's week."""


@dataclass(frozen=True)
class Window:
    """One matchup week ahead: its dates, and the real games inside them."""

    week: int
    start: date
    end: date
    games: Sequence[ScheduledGame]
    unscheduled: Sequence[date] = ()
    """Its days the NBA has yet to schedule (`week.unsettled`): its games so far are a floor."""


def build(
    windows: Sequence[Window],
    roster: Sequence[Player],
    wire: Sequence[Player],
    readings: Mapping[str, Reading],
    returns: Mapping[str, date],
    adds: int,
    lineup: Sequence[str] = (),
) -> Outlook:
    """Each week of `windows`, soonest first, with a stream for any week worth one.

    `readings` give what a game of each player is worth, for everyone on
    `roster` and the `wire`; `returns` the day ESPN expects each injured
    player back. `adds` is the league's weekly limit: without any, nothing is
    streamed. `lineup` is the league's scoring slots, one per place
    (`lineup.slots`); without them a night seats as many as the roster
    starts today. A pickup or drop is named in one week only — once he is
    added, he is yours for the weeks after.
    """
    if not windows:
        return Outlook(measure="games")
    active = [p for p in roster if p.slot not in INJURED_SLOTS]
    slots = sum(1 for p in active if p.slot and p.slot != "BN") or len(active)
    regulars = _regulars(active, readings, slots)
    days = {w.week: {p.player_key: _days(p, w, returns.get(p.player_key)) for p in [*roster, *wire]} for w in windows}
    starts = {w.week: _starts(active, days[w.week], slots, lineup) for w in windows}
    final = [starts[w.week] for w in windows if not w.unscheduled]
    usual = statistics.median(final or starts.values())
    used: set[str] = set()
    weeks = []
    for w in windows:
        games = starts[w.week]
        provisional = bool(w.unscheduled)
        row = WeekAhead(
            week=w.week,
            points=float(games),
            short_by=usual - games,
            short=not provisional and games < usual - SHORT_BY,
            missing=[note for p in roster if (note := _missing(p, w, days[w.week], returns.get(p.player_key)))],
            light=[
                f"{p.name} ({n} games)"
                for p in regulars
                if not provisional and not ruled_out(p.status) and (n := len(days[w.week][p.player_key])) <= LIGHT
            ],
            heavy=_heavy(w),
            provisional=provisional,
        )
        if adds > 0 and not provisional and (row.short or row.light or row.heavy or row.missing):
            row = _streamed(row, roster, wire, readings, days[w.week], used, w.start, lineup)
        weeks.append(row)
    return Outlook(usual=usual, measure="games", weeks=weeks)


def _regulars(active: Sequence[Player], readings: Mapping[str, Reading], slots: int) -> list[Player]:
    """The players the lineup leans on: the best `slots` of the active roster by what a game of each is worth."""
    valued = [(value, p) for p in active if (r := readings.get(p.player_key)) and (value := game_value(r)) is not None]
    return [p for _, p in sorted(valued, key=lambda pair: -pair[0])[:slots]]


def _club_days(club: str, window: Window) -> list[date]:
    """The days `club` plays inside the window."""
    return club_nights(club, window.games)


def _days(player: Player, window: Window, back: date | None) -> list[date]:
    """The days he can play inside the window: his club's; while ruled out, only those from his return, if any."""
    return nights(player, window.games, back)


def _starts(active: Sequence[Player], days: Mapping[str, list[date]], slots: int, lineup: Sequence[str]) -> int:
    """The games daily lineups can start: each day, the most of the active players playing that `lineup`'s slots
    seat at once (`lineup.seated`); without them, never more than `slots`."""
    by_day: dict[date, list[Player]] = {}
    for p in active:
        for day in days.get(p.player_key, []):
            by_day.setdefault(day, []).append(p)
    return sum(seated(playing, lineup) if lineup else min(len(playing), slots) for playing in by_day.values())


def _missing(player: Player, window: Window, days: Mapping[str, list[date]], back: date | None) -> str:
    """'Ja Morant (O, back ~3 Dec: 2 of 4 games)': an injured player the week loses games of; empty otherwise."""
    if not ruled_out(player.status):
        return ""
    club = len(_club_days(player.team, window))
    playing = len(days.get(player.player_key, []))
    if playing >= club:
        return ""
    status = player.status
    if back is None:
        return f"{player.name} ({status}, no return date)"
    if not playing:
        return f"{player.name} ({status}, back {approximately(back)})"
    return f"{player.name} ({status}, back {approximately(back)}: {playing} of {club} games)"


def _heavy(window: Window) -> bool:
    """Whether more of the clubs playing that week play `HEAVY` games or more than play fewer."""
    counts: dict[str, int] = {}
    for g in window.games:
        for club in (g.home.upper(), g.away.upper()):
            counts[club] = counts.get(club, 0) + 1
    many = sum(1 for n in counts.values() if n >= HEAVY)
    return many > len(counts) - many


def _streamed(
    row: WeekAhead,
    roster: Sequence[Player],
    wire: Sequence[Player],
    readings: Mapping[str, Reading],
    days: Mapping[str, list[date]],
    used: set[str],
    start: date,
    lineup: Sequence[str] = (),
) -> WeekAhead:
    """The week with the free agent worth most in it who streams over a drop, where one does.

    The drop is the weakest player the to-do list would offer (`actions.droppable`),
    each weighed on this week's games; the pickup has to clear the same margin
    the to-do list's streams do, and play more games than the player he replaces.
    Neither is one already named for an earlier week. A player on waivers
    counts only the days from the one he clears them (`rules.playable_from`), and is
    named as a claim where he still sits on them when the week starts; by then
    he is free to add otherwise. Where the league's slots are known (`lineup`),
    the pickup's games are the nights he would start in the drop's place and
    the drop's those the lineup would start one fewer without him, as the
    to-do list counts them (`lineup.open_nights`, `lineup.needed_nights`).
    """
    week = {
        key: replace(r, games=len(days.get(key, []))) for key, r in readings.items() if key in days and key not in used
    }
    owned = {p.player_key for p in roster}
    drops = droppable([p for p in roster if p.player_key not in used], week, set())
    # Each on the wire as it lists him, which is what says whether he sits on waivers.
    pickups = sorted(
        (
            replace(r, player=p)
            for p in wire
            if p.player_key not in owned and not ruled_out(p.status) and (r := week.get(p.player_key))
        ),
        key=lambda r: -(r.worth or 0.0),
    )
    active = [p for p in roster if p.slot not in INJURED_SLOTS]
    for found in pickups:
        swap = next(
            (
                (pickup, drop)
                for d in drops
                for pickup, drop in [_fitted(found, d, active, days, lineup)]
                if _more_games(pickup, drop) and streams_over(pickup, drop)
            ),
            None,
        )
        if swap is None:
            continue
        pickup, drop = swap
        used |= {pickup.player.player_key, drop.player.player_key}
        p, d = pickup.player, drop.player
        return row.model_copy(
            update={
                "fix": f"{acquire(p, pickup.games or 0, p.position, p.team, as_of=start)}, "
                f"drop {d.name} ({drop.games} game{'' if drop.games == 1 else 's'})",
                "gain": float((pickup.games or 0) - (drop.games or 0)),
            }
        )
    return row


def _fitted(
    pickup: Reading, drop: Reading, active: Sequence[Player], days: Mapping[str, list[date]], lineup: Sequence[str]
) -> tuple[Reading, Reading]:
    """Both read on the games the lineup would start of them: the nights `pickup` would start in `drop`'s place,
    and those it would start one fewer without `drop`. As read, every game his club plays, without `lineup`."""
    if not lineup:
        return pickup, drop
    by_night: dict[date, list[Player]] = {}
    for p in active:
        for day in days.get(p.player_key, []):
            by_night.setdefault(day, []).append(p)
    key = drop.player.player_key

    def without(night: date) -> list[Player]:
        return [p for p in by_night.get(night, []) if p.player_key != key]

    opened = sum(
        1
        for night in days.get(pickup.player.player_key, [])
        if seated([*without(night), pickup.player], lineup) > seated(without(night), lineup)
    )
    needed = sum(
        1 for night in days.get(key, []) if seated(by_night.get(night, []), lineup) > seated(without(night), lineup)
    )
    return replace(pickup, games=opened), replace(drop, games=needed)


def _more_games(pickup: Reading, drop: Reading) -> bool:
    return (pickup.games or 0) > (drop.games or 0)
