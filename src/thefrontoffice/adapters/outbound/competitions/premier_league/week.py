"""One FPL gameweek, as the week view reads it: both squads, the fixtures, the swaps, the chips.

The gameweek is the unit this game is organised around, and a gameweek has a
state the week view has to know before it can draw a row: still to come, under
way, or over. A row to come shows FPL's projection; one under way shows what
the live feed says beside it; one over shows what the game credited.

The gameweek in focus is the one being played, or once it is over, the next —
since FPL keeps a gameweek current until the next deadline, days after its
last match. Any other gameweek can be browsed in the same shapes.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.premier_league import league, prompt
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    Lineup,
    Roster,
    fixtures_by_club,
    free_transfers,
    points_of,
    points_with_captain,
    projected_of,
    roster,
)
from thefrontoffice.adapters.outbound.competitions.premier_league.views import fixture_text
from thefrontoffice.adapters.outbound.competitions.premier_league.worth import Valuation
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Chip,
    Gameweek,
    H2HMatch,
    LiveStat,
    Opponent,
    Pick,
    Player,
)
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import (
    Action,
    Side,
    Spot,
    SpotScoring,
    Stat,
    StatGroup,
    Summary,
    Tone,
    WeekRange,
)

logger = logging.getLogger(__name__)

# What counts as a return and what counts as nothing, on FPL's own scale: two
# points is an appearance and no more, and a double-figure haul is a week made.
HAUL = 10
BLANK = 2


Projected = Callable[[Pick, Player], float | None]
"""What one row is projected for the gameweek shown, multiplied as its points would be; None where FPL says nothing."""


@dataclass(frozen=True)
class Week:
    """One gameweek's two sides, and how far it has got."""

    mine: Roster
    mine_side: Side
    opponent: Side | None
    fixtures: dict[str, list[Opponent]]
    score: tuple[int, int] | None
    """The tie's score, yours first, once under way; None in a classic league or before kickoff."""
    scored: int | None
    to_come: bool
    final: bool
    window: str


# ── which gameweek ──────────────────────────────────────────────────


def picked(client: FPLSource) -> Gameweek:
    """The latest gameweek whose picks are published: FPL's own `is_current`, which moves only at a deadline.

    Picks appear only once a deadline passes, so before the season opens
    no gameweek is current, there is nothing to read, and no squad view
    can be built.
    """
    current = client.current_gameweek()
    if current is None:
        raise FPLAPIError("Season not started; no squad yet.")
    return current


def focus(client: FPLSource) -> Gameweek:
    """The gameweek the week view is about: the one being played, or once it is over, the next.

    FPL keeps a gameweek `is_current` until the next deadline, days after its
    last match — so a finished one hands over to the gameweek still open,
    whose deadline is the next thing anybody can act on. Before the season the
    first gameweek is next; after it, the last stays.
    """
    current = client.current_gameweek()
    if current is not None and not current.finished:
        return current
    upcoming = client.upcoming_gameweek()
    if current is None or upcoming.id > current.id:
        return upcoming
    return current


def numbered(client: FPLSource, week: int) -> Gameweek:
    """The season's gameweek `week`.

    Raises:
        NotFoundError: the season has no such gameweek.
    """
    gameweek = next((g for g in client.get_gameweeks() if g.id == week), None)
    if gameweek is None:
        raise NotFoundError(f"gameweek {week} of the season")
    return gameweek


def week_range(client: FPLSource, week: int, current: int) -> WeekRange:
    return WeekRange(week=week, current=current, first=1, last=max(len(client.get_gameweeks()), current))


# ── the squads in it ────────────────────────────────────────────────


def squad_of(client: FPLSource, entry_id: int, gameweek: int) -> Roster:
    """A manager's fifteen as they set them for `gameweek`."""
    return roster(client.get_squad(entry_id, gameweek), client.get_players())


def tie(client: FPLSource, league_id: str, entry_id: int, week: int) -> H2HMatch | None:
    """Your head-to-head tie that gameweek; None in a classic league, or where it will not load.

    Only head-to-head leagues pair managers; a classic league is a table,
    so there is no opponent to show and saying so beats inventing one.
    """
    mini_league = league.league_of(client.get_entry(entry_id), league_id)
    if mini_league is None or not mini_league.is_h2h:
        return None
    try:
        return client.get_h2h_match(mini_league.id, entry_id, week)
    except FPLAPIError as e:
        # The rest of the page is about your own squad and still stands.
        logger.warning(f"Skipping the head-to-head opponent: {e}")
        return None


def tie_roster(client: FPLSource, found: H2HMatch | None, week: int) -> Roster | None:
    """The squad your opponent picked for `week`; None without a tie, or where it will not load."""
    if found is None:
        return None
    try:
        return squad_of(client, found.opponent_entry, week)
    except FPLAPIError as e:
        logger.warning(f"Skipping the head-to-head opponent's squad: {e}")
        return None


# ── the week view ───────────────────────────────────────────────────


def summary(
    client: FPLSource,
    entry_id: int,
    league_id: str,
    *,
    value: Valuation,
    best: Lineup,
    free: int,
    actions: list[Action],
) -> Summary:
    """The gameweek in focus: both squads, the fixtures, and what to do before the next deadline.

    The one being played while its matches are; once it is over, the one whose
    deadline is next, with the squad as last picked against its fixtures and
    its worth for it. The to-do list is about the next deadline either way,
    since that is the one a decision can still change: `best` is the eleven
    `value` picks, `free` the transfers left against it, `actions` the list.
    """
    shown_focus = focus(client)
    week = gather(client, entry_id, league_id, shown_focus, picked(client).id, value)
    upcoming = client.upcoming_gameweek()

    return Summary(
        headline=prompt.headline(
            week.mine.squad,
            free,
            best,
            points_with_captain(week.mine.starters, week.mine.captain, value),
            upcoming,
            value,
        ),
        mine=week.mine_side,
        opponent=week.opponent,
        actions=actions,
        fixtures=warnings(week.fixtures),
        boosts=chips(client, entry_id, shown_focus.id),
        window=week.window,
        weeks=week_range(client, shown_focus.id, shown_focus.id),
    )


def browsed(client: FPLSource, entry_id: int, league_id: str, week: int, value: Valuation) -> Summary:
    """Any other gameweek: one played with the fifteen picked for it and what each scored, one to come
    with the squad as it stands against that gameweek's fixtures.

    A gameweek to come is projected only where FPL has: the next one, by each
    player's worth for it (`value`). Further out the rows read "—", since FPL
    projects nothing there.

    Raises:
        NotFoundError: the season has no such gameweek.
    """
    gameweek = numbered(client, week)
    shown = gather(client, entry_id, league_id, gameweek, picked(client).id, value)
    return Summary(
        headline=browsed_headline(gameweek, shown),
        mine=shown.mine_side,
        opponent=shown.opponent,
        window=shown.window,
        weeks=week_range(client, week, focus(client).id),
    )


def gather(client: FPLSource, entry_id: int, league_id: str, gameweek: Gameweek, latest: int, value: Valuation) -> Week:
    """Both sides of one gameweek, as far as it has got: played, under way, or to come.

    `latest` is the latest gameweek with published picks. One before it is
    over; one after it is shown with the squads as last picked, since nobody's
    picks for it are published until its deadline passes, and projected at
    each player's worth for it (`value`).
    """
    to_come = gameweek.id > latest
    squad_week = latest if to_come else gameweek.id
    mine = squad_of(client, entry_id, squad_week)
    week_fixtures = client.get_fixtures(gameweek.id)
    live = {} if to_come else live_points(client, gameweek.id)
    projected = projected_of if gameweek.id == latest else projected_for(gameweek.id, latest, value)
    final = not to_come and (
        gameweek.finished or gameweek.id < latest or (bool(week_fixtures) and all(f.finished for f in week_fixtures))
    )
    # Minutes stand in for a kickoff where the fixtures were read before it.
    begun = final or (
        not to_come and (any(f.started for f in week_fixtures) or any(s.has_played for s in live.values()))
    )
    found = tie(client, league_id, entry_id, gameweek.id)
    score = league.tie_score(found, begun)
    # Your own rows are summed while the week is under way, since the live feed
    # moves faster than any total; once it is over, the game's own total stands.
    if not final:
        scored: int | None = mine.scored(live) if begun else None
    elif score is not None:
        scored = score[0]
    else:
        scored = points_in(client, entry_id, gameweek.id)

    fixtures = fixtures_by_club(week_fixtures, (p.team for p in mine.players))
    detail = f"GW{gameweek.id}" if squad_week == gameweek.id else f"GW{squad_week} picks"
    mine_side = Side(
        name=client.get_entry(entry_id).name,
        detail=detail,
        points=side_points(scored, mine, fixtures, projected),
        lineup=spots(mine, starting=True, fixtures=fixtures, live=live, projected=projected),
        bench=spots(mine, starting=False, fixtures=fixtures, live=live, projected=projected),
    )
    opponent = None
    if found is not None and (theirs := tie_roster(client, found, squad_week)) is not None:
        their_fixtures = fixtures_by_club(week_fixtures, (p.team for p in theirs.players))
        opponent = Side(
            name=found.opponent_name,
            detail=detail,
            # The game's own total rather than a sum of the rows: it already
            # accounts for auto-subs, which a squad list cannot show.
            points=side_points(score[1] if score else None, theirs, their_fixtures, projected),
            lineup=spots(theirs, starting=True, fixtures=their_fixtures, live=live, projected=projected),
            bench=spots(theirs, starting=False, fixtures=their_fixtures, live=live, projected=projected),
        )
    return Week(
        mine=mine,
        mine_side=mine_side,
        opponent=opponent,
        fixtures=fixtures,
        score=score,
        scored=scored,
        to_come=to_come,
        final=final,
        window=window(gameweek, final=final, begun=begun),
    )


def points_in(client: FPLSource, entry_id: int, week: int) -> int | None:
    """What FPL credited the gameweek with, auto-subs and all; None where its history will not say."""
    try:
        history = client.get_history(entry_id)
    except FPLAPIError as e:
        logger.warning(f"Continuing without gameweek {week}'s points: {e}")
        return None
    return next((row.points for row in history if row.event == week), None)


def live_points(client: FPLSource, gameweek: int) -> dict[int, LiveStat]:
    """What the squad has actually scored, or nothing before a ball is kicked.

    Enrichment, not a dependency: a gameweek with no live feed yet falls
    back to projections rather than failing.
    """
    try:
        return client.get_live(gameweek)
    except FPLAPIError as e:
        logger.warning(f"Continuing without live points: {e}")
        return {}


def allowance(client: FPLSource, entry_id: int, upcoming: int) -> int:
    """Free transfers going into `upcoming`, from the history and the chips spent.

    A chip list that will not load leaves the allowance unknowable — a
    Wildcard week reads as a week of no transfers — so it falls back to the
    floor of one, which is never wrong in the manager's favor.
    """
    history = client.get_history(entry_id)
    try:
        played = client.get_chips_played(entry_id)
    except FPLAPIError as e:
        logger.warning(f"Counting one free transfer without the chips played: {e}")
        return 1
    return free_transfers(history, upcoming, chips=played)


# ── rows ────────────────────────────────────────────────────────────


def spots(
    squad: Roster,
    *,
    starting: bool,
    fixtures: dict[str, list[Opponent]],
    live: dict[int, LiveStat],
    projected: Projected = projected_of,
) -> list[Spot]:
    return [
        spot(pick, player, fixtures, live, projected) for pick, player in squad.picked if pick.is_starting == starting
    ]


def spot(
    pick: Pick,
    player: Player,
    fixtures: dict[str, list[Opponent]],
    live: dict[int, LiveStat],
    projected: Projected = projected_of,
) -> Spot:
    """One row: what he was projected for this gameweek, and once his match is on, what he has scored.

    The projection is the gameweek's own (`ep_this`), multiplied as his points
    are, so a captain's guess and a captain's score are the same kind of
    number. Once his club has kicked off a nought is a nought, not a match
    still to come. A gameweek FPL has projected nobody for yet reads "—".
    """
    flag = player.availability
    stat = live.get(player.id)
    opponents = fixtures.get(player.team, [])
    state = scoring(opponents, stat)
    points = None if state == "projected" else points_of(pick, stat or LiveStat(points=0, minutes=0))
    expected = projected(pick, player)
    return Spot(
        player_id=str(player.id),
        player=player.name,
        mark="C" if pick.is_captain else "VC" if pick.is_vice_captain else "",
        detail=f"{player.position} · {player.team} {fixture_text(opponents)}" + (f" · {flag}" if flag else ""),
        value=f"{points} pts" if points is not None else f"{expected:.1f} xPts" if expected is not None else "—",
        tone=spot_tone(points, flag, blank=not opponents),
        scoring=state,
        scored="" if points is None else str(points),
        projection="" if expected is None else f"{expected:.1f}",
        kickoff=first_kickoff(opponents) if state == "projected" else None,
    )


def first_kickoff(opponents: list[Opponent]) -> datetime | None:
    """When his first match of the gameweek starts — a double's earlier one — or None where FPL set no time."""
    return min((o.kickoff for o in opponents if o.kickoff is not None), default=None)


def spot_tone(points: int | None, flag: str, *, blank: bool) -> Tone:
    """A haul is worth seeing, and so is a blank.

    Once somebody has played, the points are what the row is about: a doubt
    about a player who got through ninety minutes is no longer a doubt.
    Until then the availability flag and a missing fixture are the signal.
    """
    if points is None:
        return "warning" if flag or blank else "neutral"
    if points >= HAUL:
        return "good"
    return "warning" if points <= BLANK else "neutral"


def scoring(opponents: list[Opponent], stat: LiveStat | None) -> SpotScoring:
    """Final once every match his club has this gameweek is over, live from the first kickoff.

    Minutes stand in for a kickoff where the fixtures were read before it: a
    player on the pitch is in a match that has started, whatever the fixture
    list last said.
    """
    if opponents and all(o.finished for o in opponents):
        return "final"
    if any(o.started for o in opponents) or (stat is not None and stat.has_played):
        return "live"
    return "projected"


def warnings(fixtures: dict[str, list[Opponent]]) -> list[Stat]:
    """Only what is worth watching, not every fixture.

    Each player row already carries its own opponent and difficulty, so a
    full list of clubs repeats the page back at itself. A blank gameweek
    and a double are the two cases that change what a squad is worth.
    """
    notable = []
    for club, opponents in fixtures.items():
        if not opponents:
            notable.append(Stat(label=club, value="blank gameweek", tone="warning"))
        elif len(opponents) > 1:
            notable.append(Stat(label=club, value=f"double gameweek — {fixture_text(opponents)}", tone="good"))
    return notable


def side_points(scored: int | None, squad: Roster, fixtures: dict[str, list[Opponent]], projected: Projected) -> str:
    """A side's projection until one of its eleven has kicked off, then what it has scored beside it.

    A gameweek played has its points and no projection, since the one FPL
    carries now is for a later week; one further out than the next has neither.
    """
    figures = [projected(pick, player) for pick, player in squad.picked if pick.is_starting]
    known = [f for f in figures if f is not None]
    projection = f"{sum(known):.1f} proj" if known else ""
    kicked = any(o.started for player in squad.starters for o in fixtures.get(player.team, []))
    if scored is None and not kicked:
        return projection
    return " · ".join(part for part in (f"{scored or 0} pts", projection) if part)


def projected_for(week: int, current: int, value: Valuation) -> Projected:
    """The projection a browsed gameweek has: each player's worth for the next one alone, and none before or after it.

    A gameweek played has its points, and a projection beside them would be
    the current week's, not the one it was played on.
    """
    if week != current + 1:
        return lambda pick, player: None
    return lambda pick, player: value(player) * max(pick.multiplier, 1)


def browsed_headline(gameweek: Gameweek, week: Week) -> list[Stat]:
    """A gameweek to come by its deadline; one under way or played by its score, and FPL's average once there is one."""
    if week.to_come:
        return [Stat(label="Deadline", value=at_time(gameweek.deadline))]
    stats = []
    if week.score is not None:
        stats.append(Stat(label="Final" if week.final else "Live", value=f"{week.score[0]} – {week.score[1]}"))
    elif week.scored is not None:
        stats.append(Stat(label="Points", value=str(week.scored)))
    if gameweek.average_score:
        stats.append(Stat(label="Average", value=str(gameweek.average_score)))
    return stats


def window(gameweek: Gameweek, *, final: bool, begun: bool) -> str:
    """Which gameweek, and where it stands: final, in progress, or when it locks.

    A deadline is the useful date right up until it passes; after that the
    useful fact is that points are landing, and once every match is over, that
    they have landed. Rendered in UTC, which is what FPL publishes and what its
    own site shows every manager.
    """
    if final:
        return f"{gameweek.name} · final"
    if begun:
        return f"{gameweek.name} · in progress"
    return f"{gameweek.name} · deadline {at_time(gameweek.deadline)}"


# ── chips ───────────────────────────────────────────────────────────


def chips(client: FPLSource, entry_id: int, gameweek: int) -> StatGroup | None:
    """What is left of the season's chips, and what has become of the rest.

    The game issues a set per half — a Wildcard for GW2-19 and another for
    GW20-38 — and a chip played in one half spends only that half's. So each
    window is tracked on its own, and one row per chip reads the window open
    now: available until it closes, played, or when the next one opens.

    A chip whose windows have all passed is still listed: an unplayed Free
    Hit is a thing that was lost, and a row saying so is worth more than a
    row quietly missing.
    """
    try:
        issued = client.get_chips()
        played = client.get_chips_played(entry_id)
    except FPLAPIError as e:
        logger.warning(f"Continuing without chips: {e}")
        return None
    if not issued:
        return None

    stats: list[Stat] = []
    closing: list[int] = []
    for name in dict.fromkeys(c.name for c in issued):
        windows = sorted((c for c in issued if c.name == name), key=lambda c: c.start_event)
        spent = {w: next((p.event for p in played if p.name == name and w.covers(p.event)), None) for w in windows}
        stat = chip_stat(windows, spent, gameweek)
        stats.append(stat)
        now = next((w for w in windows if w.covers(gameweek)), None)
        if stat.tone == "good" and now is not None and now.stop_event < windows[-1].stop_event:
            closing.append(now.stop_event)
    available = sum(stat.tone == "good" for stat in stats)
    note = f"{available} available"
    if closing and (deadline := _deadline_of(client, min(closing))):
        note += f" · this half's expire at the GW{min(closing)} deadline, {deadline}"
    return StatGroup(title="Chips", stats=stats, note=note)


def _deadline_of(client: FPLSource, week: int) -> str:
    gameweek = next((g for g in client.get_gameweeks() if g.id == week), None)
    return f"{at_time(gameweek.deadline)} UTC" if gameweek else ""


def chip_stat(windows: list[Chip], spent: dict[Chip, int | None], gameweek: int) -> Stat:
    """One chip as the gameweek in focus finds it, from each of its windows.

    The window open now decides the row: unplayed, it is available until that
    window's last gameweek; played, it says when, and when the next window
    opens. With none open, the next to open says when, and once every window is
    behind, the last says whether it was played or lost.
    """
    label = windows[0].label
    now = next((w for w in windows if w.covers(gameweek)), None)
    later = next((w for w in windows if w.start_event > gameweek), None)
    lost = any(spent[w] is None for w in windows if w.stop_event < gameweek)
    suffix = " · one expired unplayed" if lost else ""
    if now is not None and spent[now] is None:
        return Stat(label=label, value=f"available until GW{now.stop_event}{suffix}", tone="good")
    if now is not None:
        again = f" · again from GW{later.start_event}" if later else ""
        return Stat(label=label, value=f"played GW{spent[now]}{again}{suffix}")
    if later is not None:
        return Stat(label=label, value=f"from GW{later.start_event}{suffix}")
    last = windows[-1]
    if spent[last] is not None:
        return Stat(label=label, value=f"played GW{spent[last]}")
    return Stat(label=label, value="expired", tone="warning")
