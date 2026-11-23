"""How an FPL player reads on a page: a squad or market row. The drawer that opens on him is `drawer.py`.

Split from the provider because it is the one question asked of a player in
every view — your squad, anybody else's, the market, a player opened on his
own — and the provider is the place a gameweek is gathered, not drawn.

Everything here reads the bootstrap catalog every other call already reads,
so depth costs nothing.
"""

from collections.abc import Callable

from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    Roster,
    Value,
    plays,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Opponent,
    Player,
    as_millions,
)
from thefrontoffice.domain.models import (
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    PlayerCard,
)


def squad_cards(squad: Roster, value: Value) -> list[PlayerCard]:
    """One table shape for any manager's fifteen, each at his worth for the gameweek to come (`value`)."""
    return [
        PlayerCard(
            player_id=str(player.id),
            ruled_out=not plays(player),
            columns={
                **_market_columns(player, value),
                SLOT_COLUMN: ("C" if pick.is_captain else "XI") if pick.is_starting else "BN",
            },
            values=_market_values(player, value),
        )
        for pick, player in squad.picked
    ]


def market_card(player: Player, value: Value) -> PlayerCard:
    return PlayerCard(
        player_id=str(player.id),
        ruled_out=not plays(player),
        columns=_market_columns(player, value),
        values=_market_values(player, value),
    )


WORTH_COLUMN = "Worth"
"""What he adds the gameweek to come (`worth.Worth.week`): what the market is sorted on."""


def _market_values(player: Player, value: Value) -> dict[str, float]:
    """The numbers behind the formatted columns, so any of them can be
    sorted on. "£15.5m" sorted as text sits below "£9.0m"."""
    return {
        "Price": player.cost / 10,
        WORTH_COLUMN: value(player),
        "xPts": player.expected_points,
        "Form": player.form,
        "Points": float(player.total_points),
        "xGI": player.expected_goal_involvements,
        "Owned": player.selected_by,
    }


def _market_columns(player: Player, value: Value) -> dict[str, str]:
    return {
        PLAYER_COLUMN: player.name,
        POSITION_COLUMN: player.position,
        "Club": player.team,
        "Price": as_millions(player.cost),
        WORTH_COLUMN: f"{value(player):.1f}",
        "xPts": f"{player.expected_points:.1f}",
        "Form": f"{player.form:.1f}",
        "Points": str(player.total_points),
        "xGI": f"{player.expected_goal_involvements:.2f}",
        "Owned": f"{player.selected_by:.1f}%",
        STATUS_COLUMN: player.availability,
    }


def fixture_text(opponents: list[Opponent], name_of: Callable[[str], str] = str) -> str:
    """A club's matches this gameweek as a row reads them: 'vs LIV (2), at MCI (4)'.

    `name_of` spells the opponent. A lineup row has room for three letters and
    a drawer has room for the club, so the caller decides.
    """
    if not opponents:
        return "no fixture"
    return ", ".join(f"{'vs' if m.home else 'at'} {name_of(m.club)} ({m.difficulty})" for m in opponents)
