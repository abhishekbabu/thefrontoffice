"""How well the win-probability simulation predicts, on weeks already played.

Every matchup of each finished week is rebuilt as it stood before kickoff —
that week's projections and starters, only the games before it — simulated,
and scored against who actually won. A Brier score near 0 is sharp and
right; 0.25 is what always saying "50%" earns.

Run with `just backtest [competition]`; it reads the live league, so it
needs that competition configured.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from thefrontoffice.adapters.outbound.platforms.sleeper.client import NFL, SleeperClient  # noqa: E402
from thefrontoffice.bootstrap import find, forecast_engine  # noqa: E402
from thefrontoffice.config.logging import setup_logging  # noqa: E402
from thefrontoffice.domain.errors import FrontOfficeError  # noqa: E402
from thefrontoffice.domain.ports import ForecastProvider  # noqa: E402


def main() -> int:
    setup_logging()
    key = sys.argv[1] if len(sys.argv) > 1 else "nfl-sleeper"
    entry = find(key)
    if entry is None or not entry.is_configured():
        print(f"  ❌ {key} is not a configured competition.")
        return 1
    try:
        provider = entry.build()
        if not isinstance(provider, ForecastProvider):
            print(f"  ❌ {entry.label} cannot be simulated yet.")
            return 1
        league = provider.list_leagues()[0]
        week = SleeperClient().get_state(NFL).week
        weeks = list(range(2, week))  # week 1 has no games before it to shape a range
        calibration = forecast_engine(provider).backtest(league.league_id, weeks)
    except FrontOfficeError as e:
        print(f"  ❌ {e}")
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
