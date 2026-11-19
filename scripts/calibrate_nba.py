"""Fit the spreads a basketball category league's odds are priced with, and check them on seasons played.

The fit reads the season finished last: every week of its rostered-calibre
players, what was projected for each beside what he did. It prints the spreads
to commit as `strength.FITTED`, with how the categories move together. The
check then deals leagues from both that season and the one being played, and
scores how each set of spreads called their categories and weeks — the season
being played is one the committed spreads never saw. A Brier score near 0 is
sharp and right; 0.25 is what always saying "50%" earns.

Run with `just calibrate-nba`; it reads Sleeper's public box scores and
projections, so it needs no league or login.
"""

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.cli.output import print_error
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import ODDS_MODELS, Calibration, OddsCheck, OddsFit
from thefrontoffice.domain.ports import OddsTuning


def main() -> int:
    setup_logging()
    return run(bootstrap.odds_tuning())


def run(tuning: OddsTuning) -> int:
    """Fit on the season finished last and check on it and the one being played; 1 where either cannot be read."""
    try:
        fitted, checked = tuning.seasons()
        found = tuning.fit_odds(fitted)
        checks = [tuning.check_odds(season, model) for season in (fitted, checked) for model in ODDS_MODELS]
    except FrontOfficeError as e:
        print_error(e)
        return 1
    _fit(found)
    for check in checks:
        _check(check)
    return 0


def _fit(found: OddsFit) -> None:
    print(f"\n  Fitted on {found.player_weeks} player-weeks of the {found.season} season")
    print(f"  games missed {found.missed:.3f}\n")
    print(f"  {'':<8}{'typical':>9}{'kept':>7}{'spread':>8}{'game':>7}{'loading':>9}   (spread: form, or rate)")
    for label, typical in found.typical.items():
        print(
            f"  {label:<8}{typical:>9.3f}"
            + _cell(found.kept.get(label), 7)
            + _cell(found.form.get(label, found.rate.get(label)), 8)
            + _cell(found.game.get(label), 7)
            + _cell(found.loadings.get(label), 9)
        )
    print("\n  how each category's miss moves with each other's")
    print("  " + " " * 6 + "".join(f"{label:>7}" for label in found.correlation))
    for label, row in found.correlation.items():
        print(f"  {label:<6}" + "".join(f"{value:>+7.2f}" for value in row.values()))


def _cell(value: float | None, width: int) -> str:
    return f"{value:>{width}.2f}" if value is not None else " " * width


def _check(check: OddsCheck) -> None:
    print(f"\n  {check.season} season, {check.weeks} weeks — {check.model}")
    for name, calibration in (("categories", check.categories), ("weeks", check.matchups)):
        print(f"  {name}: {calibration.matchups} called · Brier {calibration.brier:.4f}")
        print(_buckets(calibration))


def _buckets(calibration: Calibration) -> str:
    return "    " + "  ".join(
        f"{bucket.predicted:.0%}→{bucket.won:.0%} ({bucket.matchups})" for bucket in calibration.buckets
    )


if __name__ == "__main__":
    raise SystemExit(main())
