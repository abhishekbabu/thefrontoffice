"""Players as the app lists and details them: pages of cards, stat tables, comparisons."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from thefrontoffice.domain.models.activity import ActivityRow
from thefrontoffice.domain.models.values import Better, Stat, Tone

PAGE_SIZE = 50
"""Rows a page of a player list holds unless the caller asks for another number."""

MAX_PAGE = 200
"""The most rows one page may hold: as many as a screen could ever show at once."""


class PlayerOrder(BaseModel):
    """Which column a player list is ordered by, and which way.

    One rule for every list, whether a page of the wire or a whole roster:
    the number behind a formatted column where the card has one — "£15.5m"
    sorted as text sits below "£9.0m" — and rows with nothing in the column
    kept last in both directions.
    """

    sort: str = Field(default="", description="Column to order by. Empty means the competition's own ranking.")
    descending: bool = True

    def ordered(self, cards: list[PlayerCard]) -> list[PlayerCard]:
        """`cards` in this order, or as they came where no column is named.

        Blanks stay last either way, which a sort key cannot express on its
        own: fold "is it missing" into the key and reversing the sort brings
        them to the top, where they push every real answer off the first page.
        """
        column = self.sort
        if not column:
            return cards
        numeric = any(column in card.values for card in cards)

        def has_value(card: PlayerCard) -> bool:
            return column in card.values if numeric else bool(card.columns.get(column))

        def key(card: PlayerCard) -> float | str:
            return card.values[column] if numeric else card.columns.get(column, "").casefold()

        present = [card for card in cards if has_value(card)]
        missing = [card for card in cards if not has_value(card)]
        return sorted(present, key=key, reverse=self.descending) + missing


class PlayerQuery(PlayerOrder):
    """How much of a player list to return, in what order, and which of it.

    A football league's free-agent pool is four thousand players, so the list
    is a window onto a ranking rather than the ranking itself — which means
    the sort has to happen where the whole list is, not in the browser holding
    one page of it.
    """

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=PAGE_SIZE, ge=1, le=MAX_PAGE)
    position: str = Field(default="", description="Keep only this position. Empty keeps all.")
    search: str = Field(default="", description="Substring match across a row's own values.")
    view: str = Field(
        default="", description="One of the page's `views` to list instead of the whole pool. Empty is the pool."
    )


class PlayerPage(BaseModel):
    """One window onto a player list, and how much there is to page through."""

    players: list[PlayerCard] = Field(default_factory=list)
    total: int = Field(default=0, description="Rows matching the filters, before the window.")
    offset: int = 0
    limit: int = Field(default=PAGE_SIZE, description="The window's size, which the next page steps by.")
    positions: list[str] = Field(
        default_factory=list,
        description="Every position in the unfiltered pool, so a filter can be offered without guessing.",
    )
    views: list[str] = Field(
        default_factory=list,
        description="Other lists of the pool the competition offers, by name: 'Trending', 'IR'. Empty where none.",
    )


PLAYER_COLUMN = "Player"
"""The column holding a player's name, in every competition's table."""

POSITION_COLUMN = "Pos"
"""The column holding a player's position, in every competition's table: what one position filter reads."""

STATUS_COLUMN = "Status"
"""The column holding a player's availability, in the platform's own words."""

SLOT_COLUMN = "Slot"
"""The column holding where a rostered player sits in the lineup."""

ColumnRole = Literal["player", "status", "slot"]
"""What a column is, for the few a table renders as more than text."""

_ROLES: dict[str, ColumnRole] = {PLAYER_COLUMN: "player", STATUS_COLUMN: "status", SLOT_COLUMN: "slot"}


class PlayerCard(BaseModel):
    """A player as a row in a roster table.

    `columns` is the competition's own vocabulary — the Premier League sends
    Price and xPts, the NFL sends Slot — so a client renders whatever keys
    arrive rather than being taught each one. What sits beside it is what a
    table needs and a column should not be: an identifier to open, and whether
    he will play.
    """

    player_id: str
    columns: dict[str, str]
    values: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "The number behind a formatted column, for the columns that have one — "
            "'Price' reads '£15.5m' and sorts as 15.5. Sorting the string instead puts "
            "£9.0m above £15.5m, and parsing it back means teaching every client each "
            "competition's units."
        ),
    )
    ruled_out: bool = Field(
        default=False,
        description=(
            "Whether his status means he will not play, rather than that he might not — "
            "decided by the provider, which knows its platform's words for it."
        ),
    )
    notes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "A cell's fuller reading, by column, where the cell abbreviates it — 'Bowers Q' reads "
            "'Without Brock Bowers (TE, Q): 6.10/game in 3 games · 8.60 with'. Shown as its tooltip."
        ),
    )

    @computed_field(
        description="The columns a table renders as more than text, by what they hold — so no client matches names."
    )
    @property
    def roles(self) -> dict[str, ColumnRole]:
        return {column: _ROLES[column] for column in self.columns if column in _ROLES}


FIT_COLUMN = "Fits"
"""The column where a provider says how a player fits your lineup: the inbound
side places the chance of winning beside it."""


class StatGroup(BaseModel):
    """A handful of related figures under a heading.

    Twenty numbers in one list is a wall; the same twenty under "This week",
    "Season" and "Set pieces" can be read without looking for anything.
    """

    title: str
    stats: list[Stat] = Field(default_factory=list)
    note: str = Field(default="", description="What the heading says about the group as a whole: '2 available'.")
    tab: str = Field(
        default="",
        description="Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.",
    )


NOT_APPLICABLE = "N/A"
"""What a cell reads where a period has no answer at all.

Part of the contract rather than a formatting choice: a nought is an answer and
this is the absence of one. Sent with every table as `StatTable.absent`, so a
client dims it without keeping its own copy of the string.
"""


class StatRow(BaseModel):
    """One line of a table across every column: a measure over the periods, or a game over the measures."""

    label: str
    values: list[str] = Field(
        description=(
            f"One per column, in the same order. {NOT_APPLICABLE!r} where that column has no "
            "answer — distinct from '0', which is an answer."
        )
    )
    tone: Tone = "neutral"
    better: Better | None = Field(default=None, description="Which way this measure improves; null where it does not.")
    best: list[int] = Field(
        default_factory=list,
        description=(
            "The cells holding the best figure, by index — set only on a comparison, and only where at "
            "least two figures compare and they differ."
        ),
    )


class StatTable(BaseModel):
    """Figures on a grid, so they can be read across as well as down.

    A stack of per-season groups makes you hold last year's goals in your head
    while you scroll to this year's. A table puts them on one line, which is
    the whole reason anybody looks at more than one season — and a game log is
    the same grid turned the other way, a game to a row and a measure to a column.
    """

    title: str
    tab: str = Field(
        default="",
        description="Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.",
    )
    columns: list[str] = Field(
        description=(
            "Column headings, the subject first: periods newest first, ['2026/27', '2025/26'], "
            "or measures, ['Pts', 'Snaps', 'Car']."
        )
    )
    rows: list[StatRow] = Field(default_factory=list)
    absent: str = Field(
        default=NOT_APPLICABLE,
        description="What a cell reads where its column has no answer, so a client can tell it from a figure.",
    )


class PlayerDetail(BaseModel):
    """Everything worth knowing about one player, on demand.

    Fetched when someone asks rather than carried by every row: the interesting
    numbers differ per competition and there are a dozen of them, which is a table
    nobody can read attached to a payload nobody needs.
    """

    player_id: str
    name: str
    position: str
    team: str = Field(description="The club as a table spells it: 'DET', 'TOT'.")
    team_name: str = Field(
        default="",
        description=(
            "The same club in full — 'Detroit Lions', 'Tottenham Hotspur'. A drawer has room "
            "for the name a person would say, where a column has room for three letters. "
            "Empty falls back to `team` rather than leaving the line blank."
        ),
    )
    team_logo_url: str = Field(
        default="",
        description="The club's crest on the platform's own CDN, or empty where it has none.",
    )
    headline: str = Field(
        default="",
        description=(
            "The one figure this player is judged on, bare — '22.3', not '22.3 proj pts'. "
            "Empty when there is none, which is not the same as zero."
        ),
    )
    headline_label: str = Field(
        default="",
        description=(
            "What that figure is: 'projected this week', 'xPts this week'. When `headline` is "
            "empty this stands alone and says why there is no figure, so it reads as a sentence "
            "rather than as a number that failed to arrive."
        ),
    )
    note: str = Field(
        default="",
        description=(
            "Injury or availability news, in words — 'Out', 'Questionable', FPL's own sentence — never a "
            "platform's bare code, which alone in a header reads as a figure ('O' as zero)."
        ),
    )
    url: str = Field(
        default="",
        description="This player on the platform's own site, where one exists.",
    )
    image_url: str = Field(
        default="",
        description=(
            "Portrait on the platform's own CDN, or empty where that competition has none. "
            "A URL rather than bytes: it is the client that has a cache for it."
        ),
    )
    tone: Tone = "neutral"
    rank: str = Field(
        default="",
        description="Where he ranks at his position this season: 'WR12'. Empty before he has played.",
    )
    owner: str = Field(
        default="",
        description=(
            "Whose roster he is on in this league — a team's name, or 'Free agent'. Empty where "
            "the league has no such thing, as in FPL, where any number of managers can hold one player."
        ),
    )
    tabs: list[str] = Field(
        default_factory=list,
        description=(
            "The drawer's tabs in the order shown, by the names its groups and tables carry. "
            "Empty is one page of everything, in the order sent."
        ),
    )
    groups: list[StatGroup] = Field(default_factory=list)
    tables: list[StatTable] = Field(
        default_factory=list,
        description="Comparisons across periods, which a list of groups cannot show.",
    )
    moves: list[ActivityRow] = Field(
        default_factory=list,
        description="Each league move he was part of, oldest first, as the league's activity shows it.",
    )
    moves_tab: str = Field(default="", description="Which tab his moves sit in, by name; empty for the first.")
    deferred: list[str] = Field(
        default_factory=list,
        description=(
            "Tabs whose sections are read only when opened, each from the player's tab route: they cost a "
            "request the rest of the drawer does not. Offered whether or not they turn out to hold anything."
        ),
    )


MAX_COMPARED = 4
"""The most players one comparison holds: past four, the columns stop fitting a screen."""


class PlayerComparison(BaseModel):
    """Players side by side: who each is, and the figures they share on one grid."""

    players: list[PlayerDetail] = Field(
        description="Each player's header, in the order asked: name, club, the one figure, owner. No groups or tables."
    )
    tables: list[StatTable] = Field(
        description=(
            "One per heading the measures came under — 'Week 11', 'Projected line', '2026 season' — each a row "
            "per measure and a column per player, in the order of `players`."
        )
    )


class PlayerRef(BaseModel):
    """A player found by name, enough to tell him from another and to open him."""

    player_id: str
    name: str
    detail: str = Field(default="", description="Position, club and owner: 'WR · DAL · Rival'.")
