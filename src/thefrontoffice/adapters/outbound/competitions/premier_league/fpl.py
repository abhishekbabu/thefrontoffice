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
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.premier_league import league, prompt
from thefrontoffice.adapters.outbound.competitions.premier_league.squad import (
    Lineup,
    Roster,
    best_lineup,
    effective_points,
    fixtures_by_club,
    free_transfers,
    lineup_changes,
    plays,
    points_of,
    points_with_captain,
    projected_of,
    purchase_prices,
    roster,
    selling_price,
)
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Chip,
    Club,
    Gameweek,
    H2HMatch,
    LiveStat,
    MiniLeague,
    Opponent,
    PastSeason,
    Pick,
    Player,
    as_millions,
)
from thefrontoffice.domain.errors import NotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    CompetitionContext,
    LeagueSchedule,
    PlayerCard,
    PlayerDetail,
    PlayerPage,
    PlayerQuery,
    Side,
    Slate,
    Spot,
    SpotScoring,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
    Summary,
    Swap,
    TeamRef,
    Tone,
    WeekRange,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Where the moves are actually made.
LEAGUE_URL = "https://fantasy.premierleague.com/leagues/{league_id}/standings/{kind}"
ENTRY_URL = "https://fantasy.premierleague.com/entry/{entry_id}/event/{gameweek}"

# Keyed by Opta's code, not the element id. Public, keyless, and already
# alongside every other asset the site serves.
PORTRAIT_URL = "https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png"
# Filed under the club's media `code`, not its bootstrap `id`.
BADGE_URL = "https://resources.premierleague.com/premierleague/badges/70/t{code}.png"

# Two back plus the one in progress is three columns, which fits a drawer and
# is as far as a player's form is still the same player.
PAST_SEASON_LIMIT = 2

# What counts as a return and what counts as nothing, on FPL's own scale: two
# points is an appearance and no more, and a double-figure haul is a week made.
HAUL = 10
BLANK = 2


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

    # ── squad ───────────────────────────────────────────────────────

    def _gameweek(self) -> Gameweek:
        """The latest gameweek whose picks are published: FPL's own `is_current`, which moves only at a deadline.

        Picks appear only once a deadline passes, so before the season opens
        no gameweek is current, there is nothing to read, and no squad view
        can be built.
        """
        current = self.client.current_gameweek()
        if current is None:
            raise FPLAPIError("Season not started; no squad yet.")
        return current

    def _focus(self) -> Gameweek:
        """The gameweek the week view is about: the one being played, or once it is over, the next.

        FPL keeps a gameweek `is_current` until the next deadline, days after its
        last match — so a finished one hands over to the gameweek still open,
        whose deadline is the next thing anybody can act on. Before the season the
        first gameweek is next; after it, the last stays.
        """
        current = self.client.current_gameweek()
        if current is not None and not current.finished:
            return current
        upcoming = self.client.upcoming_gameweek()
        if current is None or upcoming.id > current.id:
            return upcoming
        return current

    def _entry_url(self, entry_id: int) -> str:
        """A manager's points page on FPL's own site, at the latest gameweek with picks to show."""
        current = self.client.current_gameweek()
        return ENTRY_URL.format(entry_id=entry_id, gameweek=current.id if current else 1)

    def _roster(self, entry_id: int, gameweek: int) -> Roster:
        """A manager's fifteen as they set them for `gameweek`."""
        return roster(self.client.get_squad(entry_id, gameweek), self.client.get_players())

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, grouped the way a manager actually weighs them.

        Everything here comes from the catalog every other call already reads,
        so depth costs nothing: Opta's expected numbers, the season return, the
        set-piece duty that separates a good price from a bad one, and the
        market moving under the price.
        """
        catalog = self.client.get_players()
        player = catalog.get(int(player_id)) if player_id.isdigit() else None
        if player is None:
            raise PlayerNotFoundError([player_id])

        upcoming = self.client.upcoming_gameweek()
        club = self._club(player.team)

        return PlayerDetail(
            player_id=str(player.id),
            name=player.full_name or player.name,
            position=player.position,
            team=player.team,
            team_name=club.name if club else player.team,
            team_logo_url=BADGE_URL.format(code=club.code) if club and club.code else "",
            headline=f"{player.expected_points:.1f}",
            headline_label=f"xPts for {upcoming.name}",
            note=player.news,
            image_url=PORTRAIT_URL.format(code=player.code) if player.code else "",
            tone=_tone(player),
            groups=[
                StatGroup(
                    title="This week",
                    stats=[
                        Stat(label="Fixture", value=self._fixture_line(player, upcoming.id)),
                        Stat(label="Expected", value=f"{player.expected_points:.1f} xPts"),
                        Stat(label="Form", value=f"{player.form:.1f}"),
                        Stat(
                            label="Availability",
                            value=player.availability or "fit",
                            tone="warning" if player.availability else "good",
                        ),
                    ],
                ),
                StatGroup(
                    title="Underlying",
                    stats=[
                        Stat(label="xG", value=f"{player.expected_goals:.2f}"),
                        Stat(label="xA", value=f"{player.expected_assists:.2f}"),
                        Stat(label="xGI", value=f"{player.expected_goal_involvements:.2f}"),
                        Stat(label="xGC", value=f"{player.expected_goals_conceded:.2f}"),
                        Stat(label="ICT", value=f"{player.ict_index:.1f}"),
                    ],
                ),
                StatGroup(title="Set pieces", stats=self._set_pieces(player)),
                StatGroup(
                    title="Market",
                    stats=[
                        Stat(label="Price", value=as_millions(player.cost)),
                        Stat(
                            label="This week",
                            value=f"{'+' if player.price_change > 0 else ''}{player.price_change / 10:.1f}m",
                            tone="good" if player.price_change > 0 else "neutral",
                        ),
                        Stat(label="Owned by", value=f"{player.selected_by:.1f}%"),
                        Stat(label="Transfers in", value=f"{player.transfers_in:,}"),
                        Stat(label="Transfers out", value=f"{player.transfers_out:,}"),
                    ],
                ),
            ],
            tables=[table] if (table := self._season_table(player)) else [],
        )

    def _clubs(self) -> dict[str, Club]:
        """Every club in full, keyed by the abbreviation a player carries.

        Read off the same bootstrap as everything else, so it costs no request.
        Degrades to nothing rather than failing a page: a drawer that says
        "TOT" is worse than one that says "Spurs" and no worse than before.
        """
        try:
            return self.client.get_clubs()
        except FPLAPIError as e:
            logger.warning(f"Continuing without club names: {e}")
            return {}

    def _club(self, short_name: str) -> Club | None:
        return self._clubs().get(short_name)

    def _season_table(self, player: Player) -> StatTable | None:
        """This season beside the two before it, read across rather than down.

        The catalog carries only the season in progress, which in August is a
        single gameweek — so a page meant to justify a £15m striker shows one
        match, and the question anybody actually has is whether he did it last
        year. Stacked groups make you hold last year's goals in your head while
        scrolling to this year's; a row puts them side by side.

        Costs one request, made only when somebody opens a player, and degrades
        to the current season alone rather than failing: a promoted club's
        signing has no FPL history at all.
        """
        try:
            past = self.client.get_past_seasons(player.id)
        except FPLAPIError as e:
            logger.warning(f"Skipping past seasons for {player.name}: {e}")
            past = []

        seasons = list(reversed(past[-PAST_SEASON_LIMIT:]))
        columns = [self._season_label(seasons)] + [s.season for s in seasons]

        # A season nobody has kicked a ball in has no answers, and a column of
        # noughts claims it does.
        started = self._season_started()
        keeper_or_defender = player.position in ("GKP", "DEF")

        def row(label: str, current: str, of_past: Callable[[PastSeason], str], tone: Tone = "neutral") -> StatRow:
            return StatRow(
                label=label,
                values=[current if started else NOT_APPLICABLE] + [of_past(s) for s in seasons],
                tone=tone,
            )

        rows = [
            row("Points", str(player.total_points), lambda s: str(s.total_points)),
            row("Per start", f"{player.points_per_game:.1f}", lambda s: f"{s.points_per_game:.1f}"),
            row("Starts", str(player.starts), lambda s: str(s.starts)),
            row("Minutes", f"{player.minutes:,}", lambda s: f"{s.minutes:,}"),
            row("Goals", str(player.goals), lambda s: str(s.goals)),
            row("Assists", str(player.assists), lambda s: str(s.assists)),
            *(
                [
                    row("Clean sheets", str(player.clean_sheets), lambda s: str(s.clean_sheets)),
                    row("Conceded", str(player.goals_conceded), lambda s: str(s.goals_conceded)),
                ]
                if keeper_or_defender
                else []
            ),
            *([row("Saves", str(player.saves), lambda s: str(s.saves))] if player.position == "GKP" else []),
            row("Bonus", str(player.bonus), lambda s: str(s.bonus)),
            row("xG", f"{player.expected_goals:.2f}", lambda s: f"{s.expected_goals:.2f}"),
            row("xA", f"{player.expected_assists:.2f}", lambda s: f"{s.expected_assists:.2f}"),
            # The market's own verdict on a season: what the price did over it.
            StatRow(
                label="Price",
                values=[as_millions(player.cost)]
                + [f"{as_millions(s.start_cost)} → {as_millions(s.end_cost)}" for s in seasons],
            ),
        ]
        return StatTable(title="By season", columns=columns, rows=rows)

    def _season_started(self) -> bool:
        """Whether this season has produced anything to report yet.

        A gameweek in progress is not a gameweek with totals in it — the
        catalog is still all noughts until one finishes.
        """
        return any(gw.finished for gw in self.client.get_gameweeks())

    @staticmethod
    def _season_label(past: list[PastSeason]) -> str:
        """This season's name, which FPL only ever states about finished ones.

        Derived from the most recent finished season rather than from a clock:
        a football season spans two calendar years and the changeover is not on
        a date anybody could hardcode.
        """
        if not past:
            return "This season"
        try:
            start, end = past[0].season.split("/")
            return f"{int(start) + 1}/{int(end) + 1:02d}"
        except ValueError, IndexError:
            return "This season"

    def _fixture_line(self, player: Player, gameweek: int) -> str:
        """The drawer's fixture, with the opponent named the way it is said."""
        clubs = self._clubs()

        def in_full(short_name: str) -> str:
            club = clubs.get(short_name)
            return club.name if club else short_name

        opponents = fixtures_by_club(self.client.get_fixtures(gameweek), [player.team])[player.team]
        return _fixture_text(opponents, in_full)

    @staticmethod
    def _set_pieces(player: Player) -> list[Stat]:
        """Whose duty it is, which is most of the gap between two similar prices.

        Only listed when they are on them: "not on penalties" for every player
        who is not would be nineteen rows of nothing.
        """
        duties = [
            ("Penalties", player.penalties_order),
            ("Corners", player.corners_order),
            ("Free kicks", player.freekicks_order),
        ]
        taken = [
            Stat(label=name, value=f"#{order}", tone="good" if order == 1 else "neutral")
            for name, order in duties
            if order is not None
        ]
        return taken or [Stat(label="Set pieces", value="none")]

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The squad in full, with the season numbers a week view leaves out."""
        return self._squad_cards(self.entry_id)

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
        return self._squad_cards(int(team_id))

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        """The transfer market: everyone you do not already own who can play.

        FPL has no waiver wire — every player is buyable at a price — so the
        question is not who is free but who is worth the money. Ranked on the
        game's own projection, which is what a transfer is decided on.
        """
        paging.view(query, ())  # no other lists: one asked for is refused, not ignored
        squad = self.client.get_squad(self.entry_id, self._gameweek().id)
        owned = {pick.element for pick in squad.picks}

        market = [p for p in self.client.get_players().values() if p.id not in owned and plays(p)]
        market.sort(key=lambda p: (-p.expected_points, -p.form))
        return paging.page([self._market_card(p) for p in market], query)

    def _squad_cards(self, entry_id: int) -> list[PlayerCard]:
        """One table shape for any manager's fifteen."""
        return [
            PlayerCard(
                player_id=str(player.id),
                ruled_out=not plays(player),
                columns={
                    **self._market_columns(player),
                    SLOT_COLUMN: ("C" if pick.is_captain else "XI") if pick.is_starting else "BN",
                },
                values=self._market_values(player),
            )
            for pick, player in self._roster(entry_id, self._gameweek().id).picked
        ]

    def _market_card(self, player: Player) -> PlayerCard:
        return PlayerCard(
            player_id=str(player.id),
            ruled_out=not plays(player),
            columns=self._market_columns(player),
            values=self._market_values(player),
        )

    @staticmethod
    def _market_values(player: Player) -> dict[str, float]:
        """The numbers behind the formatted columns, so any of them can be
        sorted on. "£15.5m" sorted as text sits below "£9.0m"."""
        return {
            "Price": player.cost / 10,
            "xPts": player.expected_points,
            "Form": player.form,
            "Points": float(player.total_points),
            "xGI": player.expected_goal_involvements,
            "Owned": player.selected_by,
        }

    @staticmethod
    def _market_columns(player: Player) -> dict[str, str]:
        return {
            PLAYER_COLUMN: player.name,
            POSITION_COLUMN: player.position,
            "Club": player.team,
            "Price": as_millions(player.cost),
            "xPts": f"{player.expected_points:.1f}",
            "Form": f"{player.form:.1f}",
            "Points": str(player.total_points),
            "xGI": f"{player.expected_goal_involvements:.2f}",
            "Owned": f"{player.selected_by:.1f}%",
            STATUS_COLUMN: player.availability,
        }

    def summary(self, league_id: str) -> Summary:
        """The gameweek in focus: both squads, the fixtures, the swaps.

        The one being played while its matches are; once it is over, the one whose
        deadline is next, with the squad as last picked against its fixtures and
        FPL's projection for it. Reaches for the squad, the history and the tie —
        everything the week is made of — and stops short of the transfer market,
        which is the expensive half of a report and answers a different question.
        """
        entry_id = self.entry_id
        focus = self._focus()
        week = self._week(league_id, focus, self._gameweek().id)
        best = best_lineup(week.mine.players)
        upcoming = self.client.upcoming_gameweek()

        return Summary(
            headline=prompt.headline(
                week.mine.squad,
                # Keyed to the next deadline, because that is the one an
                # allowance can still be spent against.
                self._allowance(upcoming.id),
                best,
                points_with_captain(week.mine.starters, week.mine.captain),
                upcoming,
            ),
            mine=week.mine_side,
            opponent=week.opponent,
            swaps=_swaps(week.mine, best),
            fixtures=self._warnings(week.fixtures),
            boosts=self._chips(entry_id, focus.id),
            window=week.window,
            weeks=self._range(focus.id, focus.id),
        )

    # ── other gameweeks ─────────────────────────────────────────────

    def week_of(self, league_id: str, week: int) -> Summary:
        """Any other gameweek: one played with the fifteen picked for it and what each scored, one to come
        with the squad as it stands against that gameweek's fixtures.

        A gameweek to come is projected only where FPL has: the next one, by
        `ep_next`. Further out the rows read "—", since FPL projects nothing there.

        Raises:
            NotFoundError: the season has no such gameweek.
        """
        gameweek = self._gameweek_numbered(week)
        shown = self._week(league_id, gameweek, self._gameweek().id)
        return Summary(
            headline=_browsed_headline(gameweek, shown),
            mine=shown.mine_side,
            opponent=shown.opponent,
            window=shown.window,
            weeks=self._range(week, self._focus().id),
        )

    def _week(self, league_id: str, gameweek: Gameweek, picked: int) -> _Week:
        """Both sides of one gameweek, as far as it has got: played, under way, or to come.

        `picked` is the latest gameweek with published picks. One before it is
        over; one after it is shown with the squads as last picked, since nobody's
        picks for it are published until its deadline passes.
        """
        entry_id = self.entry_id
        to_come = gameweek.id > picked
        squad_week = picked if to_come else gameweek.id
        mine = self._roster(entry_id, squad_week)
        week_fixtures = self.client.get_fixtures(gameweek.id)
        live = {} if to_come else self._live_points(gameweek.id)
        projected = projected_of if gameweek.id == picked else _projected_for(gameweek.id, picked)
        final = not to_come and (
            gameweek.finished
            or gameweek.id < picked
            or (bool(week_fixtures) and all(f.finished for f in week_fixtures))
        )
        # Minutes stand in for a kickoff where the fixtures were read before it.
        begun = final or (
            not to_come and (any(f.started for f in week_fixtures) or any(s.has_played for s in live.values()))
        )
        tie = self._tie(league_id, entry_id, gameweek.id)
        score = league.tie_score(tie, begun)
        # Your own rows are summed while the week is under way, since the live feed
        # moves faster than any total; once it is over, the game's own total stands.
        if not final:
            scored: int | None = mine.scored(live) if begun else None
        elif score is not None:
            scored = score[0]
        else:
            scored = self._points_in(entry_id, gameweek.id)

        fixtures = fixtures_by_club(week_fixtures, (p.team for p in mine.players))
        detail = f"GW{gameweek.id}" if squad_week == gameweek.id else f"GW{squad_week} picks"
        mine_side = Side(
            name=self.client.get_entry(entry_id).name,
            detail=detail,
            points=_side_points(scored, mine, fixtures, projected),
            lineup=self._spots(mine, starting=True, fixtures=fixtures, live=live, projected=projected),
            bench=self._spots(mine, starting=False, fixtures=fixtures, live=live, projected=projected),
        )
        opponent = None
        if tie is not None and (theirs := self._tie_roster(tie, squad_week)) is not None:
            their_fixtures = fixtures_by_club(week_fixtures, (p.team for p in theirs.players))
            opponent = Side(
                name=tie.opponent_name,
                detail=detail,
                # The game's own total rather than a sum of the rows: it already
                # accounts for auto-subs, which a squad list cannot show.
                points=_side_points(score[1] if score else None, theirs, their_fixtures, projected),
                lineup=self._spots(theirs, starting=True, fixtures=their_fixtures, live=live, projected=projected),
                bench=self._spots(theirs, starting=False, fixtures=their_fixtures, live=live, projected=projected),
            )
        return _Week(
            mine=mine,
            mine_side=mine_side,
            opponent=opponent,
            fixtures=fixtures,
            score=score,
            scored=scored,
            to_come=to_come,
            final=final,
            window=_window(gameweek, final=final, begun=begun),
        )

    def games_of(self, league_id: str, week: int) -> Slate:
        """The real matches of any gameweek, each with its score once it has kicked off, its blanks,
        and the players each side has in it.

        Raises:
            NotFoundError: the season has no such gameweek.
        """
        self._gameweek_numbered(week)
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
            mine = self._roster(self.entry_id, squad_week)
        except FPLAPIError as e:
            logger.warning(f"Continuing without your players in the matches: {e}")
            return None, None
        return mine, self._tie_roster(self._tie(league_id, self.entry_id, week), squad_week)

    def _range(self, week: int, current: int) -> WeekRange:
        return WeekRange(week=week, current=current, first=1, last=max(len(self.client.get_gameweeks()), current))

    def _gameweek_numbered(self, week: int) -> Gameweek:
        gameweek = next((g for g in self.client.get_gameweeks() if g.id == week), None)
        if gameweek is None:
            raise NotFoundError(f"gameweek {week} of the season")
        return gameweek

    def _tie(self, league_id: str, entry_id: int, week: int) -> H2HMatch | None:
        """Your head-to-head tie that gameweek; None in a classic league, or where it will not load.

        Only head-to-head leagues pair managers; a classic league is a table,
        so there is no opponent to show and saying so beats inventing one.
        """
        mini_league = self._find_league(league_id, entry_id)
        if mini_league is None or not mini_league.is_h2h:
            return None
        try:
            return self.client.get_h2h_match(mini_league.id, entry_id, week)
        except FPLAPIError as e:
            # The rest of the page is about your own squad and still stands.
            logger.warning(f"Skipping the head-to-head opponent: {e}")
            return None

    def _tie_roster(self, tie: H2HMatch | None, week: int) -> Roster | None:
        """The squad your opponent picked for `week`; None without a tie, or where it will not load."""
        if tie is None:
            return None
        try:
            return self._roster(tie.opponent_entry, week)
        except FPLAPIError as e:
            logger.warning(f"Skipping the head-to-head opponent's squad: {e}")
            return None

    def _points_in(self, entry_id: int, week: int) -> int | None:
        """What FPL credited the gameweek with, auto-subs and all; None where its history will not say."""
        try:
            history = self.client.get_history(entry_id)
        except FPLAPIError as e:
            logger.warning(f"Continuing without gameweek {week}'s points: {e}")
            return None
        return next((row.points for row in history if row.event == week), None)

    def _chips(self, entry_id: int, gameweek: int) -> StatGroup | None:
        """What is left of the season's chips, and what has become of the rest.

        The game issues a set per half — a Wildcard for GW2-19 and another for
        GW20-38 — and a chip played in one half spends only that half's. So each
        window is tracked on its own, and one row per chip reads the window open
        now: available until it closes, played, or when the next one opens.

        A chip whose windows have all passed is still listed: an unplayed Free
        Hit is a thing that was lost, and a row saying so is worth more than a
        row quietly missing.
        """
        try:
            issued = self.client.get_chips()
            played = self.client.get_chips_played(entry_id)
        except FPLAPIError as e:
            logger.warning(f"Continuing without chips: {e}")
            return None
        if not issued:
            return None

        stats: list[Stat] = []
        closing: list[int] = []
        for name in dict.fromkeys(c.name for c in issued):
            windows = sorted((c for c in issued if c.name == name), key=lambda c: c.start_event)
            spent = {w: next((p.event for p in played if p.name == name and w.covers(p.event)), None) for w in windows}
            stat = _chip_stat(windows, spent, gameweek)
            stats.append(stat)
            now = next((w for w in windows if w.covers(gameweek)), None)
            if stat.tone == "good" and now is not None and now.stop_event < windows[-1].stop_event:
                closing.append(now.stop_event)
        available = sum(stat.tone == "good" for stat in stats)
        note = f"{available} available"
        if closing and (deadline := self._deadline_of(min(closing))):
            note += f" · this half's expire at the GW{min(closing)} deadline, {deadline}"
        return StatGroup(title="Chips", stats=stats, note=note)

    def _deadline_of(self, week: int) -> str:
        gameweek = next((g for g in self.client.get_gameweeks() if g.id == week), None)
        return f"{at_time(gameweek.deadline)} UTC" if gameweek else ""

    def _live_points(self, gameweek: int) -> dict[int, LiveStat]:
        """What the squad has actually scored, or nothing before a ball is kicked.

        Enrichment, not a dependency: a gameweek with no live feed yet falls
        back to projections rather than failing.
        """
        try:
            return self.client.get_live(gameweek)
        except FPLAPIError as e:
            logger.warning(f"Continuing without live points: {e}")
            return {}

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, the league's transfers, and the real matches behind the gameweek."""
        entry_id = self.entry_id
        # Marked on the gameweek in focus, so the season table and the week view
        # agree about which row is "now".
        playing = self._focus()
        mine, theirs = self._match_rosters(league_id, playing.id)
        schedule = league.build(
            self.client, self._find_league(league_id, entry_id), entry_id, playing.id, mine=mine, theirs=theirs
        )
        # The season's figures head the league view, which is the question they answer.
        headline = prompt.season_headline(self.client.get_entry(entry_id), league_id)
        return schedule.model_copy(update={"headline": headline})

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

    def _spots(
        self,
        squad: Roster,
        *,
        starting: bool,
        fixtures: dict[str, list[Opponent]],
        live: dict[int, LiveStat],
        projected: Projected = projected_of,
    ) -> list[Spot]:
        return [
            self._spot(pick, player, fixtures, live, projected)
            for pick, player in squad.picked
            if pick.is_starting == starting
        ]

    def _spot(
        self,
        pick: Pick,
        player: Player,
        fixtures: dict[str, list[Opponent]],
        live: dict[int, LiveStat],
        projected: Projected = projected_of,
    ) -> Spot:
        """One row: what he was projected for this gameweek, and once his match is on, what he has scored.

        The projection is the gameweek's own (`ep_this`), multiplied as his points
        are, so a captain's guess and a captain's score are the same kind of
        number. Once his club has kicked off a nought is a nought, not a match
        still to come. A gameweek FPL has projected nobody for yet reads "—".
        """
        flag = player.availability
        stat = live.get(player.id)
        opponents = fixtures.get(player.team, [])
        scoring = _scoring(opponents, stat)
        points = None if scoring == "projected" else points_of(pick, stat or LiveStat(points=0, minutes=0))
        expected = projected(pick, player)
        return Spot(
            player_id=str(player.id),
            player=player.name,
            mark="C" if pick.is_captain else "VC" if pick.is_vice_captain else "",
            detail=f"{player.position} · {player.team} {_fixture_text(opponents)}" + (f" · {flag}" if flag else ""),
            value=f"{points} pts" if points is not None else f"{expected:.1f} xPts" if expected is not None else "—",
            tone=self._spot_tone(points, flag, blank=not opponents),
            scoring=scoring,
            scored="" if points is None else str(points),
            projection="" if expected is None else f"{expected:.1f}",
        )

    @staticmethod
    def _spot_tone(points: int | None, flag: str, *, blank: bool) -> Tone:
        """A haul is worth seeing, and so is a blank.

        Once somebody has played, the points are what the row is about: a doubt
        about a player who got through ninety minutes is no longer a doubt.
        Until then the availability flag and a missing fixture are the signal.
        """
        if points is None:
            return "warning" if flag or blank else "neutral"
        if points >= HAUL:
            return "good"
        return "warning" if points <= BLANK else "neutral"

    @staticmethod
    def _warnings(fixtures: dict[str, list[Opponent]]) -> list[Stat]:
        """Only what is worth watching, not every fixture.

        Each player row already carries its own opponent and difficulty, so a
        full list of clubs repeats the page back at itself. A blank gameweek
        and a double are the two cases that change what a squad is worth.
        """
        notable = []
        for club, opponents in fixtures.items():
            if not opponents:
                notable.append(Stat(label=club, value="blank gameweek", tone="warning"))
            elif len(opponents) > 1:
                notable.append(Stat(label=club, value=f"double gameweek — {_fixture_text(opponents)}", tone="good"))
        return notable

    # ── context ─────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> CompetitionContext:
        """Gather the gameweek, then render it as the text a model reads.

        The squad is the one last fielded; the projections, fixtures and
        allowance are for the gameweek still open, which is the one advice
        can change.
        """
        entry_id = self.entry_id
        upcoming = self.client.upcoming_gameweek()
        mine = self._roster(entry_id, self._gameweek().id)
        return prompt.build(
            league_id=league_id,
            entry=self.client.get_entry(entry_id),
            upcoming=upcoming,
            roster=mine,
            catalog=self.client.get_players(),
            allowance=self._allowance(upcoming.id),
            fixtures=fixtures_by_club(self.client.get_fixtures(upcoming.id), (p.team for p in mine.players)),
            selling=self._selling_prices(mine),
        )

    def _allowance(self, upcoming: int) -> int:
        """Free transfers going into `upcoming`, from the history and the chips spent.

        A chip list that will not load leaves the allowance unknowable — a
        Wildcard week reads as a week of no transfers — so it falls back to the
        floor of one, which is never wrong in the manager's favor.
        """
        history = self.client.get_history(self.entry_id)
        try:
            chips = self.client.get_chips_played(self.entry_id)
        except FPLAPIError as e:
            logger.warning(f"Counting one free transfer without the chips played: {e}")
            return 1
        return free_transfers(history, upcoming, chips=chips)

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


def _scoring(opponents: list[Opponent], stat: LiveStat | None) -> SpotScoring:
    """Final once every match his club has this gameweek is over, live from the first kickoff.

    Minutes stand in for a kickoff where the fixtures were read before it: a
    player on the pitch is in a match that has started, whatever the fixture
    list last said.
    """
    if opponents and all(o.finished for o in opponents):
        return "final"
    if any(o.started for o in opponents) or (stat is not None and stat.has_played):
        return "live"
    return "projected"


Projected = Callable[[Pick, Player], float | None]
"""What one row is projected for the gameweek shown, multiplied as its points would be; None where FPL says nothing."""


@dataclass(frozen=True)
class _Week:
    """One gameweek's two sides, and how far it has got."""

    mine: Roster
    mine_side: Side
    opponent: Side | None
    fixtures: dict[str, list[Opponent]]
    score: tuple[int, int] | None
    """The tie's score, yours first, once under way; None in a classic league or before kickoff."""
    scored: int | None
    to_come: bool
    final: bool
    window: str


def _side_points(scored: int | None, squad: Roster, fixtures: dict[str, list[Opponent]], projected: Projected) -> str:
    """A side's projection until one of its eleven has kicked off, then what it has scored beside it.

    A gameweek played has its points and no projection, since the one FPL
    carries now is for a later week; one further out than the next has neither.
    """
    figures = [projected(pick, player) for pick, player in squad.picked if pick.is_starting]
    known = [f for f in figures if f is not None]
    projection = f"{sum(known):.1f} proj" if known else ""
    kicked = any(o.started for player in squad.starters for o in fixtures.get(player.team, []))
    if scored is None and not kicked:
        return projection
    return " · ".join(part for part in (f"{scored or 0} pts", projection) if part)


def _swaps(mine: Roster, best: Lineup) -> list[Swap]:
    """Every change from the eleven as set to the best one, the armband last, so together they reach its total.

    The armband is a change like any other: the best total counts its captain
    twice, and moving it is worth the gap between the two captains' projections.
    """
    swaps = [
        Swap(start=change.start.name, out=change.drop.name if change.drop else "", gain=f"{change.gain:+.1f} xPts")
        for change in lineup_changes(mine.starters, best)
    ]
    current, captain = mine.captain, best.captain
    if current is not None and captain is not None and captain.id != current.id:
        gain = round(effective_points(captain) - effective_points(current), 2)
        if gain > 0:
            swaps.append(Swap(start=f"Captain {captain.name}", out=current.name, gain=f"{gain:+.1f} xPts"))
    return swaps


def _projected_for(week: int, current: int) -> Projected:
    """The projection a browsed gameweek has: `ep_next` for the next one alone, and none before or after it.

    A gameweek played has its points, and a projection beside them would be
    the current week's, not the one it was played on.
    """
    if week != current + 1:
        return lambda pick, player: None
    return lambda pick, player: player.expected_points * max(pick.multiplier, 1)


def _browsed_headline(gameweek: Gameweek, week: _Week) -> list[Stat]:
    """A gameweek to come by its deadline; one under way or played by its score, and FPL's average once there is one."""
    if week.to_come:
        return [Stat(label="Deadline", value=at_time(gameweek.deadline))]
    stats = []
    if week.score is not None:
        stats.append(Stat(label="Final" if week.final else "Live", value=f"{week.score[0]} – {week.score[1]}"))
    elif week.scored is not None:
        stats.append(Stat(label="Points", value=str(week.scored)))
    if gameweek.average_score:
        stats.append(Stat(label="Average", value=str(gameweek.average_score)))
    return stats


def _chip_stat(windows: list[Chip], spent: dict[Chip, int | None], gameweek: int) -> Stat:
    """One chip as the gameweek in focus finds it, from each of its windows.

    The window open now decides the row: unplayed, it is available until that
    window's last gameweek; played, it says when, and when the next window
    opens. With none open, the next to open says when, and once every window is
    behind, the last says whether it was played or lost.
    """
    label = windows[0].label
    now = next((w for w in windows if w.covers(gameweek)), None)
    later = next((w for w in windows if w.start_event > gameweek), None)
    lost = any(spent[w] is None for w in windows if w.stop_event < gameweek)
    suffix = " · one expired unplayed" if lost else ""
    if now is not None and spent[now] is None:
        return Stat(label=label, value=f"available until GW{now.stop_event}{suffix}", tone="good")
    if now is not None:
        again = f" · again from GW{later.start_event}" if later else ""
        return Stat(label=label, value=f"played GW{spent[now]}{again}{suffix}")
    if later is not None:
        return Stat(label=label, value=f"from GW{later.start_event}{suffix}")
    last = windows[-1]
    if spent[last] is not None:
        return Stat(label=label, value=f"played GW{spent[last]}")
    return Stat(label=label, value="expired", tone="warning")


def _tone(player: Player) -> Tone:
    """A player warns whenever the game has flagged them at all."""
    return "warning" if player.availability else "neutral"


def _fixture_text(opponents: list[Opponent], name_of: Callable[[str], str] = str) -> str:
    """A club's matches this gameweek as a row reads them: 'vs LIV (2), at MCI (4)'.

    `name_of` spells the opponent. A lineup row has room for three letters and
    a drawer has room for the club, so the caller decides.
    """
    if not opponents:
        return "no fixture"
    return ", ".join(f"{'vs' if m.home else 'at'} {name_of(m.club)} ({m.difficulty})" for m in opponents)


def _window(gameweek: Gameweek, *, final: bool, begun: bool) -> str:
    """Which gameweek, and where it stands: final, in progress, or when it locks.

    A deadline is the useful date right up until it passes; after that the
    useful fact is that points are landing, and once every match is over, that
    they have landed. Rendered in UTC, which is what FPL publishes and what its
    own site shows every manager.
    """
    if final:
        return f"{gameweek.name} · final"
    if begun:
        return f"{gameweek.name} · in progress"
    return f"{gameweek.name} · deadline {at_time(gameweek.deadline)}"
