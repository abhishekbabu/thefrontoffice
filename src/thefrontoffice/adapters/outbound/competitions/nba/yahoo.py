"""NBA on Yahoo.

Head-to-head basketball, won on categories or on fantasy points as the league's
settings say: the forward-looking number is games remaining in the matchup
period crossed with recent form — per category, or summed under the league's
weights — and the budget constraint is the league's weekly add limit.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from itertools import zip_longest

from thefrontoffice.adapters.outbound.competitions import paging, places
from thefrontoffice.adapters.outbound.competitions.injuries import PlayerInjuries, by_club, matched
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba import league as nba_league
from thefrontoffice.adapters.outbound.competitions.nba import prompt, views
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.context import (
    PlayerContextBuilder,
    rank_by_points,
    rank_free_agents,
)
from thefrontoffice.adapters.outbound.competitions.nba.form import FormSource
from thefrontoffice.adapters.outbound.competitions.nba.projections import index_for
from thefrontoffice.adapters.outbound.competitions.nba.rules import SCOUTED
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Split, Teammates, conditions, reported
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.competitions.trades import resolve_sides
from thefrontoffice.adapters.outbound.platforms.espn.client import ESPNSource
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import NBA, InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperProjectionSource
from thefrontoffice.adapters.outbound.platforms.yahoo.auth import YahooLeagueSource
from thefrontoffice.adapters.outbound.platforms.yahoo.capture import YahooGame
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooSource, once
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Timeframe, YahooLeague, YahooPlayer, YahooTeam
from thefrontoffice.domain.errors import LeagueNotFoundError, NotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import (
    CompetitionContext,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    PlayerRef,
    Slate,
    Summary,
    TeamRef,
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

LEADERS = {c.label: c.yahoo_stat for c in SCOUTED}
"""The stats the free-agent scout ranks the wire by, a request each."""

LEADERS_PER_STAT = 10


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
        """The week being played: the add budget, the score, both rosters, and the to-do list.

        The one to-do item it computes is a player an injured slot no longer takes;
        with none, there is no list, rather than an empty one claiming there is nothing to do.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        my_team = yahoo.get_user_team()
        roster = yahoo.roster(my_team.team_key)
        stuck = nba_week.off_il(roster)
        week = league.current_week
        board = self._board(yahoo, league, my_team, week, roster) if week else Summary()
        return board.model_copy(
            update={
                "headline": [*nba_week.adds(my_team.adds_used, self._add_limit(yahoo)), *board.headline],
                "actions": stuck or None,
            }
        )

    def week_of(self, league_id: str, week: int) -> Summary:
        """Any week of the season: its score as it finished or stands, and no to-do list.

        A week to come shows both rosters as they stand today, against that
        week's opponent; a week played shows none (`week.side` says why).

        Raises:
            NotFoundError: the season has no such week.
        """
        league = self._league(league_id)
        current = self._within(league, week)
        yahoo = self._yahoo_for(league)
        my_team = yahoo.get_user_team()
        roster = yahoo.roster(my_team.team_key) if week >= current else None
        return self._board(yahoo, league, my_team, week, roster)

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
        return Slate(games=[nba_week.match(game, roster) for game in self.games.games_between(found.start, found.end)])

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
        self, yahoo: YahooSource, league: YahooLeague, team: YahooTeam, week: int, roster: list[YahooPlayer] | None
    ) -> Summary:
        """One week's head-to-head, and where it sits in the season.

        `roster` is yours where rosters are shown, and None where they are not;
        the opponent's is read alongside it.
        """
        current = league.current_week or week
        weeks = WeekRange(week=week, current=current, first=league.first_week, last=league.last_week(current))
        found = yahoo.pairing(team.team_key, week)
        if found is None:
            return Summary(window=f"Week {week}", weeks=weeks)
        records = {t.team_key: t.standing.record for t in yahoo.teams() if t.standing}
        theirs = yahoo.roster(found.opponent.team_key) if roster is not None else None
        scored = None if league.by_points else yahoo.settings().categories
        return nba_week.board(found, weeks, records, roster, theirs, scored)

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
        builder = PlayerContextBuilder(self.form, self.games, weights)
        roster_lines = builder.build_player_lines(
            rostered,
            start,
            end,
            remaining_games=remaining_games,
            projections=projections,
            returns=returns,
            splits=splits,
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
        )

        schedule_context = prompt.schedule(week, remaining_games, projected=projections is not None)
        stuck = nba_week.off_il(rostered)
        trans_context = prompt.transactions(used_adds, limit) + "".join(f"\n- {item.reason}" for item in stuck)
        return CompetitionContext(
            prompt=prompt.scout(
                roster="".join(roster_lines.values()),
                week=week,
                free_agents="".join(fa_lines.values()),
                schedule_context=schedule_context,
                trans_context=trans_context,
                adds_left=max(0, limit - used_adds),
                weights=weights,
            ),
            situation=prompt.matchup(week, weights),
            constraints=trans_context,
            extra=schedule_context,
            roster_lines=roster_lines,
            candidate_lines=fa_lines,
            headline=nba_week.adds(used_adds, limit),
            tasks=stuck,
            listed=frozenset(p.name for p in rostered if p.player_key in {item.player_id for item in stuck}),
            # A kept judgment's add of somebody another manager has since claimed is no move at all.
            movable=frozenset(p.name for p in (*rostered, *free_agents)),
        )

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

    # ── players and teams ───────────────────────────────────────────

    def roster(self, league_id: str = "") -> list[PlayerCard]:
        """The user's roster, with recent form where Sleeper has it."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        return self._cards(yahoo.roster(yahoo.get_user_team().team_key), self._weights(league, yahoo))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the league, yours first."""
        refs = [
            TeamRef(
                team_id=team.team_key,
                name=team.name,
                detail=team.standing.record if team.standing else "",
                url=nba_league.team_url(team.team_key),
                is_mine=team.is_mine,
            )
            for team in self._yahoo(league_id).teams()
        ]
        return sorted([r for r in refs if r.team_id], key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's roster, in the same columns as your own."""
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        if not any(t.team_key == team_id for t in yahoo.teams()):
            raise TeamNotFoundError(team_id)
        return self._cards(yahoo.roster(team_id), self._weights(league, yahoo))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The best players nobody in the league holds.

        Ordered by Yahoo's own ranks rather than by a category — season and
        last week in turn (`_wire`): a wire browsed one stat at a time is the
        scout's job, and this is the list you read when you just want to see
        who is out there.
        """
        paging.view(query, ())  # no other lists: one asked for is refused, not ignored
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        ranked = self._cards(_wire(yahoo), self._weights(league, yahoo), wire=True)
        return paging.page(ranked, query)

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
        self, players: list[YahooPlayer], weights: Mapping[str, float] | None, wire: bool = False
    ) -> list[PlayerCard]:
        """One table shape for every list of players this sport shows (`views.cards`); the wire's with teammate splits."""
        reports = self._reports()
        splits = self._splits(players, weights, reports) if wire else None
        return views.cards(players, self.form.get_player_stats, self._returns(players, reports), weights, splits)

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """Any player in the league — yours, a rival's or a free agent — with their recent line where Sleeper has it.

        A points league heads it with his fantasy points per game; a category league with his points.
        """
        league = self._league(league_id)
        yahoo = self._yahoo_for(league)
        found = yahoo.players([player_id])
        if not found:
            raise PlayerNotFoundError([player_id])
        player = found[0]

        stats = self.form.get_player_stats(player.name)
        weights = self._weights(league, yahoo)
        reports = self._reports()
        return views.detail(
            player,
            stats,
            weights,
            self._injuries([player], reports).stats(player_id),
            self._splits([player], weights, reports)(player),
        )

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


def _wire(yahoo: YahooSource) -> list[YahooPlayer]:
    """The available players under every ranking in `WIRE_DEPTH`, taken from each in turn, each player once.

    Interleaved rather than one list after the other, so the week's risers sit
    beside the season's best instead of below three hundred of them.
    """
    rankings = list(yahoo.fetch_available(WIRE_DEPTH).values())
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
