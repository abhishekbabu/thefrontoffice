"""Tests for the week's models."""

from thefrontoffice.domain.models import Action, Move, MovePlayer, Stat, Urgency, urgency_rank

# ── urgency ─────────────────────────────────────────────────────────────


def test_urgency_sorts_most_pressing_first() -> None:
    order: list[Urgency] = ["later", "now", "soon"]
    assert sorted(order, key=urgency_rank) == ["now", "soon", "later"]


def test_a_move_reads_as_an_instruction_naming_only_a_counterpart_it_takes_out() -> None:
    move = Move(action="START", player="A", position="RB", team="DET", metric="m", rationale="r", replaces="B")
    watch = move.model_copy(update={"action": "MONITOR"})

    assert (move.title, watch.title) == ("Start A over B", "Watch A")


# ── a to-do item's players ──────────────────────────────────────────────

DIKE = MovePlayer(
    side="in",
    player_id="dike",
    name="Chimere Dike",
    position="WR",
    team="TEN",
    held="free agent",
    figures=[Stat(label="Proj", value="9.88")],
)


def test_a_moved_player_reads_with_his_side_where_he_stands_and_his_figures() -> None:
    text = DIKE.text()

    assert text.startswith("IN") and "free agent" in text and "9.88" in text


def test_a_player_with_no_figures_reads_without_them() -> None:
    assert "—" not in DIKE.model_copy(update={"figures": []}).text()


def test_a_change_in_a_compared_figure_changes_the_items_fingerprint() -> None:
    """A verdict on yesterday's projection is stale once it moves, as it was when the reason stated it."""
    item = Action(kind="waiver", urgency="soon", title="Pick up Chimere Dike", reason="Role growing.", players=[DIKE])
    moved = DIKE.model_copy(update={"figures": [Stat(label="Proj", value="12.40")]})

    assert item.fingerprint != item.model_copy(update={"players": [moved]}).fingerprint


def test_an_item_without_players_keeps_the_fingerprint_it_had() -> None:
    """Adding the field must not mark every judged lineup item stale."""
    item = Action(kind="lineup", urgency="now", title="t", reason="r")

    assert item.fingerprint == item.model_copy(update={"players": []}).fingerprint


def test_an_item_lists_its_players_before_its_evidence_for_a_model() -> None:
    item = Action(
        kind="waiver",
        urgency="soon",
        title="t",
        reason="r",
        players=[DIKE],
        evidence=[Stat(label="Chimere Dike", value="News: promoted")],
    )

    assert item.lines() == [DIKE.text(), "Chimere Dike: News: promoted"]
