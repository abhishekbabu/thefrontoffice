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

from thefrontoffice.adapters.outbound.competitions.premier_league.rules import Roster, fixtures_by_club, plays
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Club,
    Gameweek,
    Opponent,
    PastSeason,
    Player,
    as_millions,
)
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
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


# ── rows ────────────────────────────────────────────────────────────


def squad_cards(squad: Roster) -> list[PlayerCard]:
    """One table shape for any manager's fifteen."""
    return [
        PlayerCard(
            player_id=str(player.id),
            ruled_out=not plays(player),
            columns={
                **_market_columns(player),
                SLOT_COLUMN: ("C" if pick.is_captain else "XI") if pick.is_starting else "BN",
            },
            values=_market_values(player),
        )
        for pick, player in squad.picked
    ]


def market_card(player: Player) -> PlayerCard:
    return PlayerCard(
        player_id=str(player.id),
        ruled_out=not plays(player),
        columns=_market_columns(player),
        values=_market_values(player),
    )


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
    """One player, grouped the way a manager actually weighs them.

    Opta's expected numbers, the season return, the set-piece duty that
    separates a good price from a bad one, and the market moving under the price.
    """
    upcoming = client.upcoming_gameweek()
    club = _clubs(client).get(player.team)

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
                    Stat(label="Fixture", value=_fixture_line(client, player, upcoming)),
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
            StatGroup(title="Set pieces", stats=_set_pieces(player)),
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
        tables=[_season_table(client, player)],
    )


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


def _season_table(client: FPLSource, player: Player) -> StatTable:
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
        past = client.get_past_seasons(player.id)
    except FPLAPIError as e:
        logger.warning(f"Skipping past seasons for {player.name}: {e}")
        past = []

    seasons = list(reversed(past[-PAST_SEASON_LIMIT:]))
    columns = [_season_label(seasons)] + [s.season for s in seasons]

    # A season nobody has kicked a ball in has no answers, and a column of
    # noughts claims it does.
    started = _season_started(client)
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
        Stat(label=name, value=f"#{order}", tone="good" if order == 1 else "neutral")
        for name, order in duties
        if order is not None
    ]
    return taken or [Stat(label="Set pieces", value="none")]


def _tone(player: Player) -> Tone:
    """A player warns whenever the game has flagged them at all."""
    return "warning" if player.availability else "neutral"
