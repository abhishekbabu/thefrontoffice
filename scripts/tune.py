"""Search the few settings that shape a player's range, on games already played.

Ranges are scored player by player — about two hundred player-games a
week, so a season is thousands — because matchups are too few to choose
settings on: thirty-odd of them move a score more by chance than any
setting does. The last finished week is held out: settings are chosen on
the weeks before it, and only recommended if they also beat the current
ones on the week they never saw. The matchup backtest is then re-run under
both, as the check that better ranges make better win chances.

Run with `just tune`; it reads the live league.
"""

import itertools
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from thefrontoffice.adapters.outbound.competitions.nfl import outcomes  # noqa: E402
from thefrontoffice.adapters.outbound.platforms.sleeper.client import NFL  # noqa: E402
from thefrontoffice.application.forecasting import calibrate, score_ranges  # noqa: E402
from thefrontoffice.bootstrap import nfl_provider  # noqa: E402
from thefrontoffice.config.logging import setup_logging  # noqa: E402
from thefrontoffice.domain.errors import FrontOfficeError  # noqa: E402
from thefrontoffice.domain.models import RangeScore  # noqa: E402

MEANINGFUL = 0.01
"""A held-out loss at least this much lower, as a share, before a change is worth making:
below it the difference is the sample, not the setting."""

GRID = {
    "own_half": (2.0, 4.0, 8.0, 16.0),
    "max_ratio": (3.0, 4.0, 6.0),
    "projection_error": (0.0, 0.15, 0.3, 0.45),
}


def score(weeks: list, settings: outcomes.RangeSettings) -> RangeScore:
    """Every player-game in `weeks`, ranged from what was known before its week."""
    played = []
    for before, last, players in weeks:
        spread = outcomes.spreads(before, settings, pool_from=last)
        for projection, actual in players:
            # Conditional on playing: whether he plays is a different question,
            # and these are games he did.
            played.append((replace(outcomes.outcomes(projection, spread, settings=settings), plays=1.0), actual))
    return score_ranges(played)


def line(name: str, result: RangeScore) -> str:
    return f"  {name:<26}{result.loss:>7.2f}{result.inside:>9.0%}{result.below:>8.0%}{result.above:>8.0%}{result.players:>9}"


def main() -> int:
    setup_logging()
    try:
        provider = nfl_provider()
        league = provider.list_leagues()[0]
        current = provider.client.get_state(NFL).week
        weeks = list(range(2, current))
        if len(weeks) < 2:
            print("  Not enough finished weeks to tune and hold one out.")
            return 1
        data = {week: provider.played_week(league.league_id, week) for week in weeks}
    except FrontOfficeError as e:
        print(f"  ❌ {e}")
        return 1

    train, holdout = [data[w] for w in weeks[:-1]], [data[weeks[-1]]]
    candidates = [
        replace(outcomes.DEFAULT, own_half=own_half, max_ratio=max_ratio, projection_error=error)
        for own_half, max_ratio, error in itertools.product(
            GRID["own_half"], GRID["max_ratio"], GRID["projection_error"]
        )
    ]
    ranked = sorted(candidates, key=lambda s: score(train, s).loss)
    best, default = ranked[0], outcomes.DEFAULT

    print(f"\n  Tuned on weeks {weeks[0]}-{weeks[-2]}, held out week {weeks[-1]} ({league.name})\n")
    header = f"  {'':<26}{'loss':>7}{'10-90%':>9}{'<10%':>8}{'>90%':>8}{'players':>9}"
    print(header + "\n  (right: loss low, 80% inside, 10% each side)")
    print("  training weeks")
    print(line("current", score(train, default)))
    print(line("best", score(train, best)))
    print("  held-out week")
    held_default, held_best = score(holdout, default), score(holdout, best)
    print(line("current", held_default))
    print(line("best", held_best))

    print("\n  matchups, all weeks (Brier: lower is better, 0.250 a coin flip)")
    for name, settings in (("current", default), ("best", best)):
        played = [g for w in weeks for g in provider.played_matchups(league.league_id, w, settings)]
        print(f"  {name:<26}{calibrate(played).brier:>7.3f}  over {len(played)} matchups")

    changed = {k: getattr(best, k) for k in GRID if getattr(best, k) != getattr(default, k)}
    print()
    if best == default:
        print("  The current settings are already the best of the grid.")
    elif held_best.loss < held_default.loss * (1 - MEANINGFUL):
        print(f"  Recommend: {changed} — better on the week it never saw.")
    else:
        print(f"  Keep the current settings: {changed} is not meaningfully better on the held-out week.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
