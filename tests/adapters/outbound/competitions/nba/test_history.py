"""Tests for a basketball player's season of league moves: `nba/history.py`."""

from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.nba.history import ACTIVITY_DAYS, moves, recent
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MovedPlayer, YahooTransaction

LOPEZ, MELTON, BARRETT, MURRAY = "478.p.4472", "478.p.6057", "478.p.6165", "478.p.5660"

CLAIM = YahooTransaction(
    kind="add/drop",
    timestamp=1795079686,  # 19 Nov 2026, early morning in the league's Pacific clock
    players=(
        MovedPlayer(LOPEZ, "Brook Lopez", "C", "LAC", kind="add", source="waivers", destination="Kalshi"),
        MovedPlayer(MELTON, "De'Anthony Melton", "PG,SG", "GSW", kind="drop", source="Kalshi", destination="waivers"),
    ),
    bid="4",
)
TRADE = YahooTransaction(
    kind="trade",
    timestamp=1793870734,
    players=(
        MovedPlayer(BARRETT, "RJ Barrett", "SF", "TOR", kind="trade", source="Giddey", destination="Justin"),
        MovedPlayer(MURRAY, "Dejounte Murray", "PG", "NOP", kind="trade", source="Justin", destination="Giddey"),
    ),
)
DROP = YahooTransaction(
    kind="drop",
    timestamp=1793000000,
    players=(MovedPlayer(LOPEZ, "Brook Lopez", "C", "LAC", kind="drop", source="Injury Prone", destination="waivers"),),
)


def test_only_the_moves_he_was_part_of_count_oldest_first() -> None:
    rows = moves([CLAIM, TRADE, DROP], LOPEZ)

    assert [(r.what, r.who) for r in rows] == [("Drop", "Injury Prone"), ("Waiver", "Kalshi")]


def test_a_claim_reads_who_made_it_both_players_and_its_bid_on_the_leagues_day() -> None:
    [row] = moves([CLAIM], LOPEZ, mine="Kalshi")

    assert (row.when, row.detail, row.bid, row.is_mine) == ("19 Nov", "+Brook Lopez, -De'Anthony Melton", "$4", True)
    assert [(m.player_id, m.change, m.manager) for m in row.moves] == [
        (LOPEZ, "added", "Kalshi"),
        (MELTON, "dropped", "Kalshi"),
    ]


def test_a_trade_names_both_teams_and_what_each_got() -> None:
    [row] = moves([TRADE], BARRETT, mine="Kalshi")

    assert (row.who, row.what, row.detail, row.is_mine) == (
        "Justin ↔ Giddey",
        "Trade",
        "+RJ Barrett · +Dejounte Murray",
        False,
    )


NOW = datetime.fromtimestamp(CLAIM.timestamp, tz=UTC) + timedelta(days=1)


def test_the_leagues_activity_is_its_moves_lately_newest_first() -> None:
    lately = YahooTransaction(kind="drop", timestamp=CLAIM.timestamp - 3600, players=DROP.players)

    rows = recent([TRADE, lately, CLAIM, DROP], NOW, mine="Kalshi")

    assert [(r.what, r.who, r.is_mine) for r in rows] == [
        ("Waiver", "Kalshi", True),
        ("Drop", "Injury Prone", False),
        ("Trade", "Justin ↔ Giddey", False),
    ]


def test_a_move_older_than_the_window_is_left_out() -> None:
    stale = NOW - timedelta(days=ACTIVITY_DAYS, seconds=1)
    old = YahooTransaction(kind="drop", timestamp=int(stale.timestamp()), players=DROP.players)

    assert recent([old], NOW) == []
