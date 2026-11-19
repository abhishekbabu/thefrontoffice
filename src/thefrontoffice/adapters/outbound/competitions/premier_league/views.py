"""How an FPL player reads on a page: a squad or market row, and the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — your squad, anybody else's, the market, a player opened on his
own — and the provider is the place a gameweek is gathered, not drawn.

Everything here reads the bootstrap catalog every other call already reads,
so depth costs nothing; the one extra request is a player's past seasons,
made only when somebody opens him.
"""

import logging
from collections.abc import Callable

from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.premier_league import news, outlook
from thefrontoffice.adapters.outbound.competitions.premier_league.league import HARD_FIXTURE
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    DEFENSIVE_THRESHOLDS,
    Roster,
    Value,
    fixtures_by_club,
    plays,
)
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Club,
    Gameweek,
    Opponent,
    PastSeason,
    Player,
    PlayerGame,
    PlayerSummary,
    as_millions,
)
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Better,
    PlayerCard,
    PlayerDetail,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
    Tone,
)

logger = logging.getLogger(__name__)

# Keyed by Opta's code, not the element id. Public, keyless, and already
# alongside every other asset the site serves.
PORTRAIT_URL = "https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png"
# Filed under the club's media `code`, not its bootstrap `id`.
BADGE_URL = "https://resources.premierleague.com/premierleague/badges/70/t{code}.png"

# Two back plus the one in progress is three columns, which fits a drawer and
# is as far as a player's form is still the same player.
PAST_SEASON_LIMIT = 2

WEEK_TAB, GAME_LOG_TAB, FIXTURES_TAB, SEASONS_TAB = "This week", "Game log", "Fixtures", "Seasons"

EASY_FIXTURE = 2
"""The top of FPL's 1-5 scale it colours as a kind fixture."""

PRICE_MOVE = 100
"""Where FPL's price progress triggers a move: a rise at +100, a fall at -100."""

HAUL = 10
BLANK_RETURN = 2
"""A double-figure match is a haul; two points or fewer from one he played is a blank."""

GAME_LOG_COLUMNS: dict[str, tuple[tuple[str, Callable[[PlayerGame], int]], ...]] = {
    "GKP": (
        ("CS", lambda g: g.clean_sheets),
        ("GC", lambda g: g.goals_conceded),
        ("Sv", lambda g: g.saves),
        ("Bon", lambda g: g.bonus),
    ),
    "DEF": (
        ("G", lambda g: g.goals),
        ("A", lambda g: g.assists),
        ("CS", lambda g: g.clean_sheets),
        ("DC", lambda g: g.defensive_contribution),
        ("Bon", lambda g: g.bonus),
    ),
    "MID": (
        ("G", lambda g: g.goals),
        ("A", lambda g: g.assists),
        ("DC", lambda g: g.defensive_contribution),
        ("Bon", lambda g: g.bonus),
    ),
}
"""What each position is scored on in a match, after its points and minutes: a forward reads as a midfielder."""


# ── rows ────────────────────────────────────────────────────────────


def squad_cards(squad: Roster, value: Value) -> list[PlayerCard]:
    """One table shape for any manager's fifteen, each at his worth for the gameweek to come (`value`)."""
    return [
        PlayerCard(
            player_id=str(player.id),
            ruled_out=not plays(player),
            columns={
                **_market_columns(player, value),
                SLOT_COLUMN: ("C" if pick.is_captain else "XI") if pick.is_starting else "BN",
            },
            values=_market_values(player, value),
        )
        for pick, player in squad.picked
    ]


def market_card(player: Player, value: Value) -> PlayerCard:
    return PlayerCard(
        player_id=str(player.id),
        ruled_out=not plays(player),
        columns=_market_columns(player, value),
        values=_market_values(player, value),
    )


WORTH_COLUMN = "Worth"
"""What he adds the gameweek to come (`worth.Worth.week`): what the market is sorted on."""


def _market_values(player: Player, value: Value) -> dict[str, float]:
    """The numbers behind the formatted columns, so any of them can be
    sorted on. "£15.5m" sorted as text sits below "£9.0m"."""
    return {
        "Price": player.cost / 10,
        WORTH_COLUMN: value(player),
        "xPts": player.expected_points,
        "Form": player.form,
        "Points": float(player.total_points),
        "xGI": player.expected_goal_involvements,
        "Owned": player.selected_by,
    }


def _market_columns(player: Player, value: Value) -> dict[str, str]:
    return {
        PLAYER_COLUMN: player.name,
        POSITION_COLUMN: player.position,
        "Club": player.team,
        "Price": as_millions(player.cost),
        WORTH_COLUMN: f"{value(player):.1f}",
        "xPts": f"{player.expected_points:.1f}",
        "Form": f"{player.form:.1f}",
        "Points": str(player.total_points),
        "xGI": f"{player.expected_goal_involvements:.2f}",
        "Owned": f"{player.selected_by:.1f}%",
        STATUS_COLUMN: player.availability,
    }


def fixture_text(opponents: list[Opponent], name_of: Callable[[str], str] = str) -> str:
    """A club's matches this gameweek as a row reads them: 'vs LIV (2), at MCI (4)'.

    `name_of` spells the opponent. A lineup row has room for three letters and
    a drawer has room for the club, so the caller decides.
    """
    if not opponents:
        return "no fixture"
    return ", ".join(f"{'vs' if m.home else 'at'} {name_of(m.club)} ({m.difficulty})" for m in opponents)


# ── the drawer ──────────────────────────────────────────────────────


def detail(client: FPLSource, player: Player) -> PlayerDetail:
    """One player, grouped the way a manager actually weighs them, over four tabs.

    The week first — the fixture, FPL's projection, his form, and his injury
    where FPL has flagged one — then the underlying numbers his position is
    scored on, his set-piece duty and the market moving under the price.
    Then his season match by match, the gameweeks ahead, and the seasons before.
    """
    upcoming = client.upcoming_gameweek()
    gameweeks = client.get_gameweeks()
    clubs = _clubs(client)
    club = clubs.get(player.team)
    games = _summary(client, player)
    hurt = news.group(player, gameweeks)
    week = [
        Stat(label="Fixture", value=_fixture_line(client, player, upcoming)),
        Stat(label="Expected", value=f"{player.expected_points:.1f} xPts", better="higher"),
        Stat(label="Form", value=f"{player.form:.1f}", better="higher"),
    ]
    if hurt is None:
        week.append(Stat(label="Availability", value="fit", tone="good"))

    last = max((g.id for g in gameweeks), default=upcoming.id)
    tables = [
        _game_log(player, games.games),
        _fixtures_table(client, player, outlook.weeks_from(upcoming.id, last), clubs),
        _season_table(client, player, games.past),
    ]
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
        tabs=[WEEK_TAB, GAME_LOG_TAB, FIXTURES_TAB, SEASONS_TAB],
        groups=[
            StatGroup(title="This week", stats=week),
            *([hurt] if hurt else []),
            StatGroup(title="Underlying", stats=_underlying(player, games.games)),
            *([StatGroup(title="Set pieces", stats=_set_pieces(player))] if player.position != "GKP" else []),
            StatGroup(title="Market", stats=_market(player)),
        ],
        tables=[table for table in tables if table is not None],
    )


def _summary(client: FPLSource, player: Player) -> PlayerSummary:
    """His own page — this season match by match, and the seasons before — or nothing where it will not load.

    Enrichment, not a dependency: a drawer without a log still has the week.
    """
    try:
        return client.get_player_summaries([player.id]).value(player.id)
    except FPLAPIError as e:
        logger.warning(f"Continuing without {player.name}'s game log and past seasons: {e}")
        return PlayerSummary()


def _underlying(player: Player, games: list[PlayerGame]) -> list[Stat]:
    """Opta's expected numbers and the defensive contribution, as far as his position is scored on them.

    A keeper is scored on what he concedes and saves, not on expected goals;
    a forward's goals conceded cost him nothing. Defensive contribution — two
    points for 10 clearances, blocks, interceptions and tackles from a defender,
    12 with recoveries from anyone further forward — is counted per 90 and in
    how many of his matches reached it.
    """
    position = player.position
    stats = []
    if position != "GKP":
        stats += [
            Stat(label="xG", value=f"{player.expected_goals:.2f}", better="higher"),
            Stat(label="xA", value=f"{player.expected_assists:.2f}", better="higher"),
        ]
    if position in ("MID", "FWD"):
        stats.append(Stat(label="xGI", value=f"{player.expected_goal_involvements:.2f}", better="higher"))
    if position in ("GKP", "DEF"):
        stats.append(Stat(label="xGC", value=f"{player.expected_goals_conceded:.2f}", better="lower"))
    if position == "GKP":
        per_90 = player.saves * 90 / player.minutes if player.minutes else 0.0
        stats.append(Stat(label="Saves/90", value=f"{per_90:.1f}", better="higher"))
    threshold = DEFENSIVE_THRESHOLDS.get(position)
    if threshold is not None:
        played = [g for g in games if g.played]
        reached = sum(g.defensive_contribution >= threshold for g in played)
        stats += [
            Stat(label="DC/90", value=f"{player.defensive_contribution_per_90:.1f}", better="higher"),
            Stat(label=f"DC {threshold}+", value=f"{reached} of {len(played)}", better="higher"),
        ]
    return stats


def _market(player: Player) -> list[Stat]:
    """The price, what moved it this gameweek, and where FPL says it goes next.

    FPL publishes how far each player is towards his next move and where the
    next overnight update is projected to leave him: past +100 he rises, past
    -100 he falls. Net transfers this gameweek are what drive it.
    """
    change = player.price_change
    net = player.transfers_in - player.transfers_out
    return [
        Stat(label="Price", value=as_millions(player.cost)),
        Stat(
            label="This GW",
            value=f"{'+' if change > 0 else ''}{change / 10:.1f}m",
            tone="good" if change > 0 else "warning" if change < 0 else "neutral",
        ),
        _price_move(player),
        Stat(label="Net transfers", value=f"{net:+,}", better="higher"),
        Stat(label="Owned by", value=f"{player.selected_by:.1f}%"),
    ]


def _price_move(player: Player) -> Stat:
    """Where his price goes next: locked after a move, likely tonight, or how far towards one."""
    label = "Next move"
    if player.price_locked_until is not None:
        return Stat(label=label, value=f"locked until {weekday_day_month(player.price_locked_until.date())}")
    tonight = player.price_tonight
    if tonight is not None and tonight >= PRICE_MOVE:
        return Stat(label=label, value="rise likely tonight", tone="good")
    if tonight is not None and tonight <= -PRICE_MOVE:
        return Stat(label=label, value="fall likely tonight", tone="warning")
    progress = player.price_progress
    if not progress:
        return Stat(label=label, value="none due")
    return Stat(label=label, value=f"{abs(progress):.0f}% to a {'rise' if progress > 0 else 'fall'}")


def _game_log(player: Player, games: list[PlayerGame]) -> StatTable | None:
    """This season match by match, newest first: the points, then what his position scores them from.

    Every match his club played while he was on its books, a ninety minutes
    on the bench included — a nought with no minutes is a match missed. None
    before he has a match to show.
    """
    if not games:
        return None
    measures = GAME_LOG_COLUMNS.get(player.position, GAME_LOG_COLUMNS["MID"])
    rows = [
        StatRow(
            label=f"GW{g.event} {'vs' if g.home else 'at'} {g.opponent}",
            values=[str(g.points), str(g.minutes), *(str(read(g)) for _, read in measures)],
            tone="good" if g.points >= HAUL else "warning" if g.played and g.points <= BLANK_RETURN else "neutral",
        )
        for g in reversed(games)
    ]
    return StatTable(
        title="Game log", tab=GAME_LOG_TAB, columns=["Pts", "Min", *(label for label, _ in measures)], rows=rows
    )


def _fixtures_table(client: FPLSource, player: Player, weeks: list[int], clubs: dict[str, Club]) -> StatTable | None:
    """His club's next gameweeks: who, where, and how hard the game rates it — a blank and a double included.

    Read off the season's fixture list, the same the weeks ahead are, so the
    two agree. None once the season has no gameweeks left, or where the list
    will not load.
    """
    if not weeks:
        return None
    try:
        by = outlook.ticker(client.get_season_fixtures())
    except FPLAPIError as e:
        logger.warning(f"Continuing without {player.name}'s fixtures: {e}")
        return None

    def in_full(short_name: str) -> str:
        club = clubs.get(short_name)
        return club.name if club else short_name

    rows = []
    for week in outlook.run_of(player.team, weeks, by):
        if not week.games:
            rows.append(StatRow(label=f"GW{week.week}", values=["no fixture", NOT_APPLICABLE], tone="warning"))
        for game in week.games:
            rows.append(
                StatRow(
                    label=f"GW{week.week}" + (" (double)" if len(week.games) > 1 else ""),
                    values=[f"{'vs' if game.home else 'at'} {in_full(game.opponent)}", str(game.difficulty)],
                    tone="warning"
                    if game.difficulty >= HARD_FIXTURE
                    else "good"
                    if game.difficulty <= EASY_FIXTURE
                    else "neutral",
                )
            )
    return StatTable(title="Fixtures", tab=FIXTURES_TAB, columns=["Opponent", "FDR"], rows=rows)


def _clubs(client: FPLSource) -> dict[str, Club]:
    """Every club in full, keyed by the abbreviation a player carries.

    Read off the same bootstrap as everything else, so it costs no request.
    Degrades to nothing rather than failing a page: a drawer that says
    "TOT" is worse than one that says "Spurs" and no worse than before.
    """
    try:
        return client.get_clubs()
    except FPLAPIError as e:
        logger.warning(f"Continuing without club names: {e}")
        return {}


def _season_table(client: FPLSource, player: Player, past: list[PastSeason]) -> StatTable:
    """This season beside the two before it, read across rather than down.

    The catalog carries only the season in progress, which in August is a
    single gameweek — so a page meant to justify a £15m striker shows one
    match, and the question anybody actually has is whether he did it last
    year. Stacked groups make you hold last year's goals in your head while
    scrolling to this year's; a row puts them side by side.

    Read off his own page, which the drawer already fetched for the game log;
    a promoted club's signing has no FPL history at all, and gets this season alone.
    """
    seasons = list(reversed(past[-PAST_SEASON_LIMIT:]))
    columns = [_season_label(seasons)] + [s.season for s in seasons]

    # A season nobody has kicked a ball in has no answers, and a column of
    # noughts claims it does.
    started = _season_started(client)
    keeper_or_defender = player.position in ("GKP", "DEF")

    def row(
        label: str, current: str, of_past: Callable[[PastSeason], str], better: Better | None = "higher"
    ) -> StatRow:
        return StatRow(
            label=label,
            values=[current if started else NOT_APPLICABLE] + [of_past(s) for s in seasons],
            better=better,
        )

    outfield = player.position != "GKP"
    rows = [
        row("Points", str(player.total_points), lambda s: str(s.total_points)),
        row("Per start", f"{player.points_per_game:.1f}", lambda s: f"{s.points_per_game:.1f}"),
        row("Starts", str(player.starts), lambda s: str(s.starts)),
        row("Minutes", f"{player.minutes:,}", lambda s: f"{s.minutes:,}"),
        *(
            [
                row("Goals", str(player.goals), lambda s: str(s.goals)),
                row("Assists", str(player.assists), lambda s: str(s.assists)),
            ]
            if outfield
            else []
        ),
        *(
            [
                row("Clean sheets", str(player.clean_sheets), lambda s: str(s.clean_sheets)),
                row("Conceded", str(player.goals_conceded), lambda s: str(s.goals_conceded), "lower"),
            ]
            if keeper_or_defender
            else []
        ),
        *([row("Saves", str(player.saves), lambda s: str(s.saves))] if not outfield else []),
        *(
            [row("Def. contribution", str(player.defensive_contribution), lambda s: str(s.defensive_contribution))]
            if outfield
            else []
        ),
        row("Bonus", str(player.bonus), lambda s: str(s.bonus)),
        *(
            [
                row("xG", f"{player.expected_goals:.2f}", lambda s: f"{s.expected_goals:.2f}"),
                row("xA", f"{player.expected_assists:.2f}", lambda s: f"{s.expected_assists:.2f}"),
            ]
            if outfield
            else []
        ),
        # The market's own verdict on a season: what the price did over it.
        StatRow(
            label="Price",
            values=[as_millions(player.cost)]
            + [f"{as_millions(s.start_cost)} → {as_millions(s.end_cost)}" for s in seasons],
        ),
    ]
    return StatTable(title="By season", tab=SEASONS_TAB, columns=columns, rows=rows)


def _season_started(client: FPLSource) -> bool:
    """Whether this season has produced anything to report yet.

    A gameweek in progress is not a gameweek with totals in it — the
    catalog is still all noughts until one finishes.
    """
    return any(gw.finished for gw in client.get_gameweeks())


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


def _fixture_line(client: FPLSource, player: Player, gameweek: Gameweek) -> str:
    """The drawer's fixture, with the opponent named the way it is said."""
    clubs = _clubs(client)

    def in_full(short_name: str) -> str:
        club = clubs.get(short_name)
        return club.name if club else short_name

    opponents = fixtures_by_club(client.get_fixtures(gameweek.id), [player.team])[player.team]
    return fixture_text(opponents, in_full)


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
        Stat(label=name, value=f"#{order}", tone="good" if order == 1 else "neutral", better="lower")
        for name, order in duties
        if order is not None
    ]
    return taken or [Stat(label="Set pieces", value="none")]


def _tone(player: Player) -> Tone:
    """A player warns whenever the game has flagged them at all."""
    return "warning" if player.availability else "neutral"
