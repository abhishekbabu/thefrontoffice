"""Each basketball day's record on disk (`nba/day.DayLog`): every rostered player's Yahoo status that day (the last seen, and the last before his game tipped off),
the minutes the box scores gave him once the day stood, and every injury ESPN's report was seen giving him.

Beside the to-do decisions, the depth chart's starters and the pre-game projections, since like them it is the
app's own record rather than a platform's response: Yahoo keeps only a player's status now, and Sleeper's box
scores only a recent window. Kept for a season.
"""

from datetime import date, timedelta

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.competitions.nba.day import Hurt

KEEP_FOR = timedelta(days=200)
"""A season and its playoffs: a day is opened only within the season it is in."""

STATUS = "nba-status:"
PREGAME = "nba-pregame:"
MINUTES = "nba-minutes:"
INJURIES = "nba-injuries"


class DiskDayLog:
    def __init__(self, cache: DiskCache) -> None:
        self._cache = cache

    def statuses(self, day: date) -> dict[str, str]:
        stored = self._cache.get(f"{STATUS}{day.isoformat()}", KEEP_FOR)
        return {str(key): str(status) for key, status in stored.items()} if isinstance(stored, dict) else {}

    def keep_statuses(self, day: date, statuses: dict[str, str]) -> None:
        self._cache.set(f"{STATUS}{day.isoformat()}", statuses)

    def pregame(self, day: date) -> dict[str, str]:
        stored = self._cache.get(f"{PREGAME}{day.isoformat()}", KEEP_FOR)
        return {str(key): str(status) for key, status in stored.items()} if isinstance(stored, dict) else {}

    def keep_pregame(self, day: date, statuses: dict[str, str]) -> None:
        self._cache.set(f"{PREGAME}{day.isoformat()}", statuses)

    def minutes(self, day: date) -> dict[str, float]:
        stored = self._cache.get(f"{MINUTES}{day.isoformat()}", KEEP_FOR)
        return {str(key): float(played) for key, played in stored.items()} if isinstance(stored, dict) else {}

    def keep_minutes(self, day: date, minutes: dict[str, float]) -> None:
        self._cache.set(f"{MINUTES}{day.isoformat()}", minutes)

    def injuries(self) -> dict[str, list[Hurt]]:
        stored = self._cache.get(INJURIES, KEEP_FOR)
        if not isinstance(stored, dict):
            return {}
        return {
            str(key): [
                Hurt(
                    str(row["injury"]),
                    date.fromisoformat(row["first"]),
                    date.fromisoformat(row["last"]),
                    bool(row.get("rest")),
                )
                for row in rows
                if isinstance(row, dict) and {"injury", "first", "last"} <= row.keys()
            ]
            for key, rows in stored.items()
            if isinstance(rows, list)
        }

    def keep_injuries(self, injuries: dict[str, list[Hurt]]) -> None:
        self._cache.set(
            INJURIES,
            {
                key: [
                    {"injury": h.injury, "first": h.first.isoformat(), "last": h.last.isoformat(), "rest": h.rest}
                    for h in rows
                ]
                for key, rows in injuries.items()
            },
        )
