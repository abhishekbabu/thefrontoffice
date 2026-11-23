"""NBA on Yahoo.

Head-to-head basketball, won on categories or on fantasy points as the league's
settings say: the forward-looking number is games remaining in the matchup
period crossed with recent form — per category, or summed under the league's
weights — and the budget constraint is the league's weekly add limit.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from itertools import zip_longest

from thefrontoffice.adapters.outbound.competitions import news, paging, places
from thefrontoffice.adapters.outbound.competitions.careers import recent_seasons
from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.injuries import PlayerInjuries, by_club, matched
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba import actions, defense, history, prompt, views
from thefrontoffice.adapters.outbound.competitions.nba import forecast as nba_forecast
from thefrontoffice.adapters.outbound.competitions.nba import league as nba_league
from thefrontoffice.adapters.outbound.competitions.nba import market as nba_market
from thefrontoffice.adapters.outbound.competitions.nba import outlook as nba_outlook
from thefrontoffice.adapters.outbound.competitions.nba import strength as nba_strength
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba import worth as nba_worth
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.context import (
    PlayerContextBuilder,
    rank_by_points,
    rank_free_agents,
)
from thefrontoffice.adapters.outbound.competitions.nba.form import FormSource
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    PACIFIC,
    SCOUTED,
    Line,
    amount,
    playable_from,
    position_filters,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Split, Teammates, conditions, reported
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.seeds import seed
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA, InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, PlayerMeta, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooLeagueSource
from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooGame
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource, once
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import RECENT_AVERAGE
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    LeagueSettings,
    Pairing,
    Timeframe,
    YahooLeague,
    YahooLine,
    YahooPlayer,
    YahooTeam,
)
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    LeagueNotFoundError,
    NotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
    UnsupportedError,
)
from thefrontoffice.domain.models import (
    Action,
    CompetitionContext,
    LeagueSchedule,
    MatchupInput,
    Outlook,
    PlayedMatchup,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    PlayerRef,
    Slate,
    Summary,
    TeamRecord,
    TeamRef,
    TradeMarket,
    TradeProposal,
    WeekRange,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

WIRE_DEPTH = {Timeframe.SEASON: 300, Timeframe.LAST_WEEK: 100}
"""How deep the wire is read under each of Yahoo's rankings: sixteen pages of 25, fetched together.

Season rank alone buries a player who has just stepped into a role — he ranks
low on a season mostly spent on the bench — so the last week's ranking is read
beside it. Three hundred deep by season is past every regular rotation player."""

STREAM_DEPTH = {Timeframe.SEASON: 50, Timeframe.LAST_WEEK: 25}
"""How deep the week's to-do list reads the wire for streams: three pages, the top of each ranking.

A stream worth an add sits near the top of one ranking or the other, and the
summary is the page opened most, so it leaves the deep list to the Free agents
page. Its first pages are the same reads, so whichever page asks first serves both."""


@dataclass(frozen=True)
class Decided:
    """The week weighed: every shown player's reading by Yahoo's key, and the to-do list read off them."""

    readings: dict[str, Reading]
    actions: list[Action]


LEADERS = {c.label: c.yahoo_stat for c in SCOUTED}
"""The stats the free-agent scout ranks the wire by, a request each."""

LEADERS_PER_STAT = 10

ONE_WIN = "headone"
"""Yahoo's scoring type for a category league whose week counts as one win, to whoever takes more categories."""


class YahooNBAProvider:
    """CompetitionProvider for Yahoo head-to-head basketball, by categories or by points."""

    @staticmethod
    def season_year(now: datetime | None = None) -> int:
        """The NBA season a date belongs to (`league.season_year`)."""
        return nba_league.season_year(now)

    def __init__(
        self,
        *,
        auth: YahooLeagueSource,
        yahoo_for: Callable[[YahooLeague], YahooSource],
        form: FormSource,
        games: ScheduleSource,
        sleeper: SleeperProjectionSource,
        espn: ESPNSource,
        fallback_weekly_adds: int,
    ):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        `yahoo_for` rather than one client because a Yahoo client is bound to a
        league, and every call names the league it reads. `fallback_weekly_adds`
        is the add limit for a league whose settings name none. `form` and
        `games` are both read from Sleeper: each player's recent run, and the
        real games inside a matchup week.
        """
        self._auth = auth
        self._yahoo_for = yahoo_for
        self.form = form
        self.games = games
        self.sleeper = sleeper
        self.espn = espn
        self.fallback_weekly_adds = fallback_weekly_adds
        self._found: list[YahooLeague] | None = None

    def _leagues(self) -> list[YahooLeague]:
        """This season's leagues, found once per provider: the first is read when a call names none.

        Raises:
            LeagueNotFoundError: the login plays in no NBA league this season.
        """
        if self._found is None:
            self._found = self._auth.find_leagues(YAHOO_GAME.code, self.season_year())
        if not self._found:
            raise LeagueNotFoundError("no Yahoo NBA leagues for this season")
        return self._found

    def list_leagues(self) -> list[LeagueRef]:
        """Every Yahoo NBA league this login is in."""
        return [
            LeagueRef(
                league_id=lg.league_key,
                name=lg.name,
                detail=lg.league_type,
                url=nba_league.league_url(lg.league_key),
            )
            for lg in self._leagues()
        ]

    def _league(self, league_id: str) -> YahooLeague:
        """The league `league_id` names, or the first when it names none."""
        leagues = self._leagues()
        if not league_id:
            return leagues[0]
        for lg in leagues:
            if lg.league_key == league_id:
                return lg
        raise LeagueNotFoundError(f"Yahoo league {league_id} is not one of yours")

    def _yahoo(self, league_id: str) -> YahooSource:
        """A reader for `league_id`, or for the first league when it names none.

        Resolved on every call rather than remembered: a provider that moved
        itself between leagues answered each request from whichever league the
        previous one had asked for.
        """
        return self._yahoo_for(self._league(league_id))

    def _add_limit(self, yahoo: YahooSource) -> int:
        """The league's weekly add limit, as its settings name it, or the configured one where they name none."""
        limit = yahoo.settings().max_weekly_adds
        return self.fallback_weekly_adds if limit is None else limit

    @staticmethod
    def _weights(league: YahooLeague, yahoo: YahooSource) -> dict[str, float] | None:
        """A points league's weights by Yahoo stat id; None for a league won on categories.

        A points league whose settings carry no weights is read as a category
        one: there is nothing to sum its players' lines with.
        """
        return (yahoo.settings().weights or None) if league.by_points else None

    def summary(self, league_id: str) -> Summary:
        """The week being played: the add budget, the score, both rosters with each player's week, and the to-do list.

        The list is the IL moves, then starts and pickups weighed on each player's
        worth this week (`actions.build`); with nothing on it, there is no list,
        rather than an empty one claiming there is nothing to do.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        my_team = yahoo.get_user_team()
        roster = yahoo.roster(my_team.team_key)
        limit = self._add_limit(yahoo)
        adds = nba_week.adds(my_team.adds_used, limit)
        week = league.current_week
        decided: list[Decided] = []

        def read(found: Pairing, theirs: list[YahooPlayer]) -> Mapping[str, Reading]:
            adds_left = max(0, limit - my_team.adds_used)
            shown = self._averages(yahoo, found.mine.team_key, found.opponent.team_key)
            decided.append(self._decide(yahoo, league, roster, theirs, found.start, found.end, adds_left, shown=shown))
            return decided[0].readings

        board = self._board(yahoo, league, my_team, week, roster, read) if week else Summary()
        # Without a matchup this week there is no week to weigh anybody on: only the IL moves stand.
        items = decided[0].actions if decided else nba_week.off_il(roster)
        return board.model_copy(update={"headline": [*adds, *board.headline], "actions": items or None})

    def _decide(
        self,
        yahoo: YahooSource,
        league: YahooLeague,
        roster: list[YahooPlayer],
        theirs: list[YahooPlayer],
        start: date,
        end: date,
        adds_left: int,
        also: list[YahooPlayer] | None = None,
        shown: Mapping[str, YahooLine] | None = None,
    ) -> Decided:
        """Every shown player's week, and the to-do list weighed on it.

        Read over your roster, your opponent's and the wire, which is also the
        pool a category league's values are scaled across — the same pool for
        the page and the prompt, so both read one list. `also` are read on
        that same scale without joining the pool: the prompt's free agents.
        `shown` is Yahoo's averages for the rostered players, which every row and
        item shows of them; the wire carries its own.

        The wire is enrichment here: one that will not load (a sync that has not
        carried it) leaves the week's rows and starts standing, with nothing to stream.
        """
        try:
            free_agents = _wire(yahoo, STREAM_DEPTH)
        except FrontOfficeError as e:
            logger.warning(f"Weighing the week without the wire, which would not load: {e}")
            free_agents = []
        weights = self._weights(league, yahoo)
        averages = {**(shown or {}), **_carried(free_agents)}
        readings = self._readings(yahoo, weights, [*roster, *theirs, *free_agents], start, end, also or [], averages)
        today = self._today(start, end)
        return Decided(readings, actions.build(roster, free_agents, readings, adds_left, weights is not None, today))

    def _readings(
        self,
        yahoo: YahooSource,
        weights: Mapping[str, float] | None,
        players: list[YahooPlayer],
        start: date,
        end: date,
        also: list[YahooPlayer] | None = None,
        averages: Mapping[str, YahooLine] | None = None,
    ) -> dict[str, Reading]:
        """Each of `players`' week between `start` and `end`, by Yahoo's key (`worth.read`), and `also`'s.

        Each carries Yahoo's average over his last month from `averages`, which
        is shown beside the week and never weighed in it.

        His games are his club's left, none while he is ruled out, or those from
        the day ESPN expects him back. A category league values a game across
        the categories it scores, scaled over `players` alone.
        """
        pool = {p.player_key for p in players}
        unique = list({p.player_key: p for p in [*players, *(also or [])]}.values())
        projections = index_for(self.sleeper, start, end)
        clubs = self.games.get_remaining_games_bulk([p.team for p in unique], start, end)
        returns = self._returns(unique, self._reports())
        provisional = bool(self.games.unscheduled(start, end))
        stats = {p.player_key: self.form.get_player_stats(p.name) for p in unique}
        projected = {
            p.player_key: projections.find(p.name, p.team, stats[p.player_key]) if projections else None for p in unique
        }
        per_game = (
            nba_worth.per_game(stats[p.player_key], projected[p.player_key]) for p in unique if p.player_key in pool
        )
        value, found = _valuer(yahoo, weights, [line for line in per_game if line])
        readings = (
            nba_worth.read(
                p,
                stats[p.player_key],
                projected[p.player_key],
                value,
                self._games(p, clubs, returns.get(p.player_key), end),
                provisional,
                returns.get(p.player_key),
            )
            for p in unique
        )
        shown = averages or {}
        return {
            r.player.player_key: replace(
                r, weak=tuple(nba_worth.weakest(r.line, found)), average=shown.get(r.player.player_key)
            )
            for r in readings
        }

    def _games(self, player: YahooPlayer, clubs: Mapping[str, int], back: date | None, end: date) -> int | None:
        """The games he can play before `end`: his club's left; none while ruled out, or those from his return;
        on waivers, those after he clears them (`rules.playable_from`).

        None where the schedule would not load. Counted from a later day only once
        the bulk read has loaded the schedule, so this read cannot fail on its own.
        """
        left = clubs.get(player.team.upper())
        out = ruled_out(player.status)
        if left is None or (out and back is None):
            return None if left is None else 0
        later = [day for day in (back if out else None, playable_from(player)) if day is not None]
        return self.games.get_remaining_games(player.team, max(later), end) if later else left

    def week_of(self, league_id: str, week: int) -> Summary:
        """Any week of the season: its score as it finished or stands, and no to-do list.

        A week to come shows both rosters as they stand today, against that
        week's opponent; a week played shows both as they ended it, each player
        with his line over it.

        Raises:
            NotFoundError: the season has no such week.
        """
        league = self._league(league_id)
        current = self._within(league, week)
        yahoo = self._yahoo_for(league)
        my_team = yahoo.get_user_team()
        if week < current:
            return self._board(yahoo, league, my_team, week, None, played=True)
        roster = yahoo.roster(my_team.team_key)
        weights = self._weights(league, yahoo)

        def read(found: Pairing, theirs: list[YahooPlayer]) -> Mapping[str, Reading]:
            shown = self._averages(yahoo, found.mine.team_key, found.opponent.team_key)
            return self._readings(yahoo, weights, [*roster, *theirs], found.start, found.end, averages=shown)

        return self._board(yahoo, league, my_team, week, roster, read)

    def games_of(self, league_id: str, week: int) -> Slate:
        """The real games inside a matchup week, from Sleeper's schedule, marked where you have players.

        Yahoo publishes no NBA schedule through this SDK, but it does date each
        matchup week, and Sleeper's schedule fills those dates. A week your
        team has no matchup in carries no dates on Yahoo's scoreboard, so it
        lists no games. Every club plays inside a matchup week, so none has a bye.

        Raises:
            NotFoundError: the season has no such week.
            PlatformError: the schedule would not load.
        """
        league = self._league(league_id)
        self._within(league, week)
        yahoo = self._yahoo_for(league)
        team = yahoo.get_user_team()
        found = yahoo.pairing(team.team_key, week)
        if found is None:
            return Slate()
        roster = yahoo.roster(team.team_key)
        return Slate(
            games=[nba_week.match(game, roster) for game in self.games.games_between(found.start, found.end)],
            note=nba_week.not_final(self.games.unscheduled(found.start, found.end)),
        )

    def _within(self, league: YahooLeague, week: int) -> int:
        """The week being played, once `week` is known to be one of the season's.

        Raises:
            NotFoundError: between seasons, or a week outside this one.
        """
        current = league.current_week
        if not current or not league.first_week <= week <= league.last_week(current):
            raise NotFoundError(f"week {week} of the {league.name} season")
        return current

    def _board(
        self,
        yahoo: YahooSource,
        league: YahooLeague,
        team: YahooTeam,
        week: int,
        roster: list[YahooPlayer] | None,
        read: Callable[[Pairing, list[YahooPlayer]], Mapping[str, Reading]] | None = None,
        *,
        played: bool = False,
    ) -> Summary:
        """One week's head-to-head, and where it sits in the season.

        `roster` is yours where rosters are shown, and None where they are not;
        the opponent's is read alongside it. `read` gives each shown player's
        week, from the pairing and the opponent's roster. A week `played` reads
        both rosters as Yahoo kept them for it instead: a basketball lineup is
        set day by day, so today's did not play it.
        """
        current = league.current_week or week
        weeks = WeekRange(week=week, current=current, first=league.first_week, last=league.last_week(current))
        found = yahoo.pairing(team.team_key, week)
        if found is None:
            return Summary(window=f"Week {week}", weeks=weeks)
        records = self._records(yahoo)
        if played:
            kept = yahoo.played_rosters([team.team_key, found.opponent.team_key], week)
            roster, theirs = kept[team.team_key], kept[found.opponent.team_key]
        else:
            theirs = yahoo.roster(found.opponent.team_key) if roster is not None else None
        readings = read(found, theirs) if read is not None and theirs is not None else None
        scored = None if league.by_points else yahoo.settings().categories
        unscheduled = [] if played else self.games.unscheduled(found.start, found.end)
        # Only while the week shown is the one being played: a week ahead has no today, and one played
        # was set day by day already. None where the schedule would not load, rather than a day of no games.
        today = None if played or week != current else self._today(found.start, found.end)
        if today is not None and roster is not None:
            today = replace(
                today, played=self._played_today(yahoo, [team.team_key, found.opponent.team_key], today.day)
            )
        return nba_week.board(found, weeks, records, roster, theirs, scored, readings, unscheduled, today)

    def _today(self, start: date, end: date) -> nba_week.Today | None:
        """Today's games, while today falls inside the week from `start` to `end`.

        None outside it, and where the schedule would not load rather than a day of no games.
        """
        on = self.games.games_today()
        if on is None or not start <= on[0] <= end:
            return None
        return nba_week.Today(on[0], on[1], self._tipoff(on[0]))

    @staticmethod
    def _records(yahoo: YahooSource) -> dict[str, str]:
        """Each team's record now, by key, from the table: Yahoo's teams list carries none.

        Empty where the table will not load — a browser sync that has not
        carried it — which leaves a matchup without records rather than fail it.
        """
        try:
            standings = yahoo.standings()
        except FrontOfficeError as e:
            logger.warning(f"Showing teams without their records, the table would not load: {e}")
            return {}
        return {t.team_key: t.standing.record for t in standings if t.standing}

    @staticmethod
    def _played_today(yahoo: YahooSource, team_keys: list[str], day: date) -> dict[str, YahooPlayer]:
        """Each of these teams' players' line from `day`'s games, by Yahoo's key.

        Empty where Yahoo would not give it: the rows then say the game is on
        or over without what he did in it, rather than fail the page.
        """
        try:
            rosters = yahoo.day_rosters(team_keys, day)
        except FrontOfficeError as e:
            logger.warning(f"Showing today's games without the players' lines, Yahoo would not give them: {e}")
            return {}
        return {p.player_key: p for players in rosters.values() for p in players}

    def _tipoff(self, day: date) -> dict[str, datetime]:
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

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The table, and your head-to-head season from every week's scoreboard.

        Between seasons there are no weeks to read, so only the table. Yahoo
        publishes no real-world NBA schedule through this SDK and no league-wide
        transaction feed, so those sections stay empty and render as nothing.

        Raises:
            YahooCaptureMissingError: read from a browser sync that has not carried the table.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        mine = yahoo.get_user_team().team_key
        standings = nba_league.table(yahoo.standings(), mine)
        row = next((row for row in standings if row.is_mine), None)
        headline = places.season(row.record, row.rank, len(standings)) if row else []
        season = []
        current = league.current_week
        if current:
            weeks = list(range(league.first_week, league.last_week(current) + 1))
            records = {row.team_id: row.record for row in standings}
            season = nba_league.season(
                yahoo.season(mine, weeks), yahoo.settings(), current, records, points=league.by_points
            )
        return LeagueSchedule(headline=headline, season=season, standings=standings)

    def build_context(self, league_id: str = "") -> CompetitionContext:
        """Gather league state and render the scouting prompt.

        Returns the prompt plus the pieces that make it up, so a follow-up
        briefing can be assembled without re-deriving or re-sending everything.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        weights = self._weights(league, yahoo)
        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team.team_key)
        start, end = (week.start, week.end) if week else (None, None)
        used_adds, limit = my_team.adds_used, self._add_limit(yahoo)

        # Gathered before the schedule so one bulk lookup covers every team
        # either of them touches.
        rostered = yahoo.roster(my_team.team_key)
        free_agents, annotations = (
            rank_by_points(_wire(yahoo), self.form.get_player_stats, weights)
            if weights
            else rank_free_agents(yahoo.fetch_top_by_stat(LEADERS, per_stat=LEADERS_PER_STAT))
        )
        logger.debug(f"Building context for {len(rostered)} rostered and {len(free_agents)} free agents")

        remaining_games: dict[str, int] = {}
        if start and end:
            teams = [p.team for p in (*rostered, *free_agents)]
            remaining_games = self.games.get_remaining_games_bulk(teams, start, end)

        projections = index_for(self.sleeper, start, end)
        reports = self._reports()
        returns = self._returns([*rostered, *free_agents], reports)
        splits = self._splits([*rostered, *free_agents], weights, reports)
        decided = (
            self._decide(
                yahoo,
                league,
                rostered,
                week.opponent_roster,
                week.start,
                week.end,
                max(0, limit - used_adds),
                free_agents,
                self._averages(yahoo, my_team.team_key, week.opponent.team_key),
            )
            if week
            else Decided({}, nba_week.off_il(rostered))
        )
        tasks = decided.actions
        # A pickup the list names is a free agent the model judges, so it reads his line too.
        named = {pid for task in tasks for pid in (task.player_id, task.replaces, task.drop) if pid}
        held = {p.player_key for p in rostered}
        free_agents += [
            r.player
            for key, r in decided.readings.items()
            if key in named and key not in held and all(p.player_key != key for p in free_agents)
        ]
        builder = PlayerContextBuilder(self.form, self.games, weights)
        roster_lines = builder.build_player_lines(
            rostered,
            start,
            end,
            remaining_games=remaining_games,
            projections=projections,
            returns=returns,
            splits=splits,
            readings=decided.readings,
        )
        fa_lines = builder.build_player_lines(
            free_agents,
            start,
            end,
            annotations,
            remaining_games,
            projections=projections,
            returns=returns,
            splits=splits,
            readings=decided.readings,
        )

        unscheduled = self.games.unscheduled(start, end) if start and end else []
        schedule_context = prompt.schedule(
            week, remaining_games, projected=projections is not None, unscheduled=unscheduled
        )
        trans_context = prompt.transactions(used_adds, limit)
        by_key = {p.player_key: p for p in (*rostered, *free_agents)}
        return CompetitionContext(
            prompt=prompt.scout(
                roster="".join(roster_lines.values()),
                week=week,
                free_agents="".join(fa_lines.values()),
                schedule_context=schedule_context,
                trans_context=trans_context,
                adds_left=max(0, limit - used_adds),
                weights=weights,
                tasks=tasks,
            ),
            situation=prompt.matchup(week, weights),
            constraints=trans_context,
            extra=schedule_context,
            roster_lines=roster_lines,
            candidate_lines=fa_lines,
            headline=nba_week.adds(used_adds, limit),
            tasks=tasks,
            # What a game of each is worth, so a model's add never costs a better player than it brings.
            worth={
                r.player.name: game
                for key, r in decided.readings.items()
                if key in by_key and (game := nba_worth.game_value(r)) is not None
            },
            listed=frozenset(by_key[pid].name for pid in named if pid in by_key),
            # A kept judgment's add of somebody another manager has since claimed is no move at all.
            movable=frozenset(p.name for p in (*rostered, *free_agents)),
        )

    # ── the wire ────────────────────────────────────────────────────

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        """The prompt asking for one call per listed free agent.

        Each candidate's line is the scout's — form, status and return, games
        left, projection, teammates out, worth this week — plus the weakest
        player he streams over by the to-do list's margin (`actions.fit`), and
        the id the call has to name. Every figure is read over the same players
        whichever are asked about: the roster, the opponent and the top of the
        wire, as the to-do list reads them, so a call kept against a line is
        checked against that same line on any page.

        Raises:
            PlayerNotFoundError: an id is rostered in this league, or not on the wire.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        weights = self._weights(league, yahoo)
        team = yahoo.get_user_team()
        rostered = yahoo.roster(team.team_key)
        held = {p.player_key for p in rostered}
        everyone = _wire(yahoo)
        available = {p.player_key: p for p in everyone if p.player_key not in held}
        unavailable = [pid for pid in player_ids if pid not in available]
        if unavailable:
            raise PlayerNotFoundError(unavailable)
        candidates = [available[pid] for pid in player_ids]
        week = yahoo.get_matchup(team.team_key)
        limit = self._add_limit(yahoo)
        reports = self._reports()
        known = [*rostered, *everyone]
        returns = self._returns(known, reports)
        splits = self._splits(known, weights, reports)
        readings: dict[str, Reading] = {}
        remaining: dict[str, int] = {}
        start, end = (week.start, week.end) if week else (None, None)
        if week:
            pool = [*rostered, *week.opponent_roster, *_wire(yahoo, STREAM_DEPTH)]
            readings = self._readings(yahoo, weights, pool, week.start, week.end, candidates, _carried(everyone))
            remaining = self.games.get_remaining_games_bulk(
                [p.team for p in (*rostered, *candidates)], week.start, week.end
            )
        builder = PlayerContextBuilder(self.form, self.games, weights)
        projections = index_for(self.sleeper, start, end)

        def lines(players: list[YahooPlayer]) -> dict[str, str]:
            return builder.build_player_lines(
                players,
                start,
                end,
                remaining_games=remaining,
                projections=projections,
                returns=returns,
                splits=splits,
                readings=readings,
            )

        candidate_lines = lines(candidates)
        fits = {
            p.player_key: actions.fit(r, rostered, readings, weights is not None)
            for p in candidates
            if (r := readings.get(p.player_key))
        }
        return prompt.wire(
            week=week,
            weights=weights,
            roster=lines(rostered),
            candidates={p.player_key: candidate_lines[p.name] for p in candidates},
            names={p.player_key: p.name for p in candidates},
            fits=fits,
            constraints=prompt.transactions(team.adds_used, limit),
        )

    # ── the weeks ahead ─────────────────────────────────────────────

    def weeks_ahead(self, league_id: str, team_id: str = "") -> Outlook:
        """The next few matchup weeks of a roster, yours where `team_id` is empty, counted in games (`outlook.build`).

        The weeks' dates are Yahoo's scoreboards, which the season page reads
        too and which hold for a week; their games are Sleeper's schedule.

        Raises:
            TeamNotFoundError: no team in the league has that id.
            PlatformError: the schedule would not load.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        if team_id and not any(t.team_key == team_id for t in yahoo.teams()):
            raise TeamNotFoundError(team_id)
        team_key = team_id or yahoo.get_user_team().team_key
        current = league.current_week
        if not current:
            return Outlook(measure="games")
        last = min(current + nba_outlook.WEEKS_AHEAD, league.last_week(current))
        pairings = yahoo.season(team_key, list(range(current + 1, last + 1)))
        windows = [
            nba_outlook.Window(
                week,
                found.start,
                found.end,
                self.games.games_between(found.start, found.end),
                self.games.unscheduled(found.start, found.end),
            )
            for week, found in sorted(pairings.items())
            if found is not None
        ]
        if not windows:
            return Outlook(measure="games")
        roster = yahoo.roster(team_key)
        try:
            wire = _wire(yahoo, STREAM_DEPTH)
        except FrontOfficeError as e:
            logger.warning(f"Planning the weeks ahead without the wire, which would not load: {e}")
            wire = []
        weights = self._weights(league, yahoo)
        readings = self._readings(yahoo, weights, [*roster, *wire], windows[0].start, windows[-1].end)
        returns = self._returns([*roster, *wire], self._reports())
        return nba_outlook.build(windows, roster, wire, readings, returns, self._add_limit(yahoo))

    # ── the week, simulated ─────────────────────────────────────────

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        """This week's matchup, ready to simulate (`forecast`): what each side has, and every game still to come.

        None between seasons and in a week without an opponent — and for
        `candidates`, since the wire is not priced in basketball: a pickup's
        worth here turns on the add budget as much as on this week.

        Raises:
            UnsupportedError: the league scores something a box score here cannot build.
            PlatformError: the schedule would not load.
        """
        league = self._league(league_id)
        week = league.current_week
        if candidates or not week:
            return None
        yahoo = self._yahoo_for(league)
        team = yahoo.get_user_team()
        found = yahoo.pairing(team.team_key, week)
        if found is None:
            return None
        rules = yahoo.settings()
        if rules.best_game:
            raise UnsupportedError(league.name, "a forecast where only each player's best game scores")
        mine, theirs = yahoo.roster(team.team_key), yahoo.roster(found.opponent.team_key)
        week_left = nba_forecast.Week(
            games=self._recent,
            left=self.games.games_left(found.start, found.end),
            returns=self._returns([*mine, *theirs], self._reports()),
            weekly=rules.weekly_lineups,
            seed=seed(league.league_key, week),
        )
        if league.by_points and not rules.weights:
            raise UnsupportedError(league.name, "a forecast without the points its settings would sum")
        matchup = (
            nba_forecast.points(found, mine, theirs, week_left, rules.weights)
            if league.by_points
            else nba_forecast.categories(found, mine, theirs, week_left, rules.categories)
        )
        # Games the NBA has yet to schedule are games nobody is drawn for: the chance is read off a short week.
        return replace(matchup, provisional=bool(self.games.unscheduled(found.start, found.end)))

    def _recent(self, player: YahooPlayer) -> list[NBAGameLog]:
        return self.form.recent_games(player.name)

    def played_weeks(self, league_id: str) -> list[int]:
        """None: a basketball week is not yet rebuilt as it stood before it began, so it is not backtested."""
        return []

    def played_matchups(
        self, league_id: str, week: int, settings: Mapping[str, float] | None = None
    ) -> list[PlayedMatchup]:
        """None, for the reason `played_weeks` names none."""
        return []

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> CompetitionContext:
        """Price both sides of a trade against the current roster, in the league's own scoring."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        weights = self._weights(league, yahoo)
        builder = PlayerContextBuilder(self.form, self.games, weights)
        giving, receiving = resolve_sides(proposal, lambda name: _find_player(yahoo, name))

        my_team = yahoo.get_user_team()
        week = yahoo.get_matchup(my_team.team_key)

        # Not enrichment: a trade is judged against the roster it changes, and
        # one judged without it is an answer to a different question.
        rostered = yahoo.roster(my_team.team_key)
        returns = self._returns([*rostered, *giving, *receiving], self._reports())
        roster = builder.build_player_lines(
            rostered, week.start if week else None, week.end if week else None, returns=returns
        )

        text = prompt.trade(
            giving=builder.build_context_for_players(giving, returns=returns),
            receiving=builder.build_context_for_players(receiving, returns=returns),
            week=week,
            roster="".join(roster.values()),
            weights=weights,
        )
        return CompetitionContext(prompt=text, situation=prompt.matchup(week, weights), roster_lines=roster)

    def trade_market(self, league_id: str) -> TradeMarket | None:
        """The rest of the season, and every trade near even in worth that improves your weeks (`market.build`).

        None between seasons, once the regular season is over, and past the
        trade deadline the league's settings name. A category league is
        searched where a week counts as one win (Yahoo's "H2H Cat One"), which
        is what its table and the season's simulation count.

        Raises:
            UnsupportedError: a league whose table counts every category, scores only a best game, or whose points
                settings carry no weights.
            PlatformError: the schedule would not load.
        """
        league = self._league(league_id)
        current = league.current_week
        if not current:
            return None
        yahoo = self._yahoo_for(league)
        rules = yahoo.settings()
        if not rules.playoff_start_week or current >= rules.playoff_start_week:
            return None
        if rules.trade_end is not None and datetime.now(PACIFIC).date() > rules.trade_end:
            return None
        categories = self._judged_on(league, rules)
        mine = yahoo.get_user_team().team_key
        standings = yahoo.standings()
        drawn = yahoo.matchups(list(range(current, league.last_week(current) + 1)))
        dates = nba_league.week_dates(drawn)
        if current not in dates:
            return None
        rosters = yahoo.rosters([team.team_key for team in standings])
        try:
            wire = _wire(yahoo, STREAM_DEPTH)
        except FrontOfficeError as e:
            logger.warning(f"Pricing trades without the wire, which would not load: {e}")
            wire = []
        players = once(p for roster in [*rosters.values(), wire] for p in roster)
        weights = self._weights(league, yahoo)
        start, end = dates[current]
        readings = self._readings(yahoo, weights, players, start, end)
        returns = self._returns(players, self._reports())
        weeks = [
            nba_market.Week(
                week=week,
                days={
                    p.player_key: frozenset(nba_strength.nights(p, games, returns.get(p.player_key))) for p in players
                },
                pairs=[(found.mine.team_key, found.opponent.team_key) for found in drawn.get(week, [])],
            )
            for week, (first, last) in sorted(dates.items())
            for games in [
                self.games.games_left(first, last) if week == current else self.games.games_between(first, last)
            ]
        ]
        this_week = {
            side.team_key: nba_strength.banked(side, categories, points=weights is not None)
            for found in drawn.get(current, [])
            for side in (found.mine, found.opponent)
        }
        return nba_market.build(
            nba_market.League(
                mine=mine,
                teams=[
                    TeamRecord(t.team_key, t.name, s.wins, s.losses, s.ties, amount(s.points_for))
                    for t in standings
                    if (s := t.standing) is not None
                ],
                rosters=rosters,
                profiles={
                    key: nba_strength.profile(reading, self._recent(reading.player), weights)
                    for key, reading in readings.items()
                },
                weeks=weeks,
                playoff_start=rules.playoff_start_week,
                spots=rules.playoff_teams,
                slots=rules.starting or nba_forecast.active_slots(*rosters.values()),
                roster_size=rules.roster_size,
                categories=categories,
                banked=this_week,
                wire=wire,
                weekly=rules.weekly_lineups,
                deadline=rules.trade_end,
                seed=seed(league.league_key, current),
            )
        )

    @staticmethod
    def _judged_on(league: YahooLeague, rules: LeagueSettings) -> tuple[nba_strength.Scored, ...]:
        """The categories a week is won on, none in a points league.

        Raises:
            UnsupportedError: a week the season's simulation cannot settle as one result.
        """
        if rules.best_game:
            raise UnsupportedError(league.name, "a trade search where only each player's best game scores")
        if league.by_points:
            if not rules.weights:
                raise UnsupportedError(league.name, "a trade search without the points its settings would sum")
            return ()
        if league.scoring_type != ONE_WIN:
            raise UnsupportedError(league.name, "a trade search where every category counts in the table")
        return nba_strength.scored(rules.categories)

    # ── players and teams ───────────────────────────────────────────

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, each player with Yahoo's averages over the last month."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        team = yahoo.get_user_team().team_key
        return self._cards(yahoo, league, yahoo.roster(team), self._roster_averages(yahoo, team))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        yahoo = self._yahoo(league_id)
        records = self._records(yahoo)
        refs = [
            TeamRef(
                team_id=team.team_key,
                name=team.name,
                detail=records.get(team.team_key, ""),
                url=nba_league.team_url(team.team_key),
                is_mine=team.is_mine,
            )
            for team in yahoo.teams()
        ]
        return sorted([r for r in refs if r.team_id], key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's roster, in the same columns as your own."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        if not any(t.team_key == team_id for t in yahoo.teams()):
            raise TeamNotFoundError(team_id)
        return self._cards(yahoo, league, yahoo.roster(team_id), self._roster_averages(yahoo, team_id))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds, the most worth picking up this week first (`views.by_worth`).

        Drawn from Yahoo's own ranks rather than a category's — season and last
        week in turn (`_wire`): a wire browsed one stat at a time is the scout's
        job, and this is the list you read when you just want to see who is out
        there. Where his week cannot be read, a player keeps Yahoo's order after
        those whose can.
        """
        paging.view(query, ())  # no other lists: one asked for is refused, not ignored
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        wire = _wire(yahoo)
        # Each page of the wire carries its players' averages, so the table costs no read beyond the list.
        cards = self._cards(yahoo, league, wire, _carried(wire), wire=True)
        return paging.page(cards, query, position_filters(wire, yahoo.settings().positions))

    def search_players(self, league_id: str, text: str, limit: int = 10) -> list[PlayerRef]:
        """Anyone in the league whose name holds `text`, rostered or not, in Yahoo's order.

        Read from a browser sync, only the players it carried — every roster and the wire it read.
        """
        if len(text.strip()) < 2:
            return []
        found = self._yahoo(league_id).search_players(text.strip())
        return [
            PlayerRef(
                player_id=p.player_key, name=p.name, detail=" · ".join(part for part in (p.position, p.team) if part)
            )
            for p in found[:limit]
        ]

    def _cards(
        self,
        yahoo: YahooSource,
        league: YahooLeague,
        players: list[YahooPlayer],
        recent: Mapping[str, YahooLine],
        wire: bool = False,
    ) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows (`views.cards`); the wire's with teammate splits.

        A category league's carry each player's value a game (`_valued`), which orders them. The wire is
        ordered by what he is worth this week instead (`views.by_worth`), in either kind of league.
        """
        reports = self._reports()
        weights = self._weights(league, yahoo)
        splits = self._splits(players, weights, reports) if wire else None
        scored = [] if weights else yahoo.settings().categories
        readings = self._valued(yahoo, league, players, weights) if wire or not weights else {}
        rows = views.cards(
            players, recent, self._returns(players, reports), weights is not None, splits, scored, readings
        )
        return views.by_worth(rows, readings) if wire else rows

    def _valued(
        self, yahoo: YahooSource, league: YahooLeague, players: list[YahooPlayer], weights: Mapping[str, float] | None
    ) -> dict[str, Reading]:
        """Each of `players`' week, a category league's read on the week's own scale: the pool the to-do list weighs,
        so a value reads alike.

        That pool is both rosters of this week's matchup and the top of the wire
        (`_decide`); `players` are read on it without joining it. A points league's
        fantasy points need no scale, so `players` are their own pool. Enrichment:
        none between seasons, in a week without a matchup, or where a read fails —
        the table stands, its values dashed and in its own order.
        """
        week = league.current_week
        if not week:
            return {}
        try:
            team = yahoo.get_user_team()
            found = yahoo.pairing(team.team_key, week)
            if found is None:
                return {}
            if weights:
                return self._readings(yahoo, weights, players, found.start, found.end)
            pool = [*yahoo.roster(team.team_key), *yahoo.roster(found.opponent.team_key), *_wire(yahoo, STREAM_DEPTH)]
            return self._readings(yahoo, None, pool, found.start, found.end, players)
        except FrontOfficeError as e:
            logger.warning(f"Showing players without their value a game: {e}")
            return {}

    def _averages(self, yahoo: YahooSource, *team_keys: str) -> dict[str, YahooLine]:
        """Yahoo's averages over the last month for every player these teams hold, by key (`_roster_averages`)."""
        return {key: line for team in team_keys for key, line in self._roster_averages(yahoo, team).items()}

    @staticmethod
    def _roster_averages(yahoo: YahooSource, team_key: str) -> dict[str, YahooLine]:
        """Each of a team's players' averages over the last month, in one read; none where it will not load.

        Enrichment: a roster without them is a table of dashes, not a failed page.
        """
        try:
            return yahoo.roster_averages(team_key, RECENT_AVERAGE)
        except FrontOfficeError as e:
            logger.warning(f"Showing the roster without Yahoo's averages: {e}")
            return {}

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """Any player in the league — yours, a rival's or a free agent — with his week, his averages and his games.

        Yahoo's averages over his season and his last month, read together, as
        every table shows them; Sleeper's box scores game by game, its
        projection and its catalog; his week weighed as the to-do list weighs
        it. Seasons, history and news are read only when their tab is opened
        (`player_tab`).
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        player = self._player(yahoo, player_id)
        try:
            spans = yahoo.averages([player_id], (Average.SEASON, RECENT_AVERAGE))
        except FrontOfficeError as e:
            logger.warning(f"Showing {player.name} without Yahoo's averages: {e}")
            spans = {}
        weights = self._weights(league, yahoo)
        reports = self._reports()
        profile = self.form.profile(player.name)
        week = self._week_of(yahoo, league, player, reports, weights, profile)
        games = self.form.games(player.name)
        return views.detail(
            views.Drawer(
                player=player,
                season=spans.get(Average.SEASON, {}).get(player_id),
                recent=spans.get(RECENT_AVERAGE, {}).get(player_id),
                scored=yahoo.settings().categories,
                weights=weights,
                reported=self._injuries([player], reports).stats(player_id),
                splits=self._splits([player], weights, reports)(player),
                week=week[0] if week else None,
                games=games,
                venues=self._venues(player, games),
                value=week[1] if week else self._points_valuer(weights),
                profile=profile,
            )
        )

    def player_tab(self, league_id: str, player_id: str, tab: str) -> PlayerDetail:
        """One of his drawer's tabs read only when opened (`views.DEFERRED`), each a request of its own.

        Seasons are Sleeper's, this one and the two before it, a request each
        and shared by every player; history is the league's moves on Yahoo, one
        request for the season's; news is ESPN's feed for his club.

        Raises:
            PlayerNotFoundError: nothing in this league has that identifier.
            NotFoundError: the drawer defers no tab of that name.
            FrontOfficeError: the tab's one source would not load.
        """
        if tab not in views.DEFERRED:
            raise NotFoundError(f"a drawer tab named {tab!r}")
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        player = self._player(yahoo, player_id)
        if tab == views.SEASONS_TAB:
            table = views.seasons(self._seasons(player), self._weights(league, yahoo))
            return views.deferred_tab(player, tables=[table] if table else [])
        if tab == views.HISTORY_TAB:
            mine = yahoo.get_user_team().name
            return views.deferred_tab(player, moves=history.moves(yahoo.transactions(), player_id, mine))
        club = espn_club(player.team)
        feeds = self.espn.get_team_news(NBA, [club])
        found = news.attach(feeds, by_club([(club, player.name, player_id)]), datetime.now(UTC))
        return views.deferred_tab(player, groups=views.news(found.stats(player_id, limit=views.NEWS_IN_DRAWER)))

    @staticmethod
    def _player(yahoo: YahooSource, player_id: str) -> YahooPlayer:
        """The player a key names, with whose roster he is on.

        Raises:
            PlayerNotFoundError: the league knows nobody by that key.
        """
        found = yahoo.players([player_id])
        if not found:
            raise PlayerNotFoundError([player_id])
        return found[0]

    def _seasons(self, player: YahooPlayer) -> dict[str, NBASeason | None]:
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

    def _week_of(
        self,
        yahoo: YahooSource,
        league: YahooLeague,
        player: YahooPlayer,
        reports: Sequence[InjuryReport],
        weights: Mapping[str, float] | None,
        profile: PlayerMeta | None,
    ) -> tuple[views.DrawerWeek, nba_worth.Valuer | None] | None:
        """His matchup week as the drawer shows it, and what a game is worth on the week's scale; None without one.

        Counted as his row counts it (`_games`): none while ruled out, or from
        his return. Weighed on the to-do list's own pool (`_valued`), so the
        value it shows is the one his row shows. Each part is enrichment:
        whatever will not load is left out, and the rest stands.
        """
        week = league.current_week
        if not week:
            return None
        try:
            found = yahoo.pairing(yahoo.get_user_team().team_key, week)
        except FrontOfficeError as e:
            logger.warning(f"Showing {player.name} without his week: {e}")
            return None
        if found is None:
            return None
        start, end = found.start, found.end
        back = self._returns([player], reports).get(player.player_key)
        clubs = self.games.get_remaining_games_bulk([player.team], start, end)
        games = self._games(player, clubs, back, end)
        provisional = bool(self.games.unscheduled(start, end))
        club = player.team.upper()
        # A claim's games are those after he clears waivers, as `_games` counts them.
        claimed = playable_from(player)
        after = claimed.isoformat() if claimed else ""
        try:
            fixtures = [g for g in self.games.games_left(start, end) if club in (g.home, g.away) and g.date >= after]
        except FrontOfficeError as e:
            logger.warning(f"Showing {player.name}'s week without its games: {e}")
            fixtures = []
        projections = index_for(self.sleeper, start, end)
        stats = self.form.get_player_stats(player.name)
        projected = projections.find(player.name, player.team, stats) if projections else None
        value = self._week_valuer(yahoo, weights, found)
        reading = nba_worth.read(player, stats, projected, value, games, provisional, back) if value else None
        matchup = None
        if fixtures and profile:
            opponent = fixtures[0].away if fixtures[0].home == club else fixtures[0].home
            matchup = defense.allowed(self.form.box_scores(), weights).get((opponent, profile.position))
        left = views.counted(games, provisional)
        return views.DrawerWeek(left, fixtures, reading, projected, matchup), value

    def _week_valuer(
        self, yahoo: YahooSource, weights: Mapping[str, float] | None, found: Pairing
    ) -> nba_worth.Valuer | None:
        """What a game is worth on the week's scale: fantasy points, or a category league's value across the pool.

        The pool is the to-do list's (`_decide`): both rosters of this week's
        matchup and the top of the wire, most of it read already by the page
        the drawer opened from. None where it will not load.
        """
        if weights:
            return nba_worth.points_value(weights)
        try:
            pool = [
                *yahoo.roster(found.mine.team_key),
                *yahoo.roster(found.opponent.team_key),
                *_wire(yahoo, STREAM_DEPTH),
            ]
            projections = index_for(self.sleeper, found.start, found.end)
            lines: list[Line] = []
            for p in once(pool):
                stats = self.form.get_player_stats(p.name)
                projected = projections.find(p.name, p.team, stats) if projections else None
                if line := nba_worth.per_game(stats, projected):
                    lines.append(line)
            return _valuer(yahoo, None, lines)[0]
        except FrontOfficeError as e:
            logger.warning(f"Showing the drawer without a value a game: {e}")
            return None

    @staticmethod
    def _points_valuer(weights: Mapping[str, float] | None) -> nba_worth.Valuer | None:
        """A points league's fantasy points, which need no pool; None in a category league, which does."""
        return nba_worth.points_value(weights) if weights else None

    def _venues(self, player: YahooPlayer, games: Sequence[NBAGameLog]) -> dict[str, ScheduledGame]:
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

    def _reports(self) -> list[InjuryReport]:
        """ESPN's NBA injury report; empty where it will not load, which leaves Yahoo's statuses standing alone."""
        try:
            return self.espn.get_injuries(NBA)
        except ESPNAPIError as e:
            logger.warning(f"Continuing on Yahoo's injury statuses alone: {e}")
            return []

    @staticmethod
    def _injuries(players: list[YahooPlayer], reports: Sequence[InjuryReport]) -> PlayerInjuries:
        """Each of `players` on ESPN's injury report, keyed by Yahoo's key, where it names him.

        Yahoo carries no ESPN id, so the join is by full name within his club
        alone, refusing a name two of them there share.
        """
        clubs = by_club((espn_club(p.team), p.name, p.player_key) for p in players)
        return PlayerInjuries(by_player=matched(reports, clubs, {}))

    def _returns(self, players: list[YahooPlayer], reports: Sequence[InjuryReport]) -> dict[str, date]:
        """The day ESPN expects each of `players` back, keyed by Yahoo's key; nobody it gives none for."""
        injuries = self._injuries(players, reports)
        return {p.player_key: back for p in players if (back := injuries.returns(p.player_key))}

    def _splits(
        self, players: list[YahooPlayer], weights: Mapping[str, float] | None, reports: Sequence[InjuryReport]
    ) -> Callable[[YahooPlayer], list[Split]]:
        """Each player's line without each regular teammate who is hurt or lately sat out (`teammates.py`).

        A teammate's condition is Yahoo's status where his row is among
        `players`, else ESPN's report; the box scores are read once for them all.
        """
        mates = Teammates(self.form.box_scores(), weights)
        regulars = mates.regulars()
        known = conditions(regulars, players, reported(regulars, reports))
        return lambda player: mates.splits(player, known)


def _valuer(
    yahoo: YahooSource, weights: Mapping[str, float] | None, lines: list[Line]
) -> tuple[nba_worth.Valuer, dict[str, nba_worth.Scale]]:
    """What a game is worth in the league's scoring, and each category's scale: fantasy points under `weights`, or
    a category league's value scaled across `lines` (`worth.category_value`)."""
    if weights:
        return nba_worth.points_value(weights), {}
    scored = yahoo.settings().categories
    return nba_worth.category_value(scored, lines), nba_worth.scales(scored, lines)


def _carried(players: Sequence[YahooPlayer]) -> dict[str, YahooLine]:
    """The averages over the last month each of `players` carries, by key, where his page read them."""
    return {p.player_key: p.line for p in players if p.coverage == RECENT_AVERAGE}


def _wire(yahoo: YahooSource, depths: Mapping[Timeframe, int] = WIRE_DEPTH) -> list[YahooPlayer]:
    """The available players under every ranking in `depths`, taken from each in turn, each player once.

    Interleaved rather than one list after the other, so the week's risers sit
    beside the season's best instead of below three hundred of them.
    """
    rankings = list(yahoo.fetch_available(depths).values())
    return once(p for row in zip_longest(*rankings) for p in row if p is not None)


def _find_player(yahoo: YahooSource, name: str) -> YahooPlayer | None:
    """The one Yahoo player a name refers to, or None — never a guess.

    Yahoo's search matches substrings, so a name can come back with others
    beside it, and an exact match among them wins. Failing any match, the
    surname alone tolerates first-name spelling ("Lebron" for "LeBron"), but
    only where it finds one player: two Williamses resolve to neither.
    """
    players = yahoo.search_players(name)
    parts = name.split()
    if not players and len(parts) > 1:
        players = yahoo.search_players(parts[-1])

    wanted = normalize_name(name)
    candidates = [p for p in players if normalize_name(p.name) == wanted] or players
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning(f"{len(candidates)} players match {name!r}; resolving to none rather than guessing")
    return None


YAHOO_GAME = YahooGame(
    code="nba",
    season=YahooNBAProvider.season_year,
    available=WIRE_DEPTH,
    leaders=LEADERS,
    per_stat=LEADERS_PER_STAT,
)
"""What this provider reads of Yahoo's NBA game, so a browser sync captures exactly that."""
