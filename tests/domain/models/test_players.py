"""Tests for the players' models."""

from thefrontoffice.domain.models import PlayerCard, PlayerOrder

# ── ordering a player list ──────────────────────────────────────────────


def _card(player_id: str, status: str = "", price: float | None = None) -> PlayerCard:
    return PlayerCard(
        player_id=player_id,
        columns={"Player": player_id, "Status": status},
        values={} if price is None else {"Price": price},
    )


def test_rows_with_nothing_in_the_column_stay_last_both_ways() -> None:
    cards = [_card("none"), _card("cheap", price=4.5), _card("dear", price=15.5)]

    for descending in (True, False):
        ordered = PlayerOrder(sort="Price", descending=descending).ordered(cards)
        assert ordered[-1].player_id == "none"


def test_a_column_with_no_numbers_behind_it_sorts_as_text_ignoring_case() -> None:
    cards = [_card("a", status="out"), _card("b", status="Doubtful"), _card("c")]

    ordered = PlayerOrder(sort="Status", descending=False).ordered(cards)

    assert [c.player_id for c in ordered] == ["b", "a", "c"]


def test_no_column_keeps_the_competitions_own_order() -> None:
    cards = [_card("b"), _card("a")]
    assert PlayerOrder().ordered(cards) == cards


def test_a_card_names_the_columns_it_renders_by_role() -> None:
    card = PlayerCard(player_id="1", columns={"Player": "A", "Pos": "QB", "Slot": "BN", "Status": ""})
    assert card.roles == {"Player": "player", "Slot": "slot", "Status": "status"}
