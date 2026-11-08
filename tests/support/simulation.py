"""Building the inputs and outputs of the simulations by hand, so a test can say what they must conclude."""

from collections.abc import Mapping, Sequence

from thefrontoffice.domain.models import MatchupInput, Outcomes, PlayedMatchup, PlayoffOdds

FEW = 2_000
"""Simulations enough to settle a clear case, few enough to keep the suite fast."""


def outcome(pid: str, *samples: float, plays: float = 1.0, floor: float = 0.0, remaining: float = 1.0) -> Outcomes:
    """One player's week drawn from `samples`, projected at their mean."""
    projection = sum(samples) / len(samples) if samples else 0.0
    return Outcomes(pid, pid.upper(), projection, samples, plays=plays, floor=floor, remaining=remaining)


def odds_split(win: float, loss: float) -> PlayoffOdds:
    """A playoff chance of one half overall, `win` with this week won and `loss` with it lost."""
    return PlayoffOdds(spots=6, playoffs=0.5, with_win=win, with_loss=loss, simulations=1)


class FakeForecast:
    """A `ForecastProvider` with no matchup and no week played; a test overrides `matchup` or `weeks`.

    Every matchup asked for is recorded in `asked`, by the candidates it was
    asked to price, and fails with `error` where given.
    """

    weeks: tuple[int, ...] = ()
    """The weeks already played, each of which rebuilds as no matchups at all."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked: list[list[str]] = []

    def matchup(self, candidates: Sequence[str]) -> MatchupInput | None:
        """This week's matchup, with a move for each of `candidates` that could start."""
        return None

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        self.asked.append(list(candidates))
        if self.error is not None:
            raise self.error
        return self.matchup(candidates)

    def played_weeks(self, league_id: str) -> list[int]:
        return list(self.weeks)

    def played_matchups(
        self, league_id: str, week: int, settings: Mapping[str, float] | None = None
    ) -> list[PlayedMatchup]:
        return []
