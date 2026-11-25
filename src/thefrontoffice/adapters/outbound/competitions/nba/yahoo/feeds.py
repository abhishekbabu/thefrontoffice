"""What the provider reads beside Yahoo, through the collaborators it was handed: Sleeper's form, schedule,
seasons and box scores, and ESPN's injury report and scoreboard.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from thefrontoffice.adapters.outbound.competitions.careers import recent_seasons
from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.nba import news as nba_news
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores, FormSource
from thefrontoffice.adapters.outbound.competitions.nba.model import Player
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    PACIFIC,
    Line,
    playable_from,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import (
    Condition,
    Leaning,
    Regular,
    Teammate,
    Teammates,
    conditions,
    reported,
)
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.competitions.nba.worth import Valuer
from thefrontoffice.adapters.outbound.competitions.news import PlayerNews
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA, InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, ScheduledGame
from thefrontoffice.domain.errors import (
    FrontOfficeError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Feeds:
    """What the provider reads beside Yahoo: Sleeper's form, schedule and seasons, and ESPN's report and scoreboard.

    Held by the provider, built from the collaborators bootstrap hands it, so
    each read here names only what it needs.
    """

    form: FormSource
    games: ScheduleSource
    sleeper: SleeperProjectionSource
    espn: ESPNSource

    def playable(self, player: Player, clubs: Mapping[str, int], back: date | None, end: date) -> int | None:
        """The games he can play before `end`: his club's left; none while ruled out, or those from his return;
        on waivers, those from the day he clears them (`rules.playable_from`).

        None where the schedule would not load. Counted from a later day only once
        the bulk read has loaded the schedule, so this read cannot fail on its own.
        """
        left = clubs.get(player.team.upper())
        out = ruled_out(player.status)
        if left is None or (out and back is None):
            return None if left is None else 0
        later = [day for day in (back if out else None, playable_from(player)) if day is not None]
        return self.games.get_remaining_games(player.team, max(later), end) if later else left

    def today(self, start: date, end: date) -> nba_week.Today | None:
        """Today's games, while today falls inside the week from `start` to `end`.

        None outside it, and where the schedule would not load rather than a day of no games.
        """
        on = self.games.games_today()
        if on is None or not start <= on[0] <= end:
            return None
        return nba_week.Today(on[0], on[1], self.tipoff(on[0]))

    def day(self) -> date:
        """Today on the league's clock: the schedule's own, or Pacific's where it would not load."""
        on = self.games.games_today()
        return on[0] if on is not None else datetime.now(PACIFIC).date()

    def projected_on(self, players: Sequence[Player], day: date) -> dict[str, Line]:
        """What Sleeper projects of each of `players`' game on `day`, by Yahoo's key; nobody it projects nothing
        for, or whom the name does not match on his club (`ProjectionIndex.find`). None at all where Sleeper
        publishes no projection for the day."""
        projections = index_for(self.sleeper, day, day)
        if projections is None:
            return {}
        found = {p.player_key: projections.find(p.name, p.team, self.form.get_player_stats(p.name)) for p in players}
        return {key: projected.line for key, projected in found.items() if projected is not None}

    def minutes_on(self, players: Sequence[Player], day: date) -> dict[str, float]:
        """The minutes each of `players` played on `day`, by Yahoo's key (`minutes_by_day`); nobody where Sleeper's
        box scores do not hold the day."""
        return self.minutes_by_day(players).get(day, {})

    def minutes_by_day(self, players: Sequence[Player]) -> dict[date, dict[str, float]]:
        """The minutes each of `players` played on every day Sleeper's box scores hold, by day, then Yahoo's key:
        what tells a game he sat out from one he played and filled no column in.

        A day is held once any game of it is in the box scores, which are read by
        whole Sleeper weeks; on such a day, a player with no line played nought.
        Only a player whose name places him in Sleeper's catalog is answered for,
        and nobody at all where the box scores would not load.
        """
        try:
            scores = self.form.box_scores()
        except FrontOfficeError as e:
            logger.warning(f"Reading days without who played, Sleeper's box scores would not load: {e}")
            return {}
        held = {day for logs in scores.logs.values() for log in logs if (day := parse_day(log.date)) is not None}
        found: dict[date, dict[str, float]] = {day: {} for day in held}
        for player in players:
            sleeper_id = scores.index.lookup(player.name)
            if sleeper_id is None:
                continue
            for day in held:
                found[day][player.player_key] = 0.0
            for log in scores.logs.get(sleeper_id, ()):
                if (day := parse_day(log.date)) in found:
                    found[day][player.player_key] += log.minutes
        return found

    def tipoff(self, day: date) -> dict[str, datetime]:
        """When each club's game on `day` starts, while it has not, by ESPN's abbreviation.

        Empty where ESPN's scoreboard would not load: a row then says he plays
        today without the hour, which is still what the lineup is set on.
        """
        try:
            games = self.espn.get_day_scoreboard(NBA, day)
        except ESPNAPIError as e:
            logger.warning(f"Showing today's games without tip-off times, ESPN's scoreboard would not load: {e}")
            return {}
        return {
            club: game.kickoff
            for game in games
            if game.state == "pre" and game.kickoff is not None
            for club in (game.home, game.away)
        }

    def scores(self) -> BoxScores:
        """Every game in the form window, by player; none where they would not load: who has missed games in a row
        (`reads.doubts`) is enrichment, and nobody's return is then doubted."""
        try:
            return self.form.box_scores()
        except FrontOfficeError as e:
            logger.warning(f"Reading returns without who has missed games, Sleeper's box scores would not load: {e}")
            return BoxScores()

    def recent(self, player: Player) -> list[NBAGameLog]:
        return self.form.recent_games(player.name)

    def seasons(self, player: Player) -> dict[str, NBASeason | None]:
        """His totals this season and the two before it, newest first; a season that will not load reads as absent."""
        current = self.sleeper.get_nba_state().season
        found: dict[str, NBASeason | None] = {}
        for season in [current, *recent_seasons(current)]:
            try:
                found[season] = self.form.season(player.name, season)
            except FrontOfficeError as e:
                logger.warning(f"Leaving {season} out of {player.name}'s seasons: {e}")
                found[season] = None
        return found

    def venues(self, player: Player, games: Sequence[NBAGameLog]) -> dict[str, ScheduledGame]:
        """His club's game on each date of his log, by ISO date, from the schedule already loaded; none where it
        will not load, which leaves each game's opponent bare."""
        days = [day for g in games if (day := parse_day(g.date))]
        if not days:
            return {}
        try:
            slate = self.games.games_between(min(days), max(days))
        except FrontOfficeError as e:
            logger.warning(f"Showing {player.name}'s game log without home and away: {e}")
            return {}
        played = {g.date: g.team or player.team.upper() for g in games}
        return {g.date: g for g in slate if played.get(g.date) in (g.home, g.away)}

    def reports(self) -> list[InjuryReport]:
        """ESPN's NBA injury report; empty where it will not load, which leaves Yahoo's statuses standing alone."""
        try:
            return self.espn.get_injuries(NBA)
        except ESPNAPIError as e:
            logger.warning(f"Continuing on Yahoo's injury statuses alone: {e}")
            return []

    def splits(
        self, players: Sequence[Player], weights: Mapping[str, float] | None, reports: Sequence[InjuryReport]
    ) -> Callable[[Player], list[Teammate]]:
        """Each player's teammates worth weighing (`teammates.py`): any at his position due back soon whom he has
        barely played beside (`Returning`), then his line without each regular who is hurt or lately sat out.

        A teammate's condition is Yahoo's status where his row is among `players`, else ESPN's report; the box
        scores, and last season's minutes for a teammate with few games this one, are read once for them all.
        """
        mates, known = self.teammates(players, weights, reports)
        today = datetime.now(PACIFIC).date()
        return lambda player: [*mates.returning(player, known, today), *mates.splits(player, known)]

    def teammates(
        self, players: Sequence[Player], weights: Mapping[str, float] | None, reports: Sequence[InjuryReport]
    ) -> tuple[Teammates, Mapping[str, Condition]]:
        """Every club's regulars from the box scores, and each one's condition: Yahoo's status where his row is
        among `players`, else ESPN's report."""
        mates = Teammates(self.form.box_scores(), weights, self.last_season())
        regulars = mates.regulars()
        return mates, conditions(regulars, players, reported(regulars, reports))

    def leaning(
        self, wire: Sequence[Player], players: Sequence[Player], weights: Mapping[str, float] | None, value: Valuer
    ) -> dict[str, Leaning]:
        """Each of `wire` whose role leans on a teammate due back, by Yahoo key: one at his position he has barely
        played beside (`Teammates.returning`), else one his split says he does clearly more without
        (`Teammates.propped`) — the soonest back. None where the box scores will not load: a teammate is
        enrichment."""
        try:
            mates, known = self.teammates(players, weights, self.reports())
        except FrontOfficeError as e:
            logger.warning(f"Weighing pickups without teammates due back: {e}")
            return {}
        today = datetime.now(PACIFIC).date()
        found: dict[str, Leaning] = {}
        for p in wire:
            leans: list[Leaning] = [*mates.returning(p, known, today), *mates.propped(p, known, today, value)]
            if leans:
                found[p.player_key] = leans[0]
        return found

    def last_season(self) -> Mapping[str, NBASeason]:
        """Every player's totals last season, by Sleeper's id; none where it will not load, which leaves a
        teammate hurt early this season out of the regulars."""
        try:
            previous = recent_seasons(self.sleeper.get_nba_state().season)
            return self.form.season_totals(previous[0]) if previous else {}
        except FrontOfficeError as e:
            logger.warning(f"Weighing teammates without last season's minutes: {e}")
            return {}

    def team_news(self, players: Sequence[Player]) -> PlayerNews:
        """Each of `players`' news and his club's stories (`nba/news.py`), from the feeds of their clubs.

        Empty where ESPN's feeds will not load: news is enrichment, and the prompt stands without it.
        """
        clubs = sorted({espn_club(p.team) for p in players if p.team})
        try:
            feeds = self.espn.get_team_news(NBA, clubs)
        except ESPNAPIError as e:
            logger.warning(f"Continuing without club news: {e}")
            return PlayerNews()
        return nba_news.attach(feeds, players, self.regulars(), datetime.now(UTC))

    def regulars(self) -> list[Regular]:
        """Every club's regulars from the box scores; none where they will not load, which leaves a club's
        stories to the ones that name nobody — a coach."""
        try:
            return Teammates(self.form.box_scores(), None, self.last_season()).regulars()
        except FrontOfficeError as e:
            logger.warning(f"Reading club news without each club's regulars: {e}")
            return []
