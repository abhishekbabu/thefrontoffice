"""Tests for which way a player's role is heading: `nfl/roles.py`.

Each player's games are written by hand, a share a game, so every direction below can be checked with a pencil.
"""

from support.nfl import SLEEPER_USER_ID, game_line, proj, week_of

from thefrontoffice.adapters.outbound.competitions.nfl.roles import heading, leads, protected, window
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    SleeperLeague,
    SleeperRoster,
)

LEAGUE = SleeperLeague(
    league_id="L1", name="Small", season="2026", total_rosters=2, scoring_format="pts_ppr", roster_positions=["BN"]
)


def _receiver(pid: str, weeks: dict[int, tuple[float, float]], team: str = "DAL") -> list[NFLGameLine]:
    """His games by week, each (snaps of 100, targets of 30)."""
    return [
        game_line(pid, week, position="WR", team=team, off_snp=snaps, tm_off_snp=100.0, rec_tgt=targets, pts_ppr=8.0)
        for week, (snaps, targets) in weeks.items()
    ]


def _club(weeks: range, team: str = "DAL") -> list[NFLGameLine]:
    """The rest of the club's 30 targets a week, on a part-timer."""
    return [
        game_line("rest", week, position="WR", team=team, off_snp=20.0, tm_off_snp=100.0, rec_tgt=30.0)
        for week in weeks
    ]


def _week(lines: list[NFLGameLine], depth: dict[str, int] | None = None, names: dict[str, str] | None = None) -> Week:
    ids = sorted({line.player_id for line in lines})
    positions = {line.player_id: line.position for line in lines}
    meta = {
        pid: PlayerMeta(
            player_id=pid,
            name=(names or {}).get(pid, pid.title()),
            position=positions[pid],
            team="DAL",
            depth_chart_order=(depth or {}).get(pid, 0),
        )
        for pid in ids
    }
    roster = SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=ids, starter_ids=[])
    return week_of(LEAGUE, roster, [proj(pid, pid, positions[pid], 8.0, team="DAL") for pid in ids], meta, lines=lines)


STEADY = dict.fromkeys(range(1, 9), (75.0, 4.5))
"""Three quarters of the snaps and 4.5 targets of a club's 34.5 every week: 13% of them."""


def test_a_share_that_falls_in_every_one_of_his_last_games_is_a_falling_role() -> None:
    games = {**STEADY, 9: (75.0, 2.0), 10: (75.0, 3.0), 11: (75.0, 1.0)}
    found = heading(_week(_receiver("wr", games) + _club(range(1, 12))), "wr")

    assert found is not None and found.direction == "falling"
    assert [shift.measure for shift in found.shifts if shift.direction == "falling"] == ["targets"]


def test_a_share_that_swings_is_holding_whatever_its_average() -> None:
    """Up a tenth on average, but under where it was in one of the three: a swing, not a role."""
    games = {**STEADY, 9: (95.0, 4.5), 10: (60.0, 4.5), 11: (100.0, 4.5)}
    found = heading(_week(_receiver("wr", games) + _club(range(1, 12))), "wr")

    assert found is not None and found.direction == "holding"


def test_more_snaps_in_every_recent_game_is_a_rising_role() -> None:
    games = {**dict.fromkeys(range(1, 9), (45.0, 4.5)), 9: (84.0, 4.5), 10: (86.0, 4.5), 11: (84.0, 4.5)}
    state = _week(_receiver("wr", games) + _club(range(1, 12)))

    found = heading(state, "wr")
    assert found is not None and found.direction == "rising"
    assert protected(state, proj("wr", "wr", "WR", 8.0, team="DAL")) == "role rising"


def test_a_falling_role_names_the_regular_teammate_back_in_his_latest_games() -> None:
    """Pickens missed week 9 and is back for 10 and 11: the receiver whose share fell may have given way to him."""
    games = {**STEADY, 9: (75.0, 2.0), 10: (75.0, 3.0), 11: (75.0, 1.0)}
    pickens = _receiver("wr2", {week: (85.0, 8.0) for week in range(1, 12) if week != 9})
    found = heading(
        _week(_receiver("wr", games) + pickens + _club(range(1, 12)), names={"wr2": "George Pickens"}), "wr"
    )

    assert found is not None and found.teammate == ("Pickens", 10)


def test_a_return_from_injury_starts_his_recent_games_there() -> None:
    """Weeks 1 to 5, then out until week 11: week 11 alone is his role now, weeks 1 to 5 what it was."""
    lines = _receiver("wr", dict.fromkeys((1, 2, 3, 4, 5), (45.0, 4.5)) | {11: (90.0, 4.5)}) + _club(range(1, 12))
    recent, earlier, returned = window(_week(lines), "wr")

    assert [game.week for game in recent] == [11]
    assert [game.week for game in earlier] == [1, 2, 3, 4, 5]
    assert returned == 11


def test_a_bye_is_no_return() -> None:
    lines = _receiver("wr", {week: (75.0, 4.5) for week in range(1, 12) if week != 7}) + _club(range(1, 12))

    assert window(_week(lines), "wr")[2] is None


def test_too_few_games_before_compare_nothing() -> None:
    lines = _receiver("wr", {9: (20.0, 1.0), 10: (90.0, 9.0), 11: (50.0, 2.0)}) + _club(range(9, 12))

    assert heading(_week(lines), "wr") is None


def test_a_back_or_receiver_heading_his_clubs_depth_chart_is_protected() -> None:
    lines = [
        game_line("rb", week, position="RB", team="DAL", off_snp=45.0, tm_off_snp=100.0, rush_att=12.0)
        for week in range(1, 9)
    ]
    state = _week(lines, depth={"rb": 1})
    back = proj("rb", "rb", "RB", 7.0, team="DAL")

    assert leads(state, back)
    assert protected(state, back) == "depth-1 RB"
    assert not leads(state, proj("k", "k", "K", 7.0, team="DAL"))


def test_a_holding_role_off_the_top_of_the_depth_chart_is_not_protected() -> None:
    state = _week(_receiver("wr", STEADY) + _club(range(1, 9)), depth={"wr": 3})

    assert protected(state, proj("wr", "wr", "WR", 8.0, team="DAL")) == ""
