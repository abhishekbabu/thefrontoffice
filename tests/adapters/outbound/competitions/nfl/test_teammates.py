"""Tests for a player's points without a hurt teammate: `nfl/teammates.py`.

The club is LV. Its tight end one is hurt; its tight end two is the free agent
everybody is adding. Every figure below can be checked with a pencil.
"""

import pytest
from support.nfl import game_line

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import gather
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import HurtTeammates, split, surname
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine, PlayerMeta

SCORING = "pts_ppr"

STAR = PlayerMeta(player_id="te1", name="Brock Bowers", position="TE", team="LV", injury_status="Questionable")
BACKUP = PlayerMeta(player_id="te2", name="Michael Mayer", position="TE", team="LV")


def _te(pid: str, week: int, snaps: float, points: float, team: str = "LV", targets: float = 2) -> NFLGameLine:
    return game_line(pid, week, position="TE", team=team, off_snp=snaps, tm_off_snp=60, rec_tgt=targets, pts_ppr=points)


def _season() -> list[NFLGameLine]:
    """Bowers plays weeks 1-3, leaves week 4 early, misses week 5; Mayer plays all five."""
    return [
        *(_te("te1", w, 50, 15.0, targets=9) for w in (1, 2, 3)),
        _te("te1", 4, 10, 2.0, targets=1),
        *(_te("te2", w, 30, p) for w, p in ((1, 8.0), (2, 9.0), (3, 9.0), (4, 5.0), (5, 7.0))),
    ]


def test_a_backup_scores_his_games_without_the_starter_against_his_games_with_him() -> None:
    found = split(gather(_season(), SCORING), BACKUP, STAR)

    assert found is not None
    assert (found.games, found.alongside_games) == (2, 3)
    assert found.without == pytest.approx(6.0)
    assert found.alongside == pytest.approx(26 / 3)


def test_a_game_the_teammate_played_for_another_club_counts_neither_way() -> None:
    lines = [*_season(), _te("te1", 5, 50, 20.0, team="KC")]

    found = split(gather(lines, SCORING), BACKUP, STAR)

    assert found is not None
    assert found.games == 1


def test_a_player_who_never_played_without_him_has_no_split() -> None:
    lines = [_te("te1", 1, 50, 15.0), _te("te2", 1, 30, 8.0)]

    assert split(gather(lines, SCORING), BACKUP, STAR) is None


def test_the_split_says_its_sample_and_tones_by_which_way_it_cuts() -> None:
    found = split(gather(_season(), SCORING), BACKUP, STAR)
    assert found is not None

    assert found.cell() == "Bowers Q"
    assert "2 games" in found.figures()
    assert found.stat().tone == "warning"


def test_a_split_with_no_game_alongside_him_is_neither_good_nor_bad() -> None:
    lines = [_te("te1", 1, 50, 15.0), _te("te2", 2, 30, 8.0)]

    found = split(gather(lines, SCORING), BACKUP, STAR)

    assert found is not None
    assert (found.games, found.alongside) == (1, None)
    assert found.stat().tone == "neutral"


def test_a_hurt_regular_at_his_position_is_his_teammate_to_weigh() -> None:
    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP)}, gather(_season(), SCORING))

    assert [m.player_id for m in hurt.of(BACKUP)] == ["te1"]
    assert hurt.of(STAR) == []
    assert [s.teammate.player_id for s in hurt.splits(BACKUP)] == ["te1"]


def test_a_healthy_starter_or_a_hurt_depth_player_is_nobody_to_weigh() -> None:
    lines = _season()
    healthy = PlayerMeta(player_id="te1", name="Brock Bowers", position="TE", team="LV")
    assert HurtTeammates({"te1": healthy, "te2": BACKUP}, gather(lines, SCORING)).of(BACKUP) == []

    # A hurt backup barely on the field, beside a starter who is fit, moves nothing.
    hurt_backup = PlayerMeta(player_id="te2", name="Michael Mayer", position="TE", team="LV", injury_status="Out")
    depth = [_te("te1", 1, 50, 15.0), _te("te2", 1, 15, 3.0)]
    assert HurtTeammates({"te1": healthy, "te2": hurt_backup}, gather(depth, SCORING)).of(healthy) == []


def test_a_receiver_weighs_his_clubs_hurt_top_target_earner_at_tight_end() -> None:
    receiver = PlayerMeta(player_id="wr1", name="Slot Guy", position="WR", team="LV")
    lines = [*_season(), *(game_line("wr1", w, team="LV", off_snp=40, tm_off_snp=60, rec_tgt=3) for w in (1, 2))]

    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP, receiver)}, gather(lines, SCORING))

    assert [m.player_id for m in hurt.of(receiver)] == ["te1"]
    # Counted once, though he is both a hurt regular at tight end and the top target earner.
    assert [m.player_id for m in hurt.of(BACKUP)] == ["te1"]


@pytest.mark.parametrize(
    ("name", "short"),
    [("Brock Bowers", "Bowers"), ("Marvin Harrison Jr.", "Harrison"), ("Kenneth Walker III", "Walker"), ("Jr", "Jr")],
)
def test_a_surname_leaves_a_generational_suffix_off(name: str, short: str) -> None:
    assert surname(name) == short


def test_only_his_games_for_this_club_count() -> None:
    lines = [*_season(), _te("te2", 6, 50, 30.0, team="KC")]

    found = split(gather(lines, SCORING), BACKUP, STAR)

    assert found is not None
    assert found.games == 2
