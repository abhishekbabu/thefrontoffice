"""Tests for a player's points without a hurt teammate: `nfl/teammates.py`.

The club is LV. Its tight end one is hurt; its tight end two is the free agent
everybody is adding. Every figure below can be checked with a pencil. How games part
by whether the teammate played, and how a split reads and is toned, are shared, and
covered in `competitions/test_teammates.py`.
"""

from dataclasses import replace

import pytest
from support.nfl import game_line

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import gather
from thefrontoffice.adapters.outbound.competitions.nfl.teammates import HurtTeammates, split
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


def test_a_player_who_never_played_without_him_has_no_split() -> None:
    lines = [_te("te1", 1, 50, 15.0), _te("te2", 1, 30, 8.0)]

    assert split(gather(lines, SCORING), BACKUP, STAR) is None


@pytest.mark.parametrize(
    ("status", "back", "cell"),
    [
        ("Out", False, "Bowers O"),
        ("IR", False, "Bowers IR"),
        ("Questionable", True, "Bowers Q"),
        ("", True, "Bowers back"),
    ],
)
def test_a_teammate_is_back_unless_ruled_out_and_his_cell_abbreviates_his_designation(
    status: str, back: bool, cell: str
) -> None:
    found = split(gather(_season(), SCORING), BACKUP, replace(STAR, injury_status=status))
    assert found is not None

    assert (found.back, found.cell()) == (back, cell)


def test_a_teammate_back_whom_he_scored_more_beside_is_good_news() -> None:
    """Mayer scored more beside Bowers, and Bowers plays: the figure beside him is the one that counts."""
    found = split(gather(_season(), SCORING), BACKUP, STAR)
    assert found is not None

    assert found.stat().tone == "good"


def test_a_player_who_never_played_beside_him_has_no_figure_alongside() -> None:
    lines = [_te("te1", 1, 50, 15.0), _te("te2", 2, 30, 8.0)]

    found = split(gather(lines, SCORING), BACKUP, STAR)

    assert found is not None
    assert (found.games, found.alongside, found.alongside_games) == (1, None, 0)


def test_a_hurt_regular_at_his_position_is_his_teammate_to_weigh() -> None:
    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP)}, gather(_season(), SCORING))

    assert [m.player_id for m in hurt.of(BACKUP)] == ["te1"]
    assert hurt.of(STAR) == []
    assert [s.teammate.player_id for s in hurt.splits(BACKUP)] == ["te1"]


def test_a_healthy_starter_who_missed_nothing_or_a_hurt_depth_player_is_nobody_to_weigh() -> None:
    lines = [*(_te("te1", w, 50, 15.0) for w in range(1, 6)), *(_te("te2", w, 30, 8.0) for w in range(1, 6))]
    healthy = PlayerMeta(player_id="te1", name="Brock Bowers", position="TE", team="LV")
    assert HurtTeammates({"te1": healthy, "te2": BACKUP}, gather(lines, SCORING)).of(BACKUP) == []

    # A hurt backup barely on the field, beside a starter who is fit, moves nothing.
    hurt_backup = PlayerMeta(player_id="te2", name="Michael Mayer", position="TE", team="LV", injury_status="Out")
    depth = [_te("te1", 1, 50, 15.0), _te("te2", 1, 15, 3.0)]
    assert HurtTeammates({"te1": healthy, "te2": hurt_backup}, gather(depth, SCORING)).of(healthy) == []


def test_a_healthy_regular_who_missed_a_recent_game_is_still_weighed() -> None:
    """Bowers missed week 5 and carries no designation now: the split is what Mayer's week 5 was worth."""
    healthy = replace(STAR, injury_status="")

    hurt = HurtTeammates({"te1": healthy, "te2": BACKUP}, gather(_season(), SCORING))

    assert [s.teammate.player_id for s in hurt.splits(BACKUP)] == ["te1"]


def test_a_regular_who_missed_a_game_long_ago_is_nobody_to_weigh() -> None:
    lines = [
        *(_te("te1", w, 50, 15.0) for w in (1, 3, 4, 5, 6)),
        *(_te("te2", w, 30, 8.0) for w in range(1, 7)),
    ]
    healthy = replace(STAR, injury_status="")

    assert HurtTeammates({"te1": healthy, "te2": BACKUP}, gather(lines, SCORING)).of(BACKUP) == []


def _understudy_season() -> list[NFLGameLine]:
    """Bowers as in `_season`; Mayer a part-timer beside him, on most of the snaps without him."""
    return [
        *(line for line in _season() if line.player_id == "te1"),
        *(_te("te2", w, 15, 2.0) for w in (1, 2, 3)),
        *(_te("te2", w, 50, 12.0) for w in (4, 5)),
    ]


def test_an_understudys_recent_games_without_a_teammate_who_is_back_are_fill_in_work() -> None:
    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP)}, gather(_understudy_season(), SCORING))

    found = hurt.filling_in(BACKUP)

    assert found is not None
    assert (found.weeks, found.alongside) == ((4, 5), 2.0)


def test_a_regular_beside_the_teammate_kept_his_own_role_and_is_no_fill_in() -> None:
    """Mayer was on half the snaps beside Bowers too: his games without him are his own."""
    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP)}, gather(_season(), SCORING))

    assert hurt.filling_in(BACKUP) is None


def test_games_without_a_teammate_still_ruled_out_are_no_fill_in() -> None:
    out = replace(STAR, injury_status="Out")

    assert HurtTeammates({"te1": out, "te2": BACKUP}, gather(_understudy_season(), SCORING)).filling_in(BACKUP) is None


def test_games_without_him_before_the_last_few_are_no_fill_in() -> None:
    """Mayer's game without Bowers was week 1; his last three were all beside him."""
    lines = [
        *(_te("te1", w, 50, 15.0) for w in (2, 3, 4, 5)),
        *(_te("te2", w, 15, 8.0) for w in range(1, 6)),
    ]

    assert HurtTeammates({p.player_id: p for p in (STAR, BACKUP)}, gather(lines, SCORING)).filling_in(BACKUP) is None


def test_a_receiver_weighs_his_clubs_hurt_top_target_earner_at_tight_end() -> None:
    receiver = PlayerMeta(player_id="wr1", name="Slot Guy", position="WR", team="LV")
    lines = [*_season(), *(game_line("wr1", w, team="LV", off_snp=40, tm_off_snp=60, rec_tgt=3) for w in (1, 2))]

    hurt = HurtTeammates({p.player_id: p for p in (STAR, BACKUP, receiver)}, gather(lines, SCORING))

    assert [m.player_id for m in hurt.of(receiver)] == ["te1"]
    # Counted once, though he is both a hurt regular at tight end and the top target earner.
    assert [m.player_id for m in hurt.of(BACKUP)] == ["te1"]
