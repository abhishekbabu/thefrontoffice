"""Tests for which of your backs is a handcuff: `nfl/handcuffs.py`."""

from thefrontoffice.adapters.outbound.competitions.nfl.handcuffs import handcuffs
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT
from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta


def _player(pid: str, depth: int, team: str = "SF", position: str = "RB") -> PlayerMeta:
    return PlayerMeta(player_id=pid, name=pid, position=position, team=team, depth_chart_order=depth)


CATALOG = {
    p.player_id: p
    for p in (
        _player("rb1", 1),
        _player("rb2", 2),
        _player("rb4", 4),
        _player("wr1", 1, position="WR"),
        _player("wr2", 2, position="WR"),
        _player("kc1", 1, team="KC"),
        _player("kc2", 2, team="KC"),
        _player("fa", 2, team=FREE_AGENT),
    )
}


def _cuffs(held: list[str], starting: tuple[str, ...] = ()) -> dict[str, str]:
    """Each handcuff's id, mapped to his starter's."""
    return {pid: starter.player_id for pid, starter in handcuffs(CATALOG, held, starting).items()}


def test_the_back_next_behind_your_clubs_first_back_is_his_handcuff() -> None:
    assert _cuffs(["rb1", "rb2"]) == {"rb2": "rb1"}


def test_the_next_back_listed_counts_where_the_chart_skips_a_number() -> None:
    """SF lists nobody third, so the fourth is next behind the second."""
    assert _cuffs(["rb2", "rb4"], starting=("rb2",)) == {"rb4": "rb2"}


def test_a_back_below_one_you_neither_start_nor_hold_first_is_no_handcuff() -> None:
    assert _cuffs(["rb2", "rb4"]) == {}


def test_a_back_further_down_than_next_is_no_handcuff() -> None:
    assert _cuffs(["rb1", "rb4"]) == {}


def test_a_handcuff_is_only_ever_to_a_back_at_his_own_club() -> None:
    assert _cuffs(["kc1", "rb2"]) == {}


def test_receivers_are_never_handcuffs() -> None:
    assert _cuffs(["wr1", "wr2"], starting=("wr1",)) == {}


def test_a_starter_with_nobody_of_yours_next_behind_him_has_no_handcuff() -> None:
    assert _cuffs(["rb2", "kc2"], starting=("rb2", "kc2")) == {}


def test_a_back_with_no_club_is_never_on_a_chart() -> None:
    assert _cuffs(["fa"], starting=("fa",)) == {}
