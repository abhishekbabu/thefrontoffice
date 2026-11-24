"""What a player is worth to a lineup: the one figure every decision about him weighs.

Split from the to-do list because more than it reads him by: who to start
(`lineup_value`, which the week's best lineup is solved on), who to drop, who
to pick up, who to stash, and how a free agent fits your lineup on the wire
(`views.fit`). One reading, so the page and the list never rank him two ways.
"""

from thefrontoffice.adapters.outbound.competitions import worth as shared
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    MIN_GAMES_FOR_AVERAGE,
    REGULAR,
    RISES,
    ROLE_GAMES,
    TARGET_POSITIONS,
    average,
    season_average,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.adapters.outbound.competitions.nfl.roles import heading, window
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week

# The blend and the usage nudge are every competition's (`competitions.worth`); what football reads
# them from is here. Worth = (FORM_WEIGHT × form + (1 − FORM_WEIGHT) × outlook) × usage, where form is
# his points a game over his last `ROLE_GAMES` games played — or, where those include games a regular
# teammate missed and that teammate is back, his points a game beside him (`filling_in`) — and outlook
# is this week's projection, or, in a week he does not play (a bye, a ruling), his season average.
#
# Usage is his snap share: a back, receiver or tight end on `REGULAR` of the snaps in every one of his
# last `ROLE_GAMES` games is steady; one whose share moved by the smallest jump that counts (`RISES`)
# between them, and not because his role grew (a trend, or his latest game his most snaps), swings.
# Quarterbacks, kickers and defenses are on for every snap or none, so theirs says nothing.


def filling_in(state: Week, player: Projection) -> Split | None:
    """The split on a regular teammate who is back, where his recent games were without him (see `HurtTeammates`)."""
    meta = state.players.get(player.player_id)
    return state.teammates.filling_in(meta) if meta is not None else None


def form(state: Week, player: Projection) -> float | None:
    """His points a game over his last few games played; None until he has played enough of them to say anything.

    Where those games were fill-in work for a teammate who is back, his points a
    game beside that teammate instead — or None where he has never played beside him.
    """
    role = state.evidence.roles.get(player.player_id)
    if role is None or role.games < MIN_GAMES_FOR_AVERAGE:
        return None
    split = filling_in(state, player)
    return role.points if split is None else split.alongside


def usage(state: Week, player_id: str) -> float:
    """What his snaps over his last games multiply his worth by: 1 ± `worth.USAGE_SWING`, or 1."""
    games = state.evidence.appearances.get(player_id, ())[-ROLE_GAMES:]
    shares = [game.snap_share for game in games if game.snap_share is not None]
    if state.evidence.positions.get(player_id) not in TARGET_POSITIONS:
        return 1.0
    return shared.usage(
        shares,
        steady_from=REGULAR,
        swings_by=RISES["snaps"][0],
        fewest=MIN_GAMES_FOR_AVERAGE,
        grew=player_id in state.evidence.trends,
    )


def plays(state: Week, player: Projection) -> bool:
    """Whether this week's projection is about a game he will play: not a bye, nor a week he is ruled out of."""
    return (bool(player.opponent) or not state.scheduled) and not ruled_out(player.injury_status)


def outlook(state: Week, player: Projection) -> float | None:
    """What he should score: this week's projection, or his season average in a week he does not play.

    A bye or a one-week ruling projects nothing, which says nothing about him.
    """
    return player.points if plays(state, player) else average(state.evidence, player.player_id)


def worth(state: Week, player: Projection) -> float | None:
    """`worth.FORM_WEIGHT` of his form and the rest his outlook, times his `usage`; either alone where the other is unknown, None with neither."""
    return blend(state, player, form(state, player))


def blend(state: Week, player: Projection, recent: float | None) -> float | None:
    """`worth` with `recent` as his form: what a teammate check reads his games without the teammate through."""
    blended = shared.blend(recent, outlook(state, player))
    return None if blended is None else blended * usage(state, player.player_id)


def value(state: Week, player: Projection) -> float:
    """His `worth`, or his season average where there is nothing to read it from: what both sides of a move are weighed by."""
    found = worth(state, player)
    return season_average(state.evidence, player) if found is None else found


def lineup_value(state: Week, player: Projection) -> float:
    """What this week's best lineup weighs him by: his `value` in a week he `plays`, nought in one he does not.

    A bye or a ruling leaves his value at his season, which no slot scores this week.
    """
    return value(state, player) if plays(state, player) else 0.0


def rest_of_season(state: Week, player: Projection) -> float | None:
    """What he is worth over the weeks left, the figure a drop is weighed by: his points a game this season beside
    his projection a game over the weeks ahead (`Week.ahead`), evenly, times his `usage`; either alone where the
    other is unknown.

    Neither this week's projection, which reads a bye or one soft matchup as the player, nor his last few games,
    which read one cold stretch as the player: a drop is for the rest of the season. Where his recent games were
    fill-in work for a teammate who is back, his season is his points a game beside that teammate (`filling_in`);
    where they follow his own return from an absence (`roles.window`), his points a game since.
    """
    split = filling_in(state, player)
    played = average(state.evidence, player.player_id) if split is None else split.alongside
    since, _, returned = window(state, player.player_id)
    if returned is not None and split is None:
        # Back from an absence: his games since are his role, and his season and projection have not caught up.
        played = sum(game.points for game in since) / len(since)
    blended = shared.blend(played, projected_ahead(state, player))
    return None if blended is None else blended * usage(state, player.player_id)


CALIBRATION_MOST = 0.25
"""The furthest his own record against Sleeper's projections moves what it projects him ahead, either way."""

CALIBRATION_SETTLES = 4
"""Games against stored projections it takes before his record counts for half its gap (`worth.settled`): two
games beating a projection are as often a soft fortnight as a projection that reads him low."""

ROLE_TILT = 0.1
"""How far a role heading up or down (`roles.heading`) moves what he is projected ahead: a tenth, the way usage
moves a worth — a projection lags a role, and the drop order already ranks by it first."""


def projected_ahead(state: Week, player: Projection) -> float | None:
    """Sleeper's projection a game over the weeks left (`Week.ahead`), read against how his games have gone against
    its projections so far (`calibration`) and where his role is heading (`ROLE_TILT`); None where it has none."""
    ahead = state.ahead.get(player.player_id)
    if ahead is None:
        return None
    found = heading(state, player.player_id)
    tilt = {"rising": 1 + ROLE_TILT, "falling": 1 - ROLE_TILT}.get(found.direction if found else "", 1.0)
    return ahead * calibration(state, player.player_id) * tilt


def calibration(state: Week, player_id: str) -> float:
    """How far his games have run over or under what Sleeper projected for them (`Week.past`), as a factor of 1 ±
    `CALIBRATION_MOST`, pulled toward 1 while he has few games against it (`CALIBRATION_SETTLES`)."""
    pairs = [
        (game.points, projected)
        for game in state.evidence.appearances.get(player_id, ())
        if (projected := state.past.get(game.week, {}).get(player_id, 0.0)) > 0
    ]
    projected = sum(p for _, p in pairs)
    if not projected:
        return 1.0
    pull = shared.settled(len(pairs), CALIBRATION_SETTLES) * (sum(scored for scored, _ in pairs) / projected - 1)
    return 1 + max(-CALIBRATION_MOST, min(CALIBRATION_MOST, pull))
