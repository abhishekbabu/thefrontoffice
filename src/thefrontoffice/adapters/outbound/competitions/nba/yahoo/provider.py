"""NBA on Yahoo.

Head-to-head basketball, won on categories or on fantasy points as the league's
settings say: the forward-looking number is games remaining in the matchup
period crossed with recent form — per category, or summed under the league's
weights — and the budget constraint is the league's weekly add limit.

The ports, and the plumbing that finds the league each one reads. What they read is beside it:
`reads.py` (Yahoo), `feeds.py` (Sleeper and ESPN), `weighing.py` (the week weighed), `scouting.py` (the
scout's prompts), `trading.py` (trades) and `drawn.py` (a player's week in the drawer).
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from thefrontoffice.adapters.outbound.competitions import news, paging, places
from thefrontoffice.adapters.outbound.competitions.injuries import by_club
from thefrontoffice.adapters.outbound.competitions.nba import drawer, history, views
from thefrontoffice.adapters.outbound.competitions.nba import forecast as nba_forecast
from thefrontoffice.adapters.outbound.competitions.nba import league as nba_league
from thefrontoffice.adapters.outbound.competitions.nba import lineup as nba_lineup
from thefrontoffice.adapters.outbound.competitions.nba import outlook as nba_outlook
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.form import FormSource
from thefrontoffice.adapters.outbound.competitions.nba.model import Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    position_filters,
)
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import drawn, reads, scouting, trading, weighing
from thefrontoffice.adapters.outbound.competitions.nba.yahoo.feeds import Feeds
from thefrontoffice.adapters.outbound.competitions.seeds import seed
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooLeagueSource
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import RECENT_AVERAGE
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    Pairing,
    YahooLeague,
    YahooTeam,
)
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    LeagueNotFoundError,
    NotFoundError,
    TeamNotFoundError,
    UnsupportedError,
)
from thefrontoffice.domain.models import (
    CompetitionContext,
    Forecast,
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
    TeamRef,
    TradeMarket,
    TradeProposal,
    WeekRange,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)


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
        forecast: Callable[[MatchupInput], Forecast],
    ):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        `yahoo_for` rather than one client because a Yahoo client is bound to a
        league, and every call names the league it reads. `fallback_weekly_adds`
        is the add limit for a league whose settings name none. `form` and
        `games` are both read from Sleeper: each player's recent run, and the
        real games inside a matchup week. `forecast` plays a matchup out — the
        same simulation the week's chance comes from — so a category league's
        pickups weigh the categories still in play.
        """
        self._auth = auth
        self._yahoo_for = yahoo_for
        self.form = form
        self.games = games
        self.sleeper = sleeper
        self.espn = espn
        self.fallback_weekly_adds = fallback_weekly_adds
        self.forecast = forecast
        self.feeds = Feeds(form=form, games=games, sleeper=sleeper, espn=espn)
        self._found: list[YahooLeague] | None = None

    def _leagues(self) -> list[YahooLeague]:
        """This season's leagues, found once per provider: the first is read when a call names none.

        Raises:
            LeagueNotFoundError: the login plays in no NBA league this season.
        """
        if self._found is None:
            self._found = self._auth.find_leagues(reads.YAHOO_GAME.code, self.season_year())
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

    def refresh(self, league_id: str) -> int:
        """Drop what is kept of the league that a move or a new week changes, the league list with it."""
        return self._yahoo(league_id).forget()

    def _add_limit(self, yahoo: YahooSource) -> int:
        """The league's weekly add limit, as its settings name it, or the configured one where they name none."""
        limit = yahoo.settings().max_weekly_adds
        return self.fallback_weekly_adds if limit is None else limit

    @staticmethod
    def _adds_left(yahoo: YahooSource, team_key: str, limit: int) -> int:
        """What is left of a team's weekly adds, by Yahoo's count of those it has made (`YahooTeam.adds_used`).

        Enrichment: none where the league's teams will not load, so its streaming is not counted.
        """
        try:
            team = next((t for t in yahoo.teams() if t.team_key == team_key), None)
        except FrontOfficeError as e:
            logger.warning(f"Counting the race in games without {team_key}'s adds left: {e}")
            return 0
        return max(0, limit - team.adds_used) if team is not None else 0

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
        decided: list[weighing.Decided] = []

        def read(found: Pairing, theirs: Sequence[Player]) -> Mapping[str, Reading]:
            adds_left = max(0, limit - my_team.adds_used)
            claimed = history.claimed(reads.pending(yahoo, my_team.team_key))
            shown = reads.averages(yahoo, found.mine.team_key, found.opponent.team_key)
            chances = (
                None if league.by_points or not week else self._chances(league, yahoo, week, found, (roster, theirs))
            )
            decided.append(
                weighing.decide(
                    self.feeds,
                    yahoo,
                    league,
                    roster,
                    theirs,
                    found.start,
                    found.end,
                    adds_left,
                    shown=shown,
                    chances=chances,
                    their_adds=self._adds_left(yahoo, found.opponent.team_key, limit),
                    claimed=claimed,
                )
            )
            return decided[0].readings

        board = self._board(yahoo, league, my_team, week, roster, read) if week else Summary()
        # Without a matchup this week there is no week to weigh anybody on: only the IL moves stand.
        items = decided[0].actions if decided else nba_week.off_il(roster)
        volume = nba_week.volume(*decided[0].volume, decided[0].streams) if decided and decided[0].volume else []
        return board.model_copy(update={"headline": [*adds, *volume, *board.headline], "actions": items or None})

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
        weights = reads.weights(league, yahoo)

        def read(found: Pairing, theirs: Sequence[Player]) -> Mapping[str, Reading]:
            shown = reads.averages(yahoo, found.mine.team_key, found.opponent.team_key)
            return weighing.read_week(
                self.feeds, yahoo, weights, [*roster, *theirs], found.start, found.end, averages=shown
            )

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
        roster: Sequence[Player] | None,
        read: Callable[[Pairing, Sequence[Player]], Mapping[str, Reading]] | None = None,
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
        records = reads.records(yahoo)
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
        today = None if played or week != current else self.feeds.today(found.start, found.end)
        if today is not None and roster is not None:
            today = replace(
                today, played=reads.played_today(yahoo, [team.team_key, found.opponent.team_key], today.day)
            )
        return nba_week.board(found, weeks, records, roster, theirs, scored, readings, unscheduled, today)

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The table, your head-to-head season from every week's scoreboard, and the league's moves lately.

        Between seasons there are no weeks to read, so only the table and the
        moves. Yahoo publishes no real-world NBA schedule through this SDK, so
        that section stays empty and renders as nothing.

        Raises:
            YahooCaptureMissingError: read from a browser sync that has not carried the table.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        team = yahoo.get_user_team()
        mine = team.team_key
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
        return LeagueSchedule(
            headline=headline, season=season, standings=standings, activity=reads.activity(yahoo, team)
        )

    def build_context(self, league_id: str = "") -> CompetitionContext:
        """Gather league state and render the scouting prompt."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        return scouting.context(self.feeds, yahoo, league, self._add_limit(yahoo))

    # ── the wire ────────────────────────────────────────────────────

    def build_wire_context(self, league_id: str, player_ids: list[str]) -> CompetitionContext:
        """The prompt asking for one call per listed free agent.

        Raises:
            PlayerNotFoundError: an id is rostered in this league, or not on the wire.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        return scouting.wire_context(self.feeds, yahoo, league, self._add_limit(yahoo), player_ids)

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
            wire = reads.wire(yahoo, reads.STREAM_DEPTH)
        except FrontOfficeError as e:
            logger.warning(f"Planning the weeks ahead without the wire, which would not load: {e}")
            wire = []
        weights = reads.weights(league, yahoo)
        readings = weighing.read_week(self.feeds, yahoo, weights, [*roster, *wire], windows[0].start, windows[-1].end)
        returns = reads.returns([*roster, *wire], self.feeds.reports())
        lineup = nba_lineup.slots(yahoo.settings().slots)
        return nba_outlook.build(windows, roster, wire, readings, returns, self._add_limit(yahoo), lineup)

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
        mine, theirs = yahoo.roster(team.team_key), yahoo.roster(found.opponent.team_key)
        return self._matchup(league, yahoo, week, found, (mine, theirs))

    def _matchup(
        self,
        league: YahooLeague,
        yahoo: YahooSource,
        week: int,
        found: Pairing,
        sides: tuple[Sequence[Player], Sequence[Player]],
    ) -> MatchupInput:
        """Week `week`, which `found` pairs, ready to simulate: what each side has, and every game still to come.

        Raises:
            UnsupportedError: the league scores something a box score here cannot build.
            PlatformError: the schedule would not load.
        """
        mine, theirs = sides
        rules = yahoo.settings()
        if rules.best_game:
            raise UnsupportedError(league.name, "a forecast where only each player's best game scores")
        week_left = nba_forecast.Week(
            games=self.feeds.recent,
            left=self.games.games_left(found.start, found.end),
            returns=reads.returns([*mine, *theirs], self.feeds.reports()),
            weekly=rules.weekly_lineups,
            seed=seed(league.league_key, week),
            lineup=nba_lineup.slots(rules.slots),
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

    def _chances(
        self,
        league: YahooLeague,
        yahoo: YahooSource,
        week: int,
        found: Pairing,
        sides: tuple[Sequence[Player], Sequence[Player]],
    ) -> dict[str, float] | None:
        """Your chance of winning each category this week, by the league's name for it: the forecast's own, on the
        same matchup it is read from, so the page and the to-do list share one simulation.

        Enrichment: None where the week cannot be simulated, and the to-do list
        then weighs every category alike.
        """
        try:
            return dict(self.forecast(self._matchup(league, yahoo, week, found, sides)).categories) or None
        except FrontOfficeError as e:
            logger.warning(f"Weighing pickups on every category alike, without a forecast: {e}")
            return None

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
        return trading.context(self.feeds, self._yahoo_for(league), league, proposal)

    def trade_market(self, league_id: str) -> TradeMarket | None:
        """The rest of the season, and every trade near even in worth that improves your weeks (`market.build`).

        Raises:
            UnsupportedError: a league whose table counts every category, scores only a best game, or whose points
                settings carry no weights.
            PlatformError: the schedule would not load.
        """
        league = self._league(league_id)
        return trading.market(self.feeds, self._yahoo_for(league), league)

    # ── players and teams ───────────────────────────────────────────

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, each player with Yahoo's averages over the last month."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        team = yahoo.get_user_team().team_key
        return self._cards(yahoo, league, yahoo.roster(team), reads.roster_averages(yahoo, team))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        yahoo = self._yahoo(league_id)
        records = reads.records(yahoo)
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
        return self._cards(yahoo, league, yahoo.roster(team_id), reads.roster_averages(yahoo, team_id))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds, the most worth picking up this week first (`views.by_worth`).

        Drawn from Yahoo's own ranks rather than a category's — season and last
        week in turn (`reads.wire`): a wire browsed one stat at a time is the scout's
        job, and this is the list you read when you just want to see who is out
        there. Where his week cannot be read, a player keeps Yahoo's order after
        those whose can.
        """
        paging.view(query, ())  # no other lists: one asked for is refused, not ignored
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        wire = reads.wire(yahoo)
        # Each page of the wire carries its players' averages, so the table costs no read beyond the list.
        cards = self._cards(yahoo, league, wire, reads.carried(wire), wire=True)
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
        players: Sequence[Player],
        recent: Mapping[str, PrintedLine],
        wire: bool = False,
    ) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows (`views.cards`); the wire's with teammate splits.

        A category league's carry each player's value a game (`weighing.valued`), which orders them. The wire is
        ordered by what he is worth this week instead (`views.by_worth`), in either kind of league.
        """
        reports = self.feeds.reports()
        weights = reads.weights(league, yahoo)
        splits = self.feeds.splits(players, weights, reports) if wire else None
        scored = [] if weights else yahoo.settings().categories
        readings = weighing.valued(self.feeds, yahoo, league, players, weights) if wire or not weights else {}
        rows = views.cards(
            players, recent, reads.returns(players, reports), weights is not None, splits, scored, readings, wire=wire
        )
        return views.by_worth(rows, readings) if wire else rows

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
        player = reads.player(yahoo, player_id)
        try:
            spans = yahoo.averages([player_id], (Average.SEASON, RECENT_AVERAGE))
        except FrontOfficeError as e:
            logger.warning(f"Showing {player.name} without Yahoo's averages: {e}")
            spans = {}
        weights = reads.weights(league, yahoo)
        reports = self.feeds.reports()
        profile = self.form.profile(player.name)
        week = drawn.week_of(self.feeds, yahoo, league, player, reports, weights, profile)
        games = self.form.games(player.name)
        return drawer.detail(
            drawer.Drawer(
                player=player,
                season=spans.get(Average.SEASON, {}).get(player_id),
                recent=spans.get(RECENT_AVERAGE, {}).get(player_id),
                scored=yahoo.settings().categories,
                weights=weights,
                reported=reads.injuries([player], reports).stats(player_id),
                splits=self.feeds.splits([player], weights, reports)(player),
                week=week[0] if week else None,
                games=games,
                venues=self.feeds.venues(player, games),
                value=week[1] if week else reads.points_valuer(weights),
                profile=profile,
                priority=yahoo.get_user_team().waiver_priority if player.waiver_date else 0,
            )
        )

    def player_tab(self, league_id: str, player_id: str, tab: str) -> PlayerDetail:
        """One of his drawer's tabs read only when opened (`drawer.DEFERRED`), each a request of its own.

        Seasons are Sleeper's, this one and the two before it, a request each
        and shared by every player; history is the league's moves on Yahoo, one
        request for the season's; news is ESPN's feed for his club.

        Raises:
            PlayerNotFoundError: nothing in this league has that identifier.
            NotFoundError: the drawer defers no tab of that name.
            FrontOfficeError: the tab's one source would not load.
        """
        if tab not in drawer.DEFERRED:
            raise NotFoundError(f"a drawer tab named {tab!r}")
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        player = reads.player(yahoo, player_id)
        if tab == drawer.SEASONS_TAB:
            table = drawer.seasons(self.feeds.seasons(player), reads.weights(league, yahoo))
            return drawer.deferred_tab(player, tables=[table] if table else [])
        if tab == drawer.HISTORY_TAB:
            mine = yahoo.get_user_team().name
            return drawer.deferred_tab(player, moves=history.moves(yahoo.transactions(), player_id, mine))
        club = espn_club(player.team)
        feeds = self.espn.get_team_news(NBA, [club])
        found = news.attach(feeds, by_club([(club, player.name, player_id)]), datetime.now(UTC))
        return drawer.deferred_tab(player, groups=drawer.news(found.stats(player_id, limit=drawer.NEWS_IN_DRAWER)))
