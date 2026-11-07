"""Tests for the domain's own models."""

from thefrontoffice.domain.models import (
    Move,
    PlayerCard,
    PlayerOrder,
    TradeProposal,
    Urgency,
    outcome,
    record,
    urgency_rank,
)

# ── TradeProposal ───────────────────────────────────────────────────────


def test_both_sides_populated_is_valid() -> None:
    assert TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"]).is_valid


def test_one_sided_proposals_are_invalid() -> None:
    assert not TradeProposal(giving=["LeBron James"], receiving=[]).is_valid
    assert not TradeProposal(giving=[], receiving=["Jayson Tatum"]).is_valid


def test_empty_proposal_is_invalid() -> None:
    """What a parse that found neither side yields, so it must be falsy."""
    assert not TradeProposal().is_valid


# ── urgency ─────────────────────────────────────────────────────────────


def test_urgency_sorts_most_pressing_first() -> None:
    order: list[Urgency] = ["later", "now", "soon"]
    assert sorted(order, key=urgency_rank) == ["now", "soon", "later"]


def test_a_played_matchup_ends_won_lost_or_drawn() -> None:
    """Level scores are a draw, not a loss."""
    assert [outcome(*scores) for scores in ((90, 80), (80, 90), (85.5, 85.5))] == ["won", "lost", "drawn"]


def test_a_move_reads_as_an_instruction_naming_only_a_counterpart_it_takes_out() -> None:
    move = Move(action="START", player="A", position="RB", team="DET", metric="m", rationale="r", replaces="B")
    watch = move.model_copy(update={"action": "MONITOR"})

    assert (move.title, watch.title) == ("Start A over B", "Watch A")


def test_a_record_names_ties_only_where_there_were_any() -> None:
    assert (record(4, 2), record(4, 2, 1)) == ("4-2", "4-2-1")


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
