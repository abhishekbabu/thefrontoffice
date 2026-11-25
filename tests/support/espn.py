"""A stand-in for ESPN's public site API, which the NFL and the NBA both read."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from thefrontoffice.adapters.outbound.platforms.espn.types import Athlete, InjuryReport, NewsArticle, ScoreboardGame


class FakeESPN:
    """Stands in for ESPNClient: each club's articles, keyed by ESPN's abbreviation."""

    def __init__(
        self,
        news: dict[str, list[NewsArticle]] | None = None,
        error: Exception | None = None,
        scoreboard: list[ScoreboardGame] | None = None,
        scoreboard_error: Exception | None = None,
        injuries: list[InjuryReport] | None = None,
        injuries_error: Exception | None = None,
    ) -> None:
        self.news = news or {}
        self.injuries = injuries or []
        self.injuries_error = injuries_error
        self.error = error
        self.scoreboard = scoreboard or []
        self.scoreboard_error = scoreboard_error
        self.weekly_scoreboards: dict[int, list[ScoreboardGame]] = {}
        self.days_asked: list[date] = []
        """Scoreboards for particular weeks, where a test needs them to differ; `scoreboard` otherwise."""
        self.asked: list[str] = []
        self.rosters: list[Athlete] = []
        self.histories: dict[str, InjuryReport] = {}
        """Each athlete's own latest entry, keyed by his ESPN id: what the core API answers per player."""
        self.backfill_error: Exception | None = None
        self.roster_reads = 0
        self.asked_after: list[str] = []
        self.athlete_news: dict[str, list[NewsArticle]] = {}
        """Each athlete's own stories, keyed by his ESPN id: his ESPN page's news."""
        self.stories: dict[str, str] = {}
        """Each story's text, keyed by its id: what the content API serves."""
        self.athletes_asked: list[str] = []
        """The ESPN ids whose own entries were asked for."""

    def get_athlete_news(self, league: str, athlete_ids: Sequence[str]) -> dict[str, list[NewsArticle]]:
        self.athletes_asked = list(athlete_ids)
        if self.error:
            raise self.error
        return {a: self.athlete_news[a] for a in athlete_ids if a in self.athlete_news}

    def get_stories(self, articles: Sequence[NewsArticle]) -> list[NewsArticle]:
        return [replace(a, body=self.stories[a.article_id]) if a.article_id in self.stories else a for a in articles]

    def get_team_news(self, league: str, clubs: list[str]) -> dict[str, list[NewsArticle]]:
        self.asked = clubs
        if self.error:
            raise self.error
        return {club: self.news[club] for club in clubs if club in self.news}

    def get_injuries(self, league: str) -> list[InjuryReport]:
        if self.injuries_error:
            raise self.injuries_error
        return self.injuries

    def get_scoreboard(self, league: str, season: str, week: int) -> list[ScoreboardGame]:
        if self.scoreboard_error:
            raise self.scoreboard_error
        return self.weekly_scoreboards.get(week, self.scoreboard)

    def get_day_scoreboard(self, league: str, day: date) -> list[ScoreboardGame]:
        self.days_asked.append(day)
        if self.scoreboard_error:
            raise self.scoreboard_error
        return self.scoreboard

    def get_rosters(self, league: str) -> list[Athlete]:
        self.roster_reads += 1
        if self.backfill_error:
            raise self.backfill_error
        return self.rosters

    def get_athlete_injuries(self, league: str, season: str, athletes: Sequence[Athlete]) -> dict[str, InjuryReport]:
        self.asked_after = [a.athlete_id for a in athletes]
        if self.backfill_error:
            raise self.backfill_error
        return {a.athlete_id: self.histories[a.athlete_id] for a in athletes if a.athlete_id in self.histories}
