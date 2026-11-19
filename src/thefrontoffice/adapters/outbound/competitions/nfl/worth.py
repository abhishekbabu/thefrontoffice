"""What a player is worth to a lineup: the one figure every decision about him weighs.

Split from the to-do list because more than it reads him by: who to drop, who
to pick up, who to stash, and how a free agent fits your lineup on the wire
(`views.fit`). One reading, so the page and the list never rank him two ways.
"""

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
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week

FORM_WEIGHT = 0.5
"""The share of a player's worth, when choosing who to drop, that is his recent form; the rest is his outlook.

Worth = (FORM_WEIGHT × form + (1 − FORM_WEIGHT) × outlook) × usage, where form is his points a game
over his last `ROLE_GAMES` games played — or, where those include games a regular teammate missed and
that teammate is back, his points a game beside him (`filling_in`) — and outlook is this week's
projection, or, in a week he does not play (a bye, a ruling), his season average. Either alone where
the other is unknown. Even weights: a projection alone drops a receiver scoring thirteen a game for
one scoring five whenever a bye or a quiet matchup dents the first's number, and form alone chases
one big afternoon. Usage is `usage`.
"""

USAGE_SWING = 0.1
"""The most his usage moves his worth, either way: a tenth.

Points follow snaps, and a role that is steady says more about next week than
one that swings. So a back, receiver or tight end on `REGULAR` of the snaps in
every one of his last `ROLE_GAMES` games is worth a tenth more; one whose share
moved by the smallest jump that counts (`RISES`) between them, and not because
his role grew, a tenth less — a fill-in, a part-timer, a starter losing his
place. A role grew where it is a trend, or where his latest game is his most
snaps of them: a debut ramping up has too few games before it for a trend. A
tenth because it is a tiebreak between comparable players, not a ranking of
its own. Quarterbacks, kickers and defenses are on for every
snap or none, so theirs says nothing.
"""


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
    """What his snaps over his last games multiply his worth by: 1 ± `USAGE_SWING`, or 1."""
    games = state.evidence.appearances.get(player_id, ())[-ROLE_GAMES:]
    shares = [game.snap_share for game in games if game.snap_share is not None]
    if state.evidence.positions.get(player_id) not in TARGET_POSITIONS or len(shares) < MIN_GAMES_FOR_AVERAGE:
        return 1.0
    if min(shares) >= REGULAR:
        return 1 + USAGE_SWING
    grew = player_id in state.evidence.trends or shares[-1] == max(shares)
    if not grew and max(shares) - min(shares) >= RISES["snaps"][0]:
        return 1 - USAGE_SWING
    return 1.0


def plays(state: Week, player: Projection) -> bool:
    """Whether this week's projection is about a game he will play: not a bye, nor a week he is ruled out of."""
    return (bool(player.opponent) or not state.scheduled) and not ruled_out(player.injury_status)


def outlook(state: Week, player: Projection) -> float | None:
    """What he should score: this week's projection, or his season average in a week he does not play.

    A bye or a one-week ruling projects nothing, which says nothing about him.
    """
    return player.points if plays(state, player) else average(state.evidence, player.player_id)


def worth(state: Week, player: Projection) -> float | None:
    """`FORM_WEIGHT` of his form and the rest his outlook, times his `usage`; either alone where the other is unknown, None with neither."""
    return blend(state, player, form(state, player))


def blend(state: Week, player: Projection, recent: float | None) -> float | None:
    """`worth` with `recent` as his form: what a teammate check reads his games without the teammate through."""
    ahead = outlook(state, player)
    if recent is None:
        blended = ahead
    elif ahead is None:
        blended = recent
    else:
        blended = FORM_WEIGHT * recent + (1 - FORM_WEIGHT) * ahead
    return None if blended is None else blended * usage(state, player.player_id)


def value(state: Week, player: Projection) -> float:
    """His `worth`, or his season average where there is nothing to read it from: what both sides of a move are weighed by."""
    found = worth(state, player)
    return season_average(state.evidence, player) if found is None else found
