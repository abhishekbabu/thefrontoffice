"""Remove caches and build artefacts.

Written in Python rather than shell so `just clean` behaves the same on Windows,
macOS and Linux. Never touches .env, .yahoofantasy, or anything else holding
credentials.
"""

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TOOL_CACHES = (".ruff_cache", ".pytest_cache", ".pyrefly_cache")

# The platform caches, one directory each. Named here rather than read from
# settings so that cleaning never needs a valid .env to run.
DATA_CACHES = (".yahoo_cache", ".sleeper_cache", ".fpl_cache")


def _remove(path: Path) -> bool:
    """Delete a file or directory. Returns whether anything was removed."""
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Only remove the platform caches, forcing a refetch on the next run.",
    )
    args = parser.parse_args()

    removed = 0

    if args.data_only:
        for name in DATA_CACHES:
            if _remove(PROJECT_ROOT / name):
                removed += 1
        print(f"Platform caches cleared ({removed} removed).")
        return 0

    for name in TOOL_CACHES + DATA_CACHES:
        if _remove(PROJECT_ROOT / name):
            removed += 1

    # Skip .venv — walking it is slow and its bytecode is not ours to manage.
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        if ".venv" in pycache.parts:
            continue
        if _remove(pycache):
            removed += 1

    for egg_info in PROJECT_ROOT.rglob("*.egg-info"):
        if ".venv" in egg_info.parts:
            continue
        if _remove(egg_info):
            removed += 1

    print(f"Cleaned ({removed} item{'s' if removed != 1 else ''} removed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
