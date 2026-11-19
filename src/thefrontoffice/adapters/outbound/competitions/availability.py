"""Whether a player will play his next game, by what his league says of him, as every competition reads it.

A player ruled out plays nothing until he is back, which each sport counts in
its own calendar. A doubtful or questionable one usually plays, so a list of
whom to pick up discounts him rather than dropping him: rough base rates, the
same whichever sport, applied to his next game alone — the designation is
about that one, not the games after it.
"""

DOUBTFUL = 0.25
"""The chance a doubtful player plays his next game."""

QUESTIONABLE = 0.8
"""The chance a questionable player — a game-time decision, day-to-day — plays his next game."""


def expected_games(games: float, chance: float) -> float:
    """Of the `games` he can play, those he should: the next at `chance`, the rest whole; none of none."""
    return max(games - (1 - chance), 0.0) if games else 0.0
