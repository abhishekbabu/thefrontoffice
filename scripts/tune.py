"""Search the few settings that shape a player's range, on games already played.

Ranges are scored player by player — about two hundred player-games a
week, so a season is thousands — because matchups are too few to choose
settings on: thirty-odd of them move a score more by chance than any
setting does. The last finished week is held out: settings are chosen on
the weeks before it, and only recommended if they also beat the current
ones on the week they never saw. The matchup backtest is then re-run under
both, as the check that better ranges make better win chances.

Run with `just tune [competition]`; it reads the live league, so it needs
that competition configured and able to range its players.
"""

import itertools
import sys

from leagues import chosen, open_league

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.cli.output import print_error
from thefrontoffice.application.forecasting import ForecastEngine, score_ranges
from thefrontoffice.bootstrap import Registry
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import RangeScore
from thefrontoffice.domain.ports import RangeTuningProvider

MEANINGFUL = 0.01
"""A held-out loss at least this much lower, as a share, before a change is worth making:
below it the difference is the sample, not the setting."""


def line(name: str, result: RangeScore) -> str:
    return f"  {name:<26}{result.loss:>7.2f}{result.inside:>9.0%}{result.below:>8.0%}{result.above:>8.0%}{result.players:>9}"


def main() -> int:
    setup_logging()
    return run(bootstrap.registry(), chosen(sys.argv))


def run(registry: Registry, key: str) -> int:
    """Tune the competition `key` names; 1 where there is too little played to hold a week out."""
    try:
        _, provider, league = open_league(registry, key, RangeTuningProvider, "tuning player ranges")
        weeks = provider.played_weeks(league.league_id)
        if len(weeks) < 2:
            print("  Not enough finished weeks to tune and hold one out.")
            return 1
        search = provider.range_search()
        names = list(search.grid)
        candidates = [dict(zip(names, values, strict=True)) for values in itertools.product(*search.grid.values())]
        default = search.current
        trained = provider.ranged_games(league.league_id, weeks[:-1], [default, *candidates])
        trained_default, *scores = (score_ranges(games) for games in trained)
        best = min(range(len(candidates)), key=lambda i: scores[i].loss)
        best_settings = candidates[best]
        held_default, held_best = (
            score_ranges(games)
            for games in provider.ranged_games(league.league_id, weeks[-1:], [default, best_settings])
        )
        engine = ForecastEngine(provider)
        calibrations = {
            name: engine.backtest(league.league_id, weeks, settings)
            for name, settings in (("current", default), ("best", best_settings))
        }
    except FrontOfficeError as e:
        print_error(e)
        return 1

    print(f"\n  Tuned on weeks {weeks[0]}-{weeks[-2]}, held out week {weeks[-1]} ({league.name})\n")
    header = f"  {'':<26}{'loss':>7}{'10-90%':>9}{'<10%':>8}{'>90%':>8}{'players':>9}"
    print(header + "\n  (right: loss low, 80% inside, 10% each side)")
    print("  training weeks")
    print(line("current", trained_default))
    print(line("best", scores[best]))
    print("  held-out week")
    print(line("current", held_default))
    print(line("best", held_best))

    print("\n  matchups, all weeks (Brier: lower is better, 0.250 a coin flip)")
    for name, calibration in calibrations.items():
        print(f"  {name:<26}{calibration.brier:>7.3f}  over {calibration.matchups} matchups")

    changed = {k: v for k, v in best_settings.items() if v != default[k]}
    print()
    if not changed:
        print("  The current settings are already the best of the grid.")
    elif held_best.loss < held_default.loss * (1 - MEANINGFUL):
        print(f"  Recommend: {changed} — better on the week it never saw.")
    else:
        print(f"  Keep the current settings: {changed} is not meaningfully better on the held-out week.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
