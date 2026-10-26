"""The Fantasy Premier League game, standing in: a player built from the few fields a rule turns on."""

from thefrontoffice.adapters.outbound.platforms.fpl.types import Player


def player(
    pid: int,
    position: str,
    points: float,
    cost: int = 50,
    team: str = "ARS",
    *,
    status: str = "a",
    news: str = "",
    chance_of_playing: int | None = None,
    penalties_order: int | None = None,
    corners_order: int | None = None,
) -> Player:
    """A player whose form, points a game and expected points are all `points`, so one number sets him."""
    return Player(
        id=pid,
        name=f"P{pid}",
        full_name=f"Player {pid}",
        position=position,
        team=team,
        cost=cost,
        expected_points=points,
        form=points,
        points_per_game=points,
        total_points=int(points * 10),
        selected_by=5.0,
        minutes=900,
        status=status,
        news=news,
        chance_of_playing=chance_of_playing,
        penalties_order=penalties_order,
        corners_order=corners_order,
    )
