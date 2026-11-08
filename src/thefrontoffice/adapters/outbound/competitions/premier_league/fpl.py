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

from thefrontoffice.adapters.outbound.competitions import paging
from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.premier_league import league, prompt
from thefrontoffice.adapters.outbound.competitions.premier_league.squad import (
    Roster,
    best_lineup,
    effective_points,
    fixtures_by_club,
    free_transfers,
    lineup_changes,
    plays,
    points_of,
    points_with_captain,
    roster,
)
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Chip,
    Club,
    Fixture,
    Gameweek,
    LiveStat,
    MiniLeague,
    Opponent,
    PastSeason,
    Pick,
    Player,
    as_millions,
)
from thefrontoffice.domain.errors import PlayerNotFoundError, TeamNotFoundError
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
    Spot,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
    Summary,
    Swap,
    TeamRef,
    Tone,
)
from thefrontoffice.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Where the moves are actually made.
LEAGUE_URL = "https://fantasy.premierleague.com/leagues/{league_id}/standings/{kind}"
ENTRY_URL = "https://fantasy.premierleague.com/entry/{entry_id}/event/1"

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
                    url=ENTRY_URL.format(entry_id=entry.entry_id),
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
        """The gameweek being played: where points are landing, and the latest whose picks are published.

        Picks appear only once a deadline passes, so before the season opens
        no gameweek is current, there is nothing to read, and no squad view
        can be built.
        """
        current = self.client.current_gameweek()
        if current is None:
            raise FPLAPIError("The season has not started, so no squad has been picked yet.")
        return current

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
                url=ENTRY_URL.format(entry_id=row.entry),
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
        """The gameweek being played: both squads, the fixtures, the swaps.

        Reaches for the squad, the history and the tie — everything the week is
        made of — and stops short of the transfer market, which is the expensive
        half of a report and answers a different question.
        """
        entry_id = self.entry_id
        # Points are landing in this one; the next deadline is a plan, and the
        # report is where plans go.
        gameweek = self._gameweek()
        mine = self._roster(entry_id, gameweek.id)
        best = best_lineup(mine.players)
        entry = self.client.get_entry(entry_id)
        week_fixtures = self.client.get_fixtures(gameweek.id)
        fixtures = fixtures_by_club(week_fixtures, (p.team for p in mine.players))
        live = self._live_points(gameweek.id)
        scored = mine.scored(live)
        upcoming = self.client.upcoming_gameweek()

        return Summary(
            headline=prompt.headline(
                mine.squad,
                # Keyed to the next deadline, because that is the one an
                # allowance can still be spent against.
                free_transfers(self.client.get_history(entry_id), upcoming.id),
                best,
                points_with_captain(mine.starters, mine.captain),
                upcoming,
            ),
            mine=Side(
                name=entry.name,
                detail=f"GW{gameweek.id}",
                # Empty until somebody has played rather than zero, which reads
                # as a bad week instead of a week that has not started.
                points=f"{scored} pts" if scored is not None else "",
                lineup=self._spots(mine, starting=True, fixtures=fixtures, live=live),
                bench=self._spots(mine, starting=False, fixtures=fixtures, live=live),
            ),
            opponent=self._opponent(league_id, entry_id, gameweek.id, week_fixtures, live),
            swaps=[
                Swap(
                    start=change.start.name,
                    out=change.drop.name if change.drop else "",
                    gain=f"+{change.gain:.1f} xPts",
                )
                for change in lineup_changes(mine.starters, best)
            ],
            fixtures=self._warnings(fixtures),
            boosts=self._chips(entry_id, gameweek.id),
            window=_window(gameweek, live=any(s.has_played for s in live.values())),
        )

    def _chips(self, entry_id: int, gameweek: int) -> StatGroup | None:
        """What is left of the season's chips, and what has become of the rest.

        The game issues a set per half, so the same chip appears twice with
        different windows — one grouped row per name, showing the first window
        that has not closed, because that is the one still worth a decision.

        A chip whose windows have all passed is still listed: an unplayed Free
        Hit is a thing that was lost, and a row saying so is worth more than a
        row quietly missing.
        """
        try:
            issued = self.client.get_chips()
            played = {c.name: c.event for c in self.client.get_chips_played(entry_id)}
        except FPLAPIError as e:
            logger.warning(f"Continuing without chips: {e}")
            return None
        if not issued:
            return None

        stats: list[Stat] = []
        for name in dict.fromkeys(c.name for c in issued):
            windows = sorted((c for c in issued if c.name == name), key=lambda c: c.start_event)
            live = next((c for c in windows if c.stop_event >= gameweek), None)
            stats.append(self._chip_stat(windows[0].label, live, played.get(name), gameweek))
        available = sum(stat.tone == "good" for stat in stats)
        return StatGroup(title="Chips", stats=stats, note=f"{available} available")

    @staticmethod
    def _chip_stat(label: str, live: Chip | None, played: int | None, gameweek: int) -> Stat:
        if played is not None:
            return Stat(label=label, value=f"played GW{played}")
        if live is None:
            return Stat(label=label, value="gone unplayed", tone="warning")
        if live.covers(gameweek):
            return Stat(label=label, value="available", tone="good")
        return Stat(label=label, value=f"from GW{live.start_event}")

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
        """The season, the table, and the real matches behind the gameweek."""
        entry_id = self.entry_id
        # Marked on the week being played, so the season table and the week
        # view agree about which row is "now". Before the season opens nothing
        # is being played, and the calendar still has a first week to mark.
        playing = self.client.current_gameweek() or self.client.upcoming_gameweek()
        schedule = league.build(self.client, self._find_league(league_id, entry_id), entry_id, playing.id)
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

    def _opponent(
        self,
        league_id: str,
        entry_id: int,
        gameweek: int,
        week_fixtures: list[Fixture],
        live: dict[int, LiveStat],
    ) -> Side | None:
        """Who this entry is playing, and what they are fielding.

        Only head-to-head leagues pair managers; a classic league is a table,
        so there is no opponent to show and saying so beats inventing one.
        """
        mini_league = self._find_league(league_id, entry_id)
        if mini_league is None or not mini_league.is_h2h:
            return None

        try:
            match = self.client.get_h2h_match(mini_league.id, entry_id, gameweek)
            if match is None:
                return None
            theirs = self._roster(match.opponent_entry, gameweek)
        except FPLAPIError as e:
            # The rest of the page is about your own squad and still stands.
            logger.warning(f"Skipping the head-to-head opponent: {e}")
            return None

        fixtures = fixtures_by_club(week_fixtures, (p.team for p in theirs.players))
        return Side(
            name=match.opponent_name,
            detail=f"GW{gameweek}",
            # The game's own total rather than a sum of the rows: it already
            # accounts for auto-subs, which a squad list cannot show.
            points=f"{match.opponent_points} pts",
            lineup=self._spots(theirs, starting=True, fixtures=fixtures, live=live),
            bench=self._spots(theirs, starting=False, fixtures=fixtures, live=live),
        )

    def _spots(
        self,
        squad: Roster,
        *,
        starting: bool,
        fixtures: dict[str, list[Opponent]],
        live: dict[int, LiveStat],
    ) -> list[Spot]:
        return [
            self._spot(pick, player, fixtures, live) for pick, player in squad.picked if pick.is_starting == starting
        ]

    def _spot(
        self,
        pick: Pick,
        player: Player,
        fixtures: dict[str, list[Opponent]],
        live: dict[int, LiveStat],
    ) -> Spot:
        """One row of a lineup, showing what happened where anything has.

        Once a gameweek is under way the scored total is the number somebody is
        looking for, and a projection beside it is last week's guess about a
        question already being answered. Before then, the projection is all
        there is.
        """
        flag = player.availability
        stat = live.get(player.id)
        armband = " (C)" if pick.is_captain else " (V)" if pick.is_vice_captain else ""
        points = points_of(pick, stat) if stat is not None and stat.has_played else None
        opponents = fixtures.get(player.team, [])
        return Spot(
            player_id=str(player.id),
            player=player.name + armband,
            detail=f"{player.position} · {player.team} {_fixture_text(opponents)}" + (f" · {flag}" if flag else ""),
            # Points once they exist, the projection until then. A player whose
            # match is on Sunday has not blanked, and showing them a nought
            # says they have.
            value=f"{points} pts" if points is not None else f"{effective_points(player):.1f} xPts",
            tone=self._spot_tone(points, flag, blank=not opponents),
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
                notable.append(Stat(label=club, value="no fixture — these players score nothing", tone="warning"))
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
            allowance=free_transfers(self.client.get_history(entry_id), upcoming.id),
            fixtures=fixtures_by_club(self.client.get_fixtures(upcoming.id), (p.team for p in mine.players)),
        )


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


def _window(gameweek: Gameweek, live: bool = False) -> str:
    """Which gameweek, and either when it locks or that it already has.

    A deadline is the useful date right up until it passes; after that the
    useful fact is that points are landing. Rendered in UTC, which is what FPL
    publishes and what its own site shows every manager.
    """
    if live:
        return f"{gameweek.name} · in progress"
    return f"{gameweek.name} · deadline {at_time(gameweek.deadline)}"
