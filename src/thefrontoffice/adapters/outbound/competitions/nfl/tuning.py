"""The settings that shape a player's range, as `just tune` searches them."""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from thefrontoffice.adapters.outbound.competitions.nfl import evidence, outcomes
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.domain.models import Outcomes, RangeSearch

GRID: dict[str, tuple[float, ...]] = {
    "own_half": (2.0, 4.0, 8.0, 16.0),
    "max_ratio": (3.0, 4.0, 6.0),
    "projection_error": (0.0, 0.15, 0.3, 0.45),
}
"""The settings worth searching, and the values to try for each."""

SEARCH = RangeSearch(current={name: float(getattr(outcomes.DEFAULT, name)) for name in GRID}, grid=GRID)

PlayedWeek = tuple[evidence.Evidence, evidence.Evidence, list[tuple[Projection, float]]]
"""A finished week: what was known before it, last season, and each player's projection with what he scored."""


def settings(overrides: Mapping[str, float]) -> outcomes.RangeSettings:
    """The app's settings with `overrides` in place of the searched ones.

    Raises:
        KeyError: a setting the search does not cover.
    """
    if unknown := set(overrides) - set(GRID):
        raise KeyError(f"Not a searched setting: {', '.join(sorted(unknown))}")
    default = outcomes.DEFAULT
    return replace(
        default,
        own_half=overrides.get("own_half", default.own_half),
        max_ratio=overrides.get("max_ratio", default.max_ratio),
        projection_error=overrides.get("projection_error", default.projection_error),
    )


def ranged(weeks: Sequence[PlayedWeek], overrides: Mapping[str, float]) -> list[tuple[Outcomes, float]]:
    """Every player-game in `weeks`, ranged from what was known before its week, with what he scored."""
    chosen = settings(overrides)
    games = []
    for before, last, players in weeks:
        spread = outcomes.spreads(before, chosen, pool_from=last)
        for projection, actual in players:
            # Conditional on playing: whether he plays is a different question,
            # and these are games he did.
            games.append((replace(outcomes.outcomes(projection, spread, settings=chosen), plays=1.0), actual))
    return games
