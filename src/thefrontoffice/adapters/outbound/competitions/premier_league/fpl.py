"""Fantasy Premier League on the official game.

The only sport here whose league platform is also its stats provider: the same
payload that lists a squad carries expected goals, ownership and the game's own
next-gameweek projection, so there is no second platform to join names against.

What binds a decision is money and a transfer allowance rather than a waiver
budget or a set of lineup slots, and the highest-leverage call of the week is
the captaincy — which is why the report leads with it.

There is no trade path. FPL managers do not exchange players with each other;
the equivalent action is a transfer against the market, which the scouting
report already recommends.

How a gameweek is gathered lives in `week.py`, how a player reads in
`views.py`, the season and the table in `league.py`, the model's text in
`prompt.py` and the rules of the game in `rules.py`; the gameweeks ahead in
`outlook.py`, a head-to-head tie as the simulation reads it in `forecast.py`,
and a player's news in `news.py`. This is the port.
"""

import logging
from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.premier_league import forecast, league, outlook, prompt, views
from thefrontoffice.adapters.outbound.competitions.premier_league import week as fpl_week
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    Roster,
    fixtures_by_club,
    plays,
    purchase_prices,
    selling_price,
)
from thefrontoffice.adapters.outbound.competitions.seeds import seed
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import MiniLeague, as_millions
from thefrontoffice.domain.errors import PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import (
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
    TeamRef,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Where the moves are actually made.
LEAGUE_URL = "https://fantasy.premierleague.com/leagues/{league_id}/standings/{kind}"
ENTRY_URL = "https://fantasy.premierleague.com/entry/{entry_id}/event/{gameweek}"


class FPLProvider:
    """CompetitionProvider for the official Fantasy Premier League game.

    Named for neither a separate platform nor a separate sport because there is
    only one of each: the game is both.
    """

    def __init__(self, entry_id: int, *, client: FPLSource):
        """Every collaborator from bootstrap, which is the one place a real client is built.

        The entry id is required: whether one is set, and what to set when it
        is not, is the registry entry's to say before this is ever built.
        """
        self.entry_id = entry_id
        self.client = client

    # ── leagues ─────────────────────────────────────────────────────

    def list_leagues(self) -> list[LeagueRef]:
        """The manager's invitational mini-leagues.

        The game's own leagues — Overall, your country, one per gameweek — are
        filtered out. Everyone is in them, nobody competes in them, and a report
        per gameweek league would mean 38 identical reports.

        Falls back to the overall standing when the manager has joined no
        private league, so a brand-new account still has something to scout.
        """
        entry = self.client.get_entry(self.entry_id)
        private = [lg for lg in entry.leagues if lg.is_private]
        if not private:
            return [
                LeagueRef(
                    league_id=str(entry.entry_id),
                    name=entry.name,
                    detail=f"overall rank {entry.overall_rank:,} · {entry.overall_points} pts",
                    url=self._entry_url(entry.entry_id),
                )
            ]
        return [
            LeagueRef(
                league_id=str(lg.id),
                name=lg.name,
                detail=f"{league.standing(lg)} · {entry.name}",
                url=self._league_url(lg),
            )
            for lg in private
        ]

    def _entry_url(self, entry_id: int) -> str:
        """A manager's points page on FPL's own site, at the latest gameweek with picks to show."""
        current = self.client.current_gameweek()
        return ENTRY_URL.format(entry_id=entry_id, gameweek=current.id if current else 1)

    @staticmethod
    def _league_url(league: MiniLeague) -> str:
        """The mini-league on FPL's own site.

        The two formats are different pages, so the suffix is not cosmetic —
        a head-to-head league opened as a classic one shows a table it does
        not play by.
        """
        return LEAGUE_URL.format(league_id=league.id, kind="h" if league.is_h2h else "c")

    def _find_league(self, league_id: str, entry_id: int) -> MiniLeague | None:
        return league.league_of(self.client.get_entry(entry_id), league_id)

    # ── squads and players ──────────────────────────────────────────

    def _roster(self, entry_id: int) -> Roster:
        """A manager's fifteen as last picked: the latest gameweek with published picks."""
        return fpl_week.squad_of(self.client, entry_id, fpl_week.picked(self.client).id)

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, grouped the way a manager actually weighs them (`views.detail`)."""
        catalog = self.client.get_players()
        player = catalog.get(int(player_id)) if player_id.isdigit() else None
        if player is None:
            raise PlayerNotFoundError([player_id])
        return views.detail(self.client, player)

    def search_players(self, league_id: str, text: str, limit: int = 10) -> list[PlayerRef]:
        """Anyone in the game whose name holds `text`, the most owned first.

        The whole catalog is already in hand — every player rides on the one
        bootstrap payload — so finding one costs no request. FPL has no owner to
        name: any number of managers can hold the same player.
        """
        wanted = normalize_name(text)
        if len(wanted) < 2:
            return []
        found = [
            p
            for p in self.client.get_players().values()
            if wanted in normalize_name(p.full_name) or wanted in normalize_name(p.name)
        ]
        found.sort(key=lambda p: (-p.selected_by, -p.total_points))
        return [
            PlayerRef(
                player_id=str(p.id),
                name=p.full_name or p.name,
                detail=f"{p.position} · {p.team} · {as_millions(p.cost)}",
            )
            for p in found[:limit]
        ]

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The squad in full, with the season numbers a week view leaves out."""
        return views.squad_cards(self._roster(self.entry_id))

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the mini-league, yours first.

        The table is the membership list — FPL has no separate one. The
        overall standing a manager with no private league is offered is not a
        league with a table, so it has no teams to browse.
        """
        entry_id = self.entry_id
        mini_league = self._find_league(league_id, entry_id)
        if mini_league is None:
            return []
        refs = [
            TeamRef(
                team_id=str(row.entry),
                name=row.entry_name,
                detail=row.manager,
                url=self._entry_url(row.entry),
                is_mine=row.entry == entry_id,
            )
            for row in self.client.get_standings(mini_league.id, mini_league.is_h2h)
        ]
        return sorted(refs, key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's squad, in the same columns as your own."""
        if not team_id.isdigit():
            raise TeamNotFoundError(team_id)
        return views.squad_cards(self._roster(int(team_id)))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The transfer market: everyone you do not already own who can play.

        FPL has no waiver wire — every player is buyable at a price — so the
        question is not who is free but who is worth the money. Ranked on the
        game's own projection, which is what a transfer is decided on.
        """
        paging.view(query, ())  # no other lists: one asked for is refused, not ignored
        squad = self.client.get_squad(self.entry_id, fpl_week.picked(self.client).id)
        owned = {pick.element for pick in squad.picks}

        market = [p for p in self.client.get_players().values() if p.id not in owned and plays(p)]
        market.sort(key=lambda p: (-p.expected_points, -p.form))
        return paging.page([views.market_card(p) for p in market], query)

    # ── gameweeks ───────────────────────────────────────────────────

    def summary(self, league_id: str) -> Summary:
        """The gameweek in focus: both squads, the fixtures, the swaps (`week.summary`)."""
        return fpl_week.summary(self.client, self.entry_id, league_id)

    def week_of(self, league_id: str, week: int) -> Summary:
        """Any other gameweek, played or to come (`week.browsed`).

        Raises:
            NotFoundError: the season has no such gameweek.
        """
        return fpl_week.browsed(self.client, self.entry_id, league_id, week)

    def games_of(self, league_id: str, week: int) -> Slate:
        """The real matches of any gameweek, each with its score once it has kicked off, its blanks,
        and the players each side has in it.

        Raises:
            NotFoundError: the season has no such gameweek.
        """
        fpl_week.numbered(self.client, week)
        mine, theirs = self._match_rosters(league_id, week)
        games = league.matches(self.client, week, mine=mine, theirs=theirs)
        return Slate(games=games, byes=league.blanks(self.client, games))

    def _match_rosters(self, league_id: str, week: int) -> tuple[Roster | None, Roster | None]:
        """Your squad and your opponent's for a gameweek's matches; None for either that will not load.

        Enrichment, not a dependency: before the season there are no picks at
        all, and the matches stand without names in them.
        """
        current = self.client.current_gameweek()
        if current is None:
            return None, None
        squad_week = min(week, current.id)
        try:
            mine = fpl_week.squad_of(self.client, self.entry_id, squad_week)
        except FPLAPIError as e:
            logger.warning(f"Continuing without your players in the matches: {e}")
            return None, None
        tie = fpl_week.tie(self.client, league_id, self.entry_id, week)
        return mine, fpl_week.tie_roster(self.client, tie, squad_week)

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, the league's transfers, and the real matches behind the gameweek."""
        entry_id = self.entry_id
        # Marked on the gameweek in focus, so the season table and the week view
        # agree about which row is "now".
        playing = fpl_week.focus(self.client)
        mine, theirs = self._match_rosters(league_id, playing.id)
        schedule = league.build(
            self.client, self._find_league(league_id, entry_id), entry_id, playing.id, mine=mine, theirs=theirs
        )
        # The season's figures head the league view, which is the question they answer.
        headline = prompt.season_headline(self.client.get_entry(entry_id), league_id)
        return schedule.model_copy(update={"headline": headline})

    def weeks_ahead(self, league_id: str, team_id: str = "") -> Outlook:
        """A squad's next gameweeks as fixtures (`outlook`), yours where `team_id` is empty.

        From the gameweek still open to the next deadline; none once the season has run out.

        Raises:
            TeamNotFoundError: `team_id` is no FPL entry.
        """
        if team_id and not team_id.isdigit():
            raise TeamNotFoundError(team_id)
        squad = self._roster(int(team_id) if team_id else self.entry_id)
        gameweeks = self.client.get_gameweeks()
        upcoming = self.client.upcoming_gameweek()
        last = max((g.id for g in gameweeks), default=upcoming.id)
        # The last gameweek stays "upcoming" once the season is over: nothing is ahead then.
        weeks = [] if all(g.finished for g in gameweeks) else outlook.weeks_from(upcoming.id, last)
        return outlook.outlook(squad, self.client.get_season_fixtures(), weeks)

    # ── the tie, simulated ──────────────────────────────────────────

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        """The gameweek in focus's head-to-head tie, ready to simulate (`forecast`).

        None in a classic league, which has no tie to win, in a gameweek without
        one, and for `candidates`: the market is not priced, since a transfer
        is weighed over the weeks ahead rather than one tie.
        """
        if candidates:
            return None
        mini_league = self._find_league(league_id, self.entry_id)
        if mini_league is None or not mini_league.is_h2h:
            return None
        gameweek = fpl_week.focus(self.client)
        found = fpl_week.tie(self.client, league_id, self.entry_id, gameweek.id)
        if found is None:
            return None
        latest = fpl_week.picked(self.client).id
        squad_week = min(gameweek.id, latest)
        mine = fpl_week.squad_of(self.client, self.entry_id, squad_week)
        theirs = fpl_week.squad_of(self.client, found.opponent_entry, squad_week)
        to_come = gameweek.id > latest
        logs = self.client.get_player_summaries(forecast.everyone(mine, theirs))
        week = forecast.Gameweek(
            fixtures=fixtures_by_club(
                self.client.get_fixtures(gameweek.id), (p.team for p in (*mine.players, *theirs.players))
            ),
            games={pid: summary.games for pid, summary in logs.values.items()},
            live={} if to_come else fpl_week.live_points(self.client, gameweek.id),
            recent_from=forecast.recent_from(gameweek.id),
            to_come=to_come,
        )
        return forecast.matchup(mine, theirs, week, seed(league_id, self.entry_id, gameweek.id))

    def played_weeks(self, league_id: str) -> list[int]:
        """None: a gameweek is not yet rebuilt as it stood before its deadline, so it is not backtested."""
        return []

    def played_matchups(
        self, league_id: str, week: int, settings: Mapping[str, float] | None = None
    ) -> list[PlayedMatchup]:
        """None, for the reason `played_weeks` names none."""
        return []

    # ── context ─────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather the gameweek, then render it as the text a model reads.

        The squad is the one last fielded; the projections, fixtures and
        allowance are for the gameweek still open, which is the one advice
        can change.
        """
        entry_id = self.entry_id
        upcoming = self.client.upcoming_gameweek()
        mine = self._roster(entry_id)
        return prompt.build(
            league_id=league_id,
            entry=self.client.get_entry(entry_id),
            upcoming=upcoming,
            roster=mine,
            catalog=self.client.get_players(),
            allowance=fpl_week.allowance(self.client, entry_id, upcoming.id),
            fixtures=fixtures_by_club(self.client.get_fixtures(upcoming.id), (p.team for p in mine.players)),
            selling=self._selling_prices(mine),
        )

    def _selling_prices(self, mine: Roster) -> dict[int, int]:
        """What the game would pay for each of the squad, by element id: half of any rise since purchase is kept back.

        Degrades to current prices — the optimistic case — where the transfer
        history will not load, rather than failing the report over it.
        """
        try:
            transfers = self.client.get_transfers(self.entry_id)
            chips = self.client.get_chips_played(self.entry_id)
        except FPLAPIError as e:
            logger.warning(f"Pricing sales at current prices: {e}")
            return {}
        bought = purchase_prices(mine.players, transfers, chips)
        return {p.id: selling_price(bought[p.id], p.cost) for p in mine.players}
