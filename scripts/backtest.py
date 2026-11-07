"""How well the win-probability simulation predicts, on weeks already played.

Every matchup of each finished week is rebuilt as it stood before kickoff —
that week's projections and starters, only the games before it — simulated,
and scored against who actually won. A Brier score near 0 is sharp and
right; 0.25 is what always saying "50%" earns.

Run with `just backtest [competition]`; it reads the live league, so it
needs that competition configured.
"""

import sys

from leagues import first_league

from thefrontoffice.adapters.inbound.cli.output import print_error
from thefrontoffice.application.forecasting import ForecastEngine
from thefrontoffice.bootstrap import REGISTRY, Registry
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.ports import ForecastProvider


def main() -> int:
    setup_logging()
    return run(REGISTRY, sys.argv[1] if len(sys.argv) > 1 else "nfl-sleeper")


def run(registry: Registry, key: str) -> int:
    """Backtest the competition `key` names; 1 where there is nothing to score."""
    try:
        entry = registry.find(key)
        competition = entry.open()
        provider = entry.as_port(competition, ForecastProvider, "simulating a matchup")
        league = first_league(competition, entry.label)
        weeks = provider.played_weeks(league.league_id)
        if not weeks:
            print("  No finished week to backtest yet.")
            return 1
        calibration = ForecastEngine(provider).backtest(league.league_id, weeks)
    except FrontOfficeError as e:
        print_error(e)
        return 1

    print(f"\n  {entry.label} — {league.name}, weeks {weeks[0]}-{weeks[-1]}")
    print(f"  {calibration.matchups} matchups · Brier {calibration.brier:.3f} (0.250 is a coin flip)\n")
    print(f"  {'chance given':<16}{'matchups':>9}{'predicted':>11}{'won':>7}")
    for bucket in calibration.buckets:
        span = f"{bucket.low:.0%}-{bucket.high:.0%}"
        print(f"  {span:<16}{bucket.matchups:>9}{bucket.predicted:>11.0%}{bucket.won:>7.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
