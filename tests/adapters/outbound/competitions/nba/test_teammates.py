"""Tests for a basketball player's line without a regular teammate: `nba/teammates.py`.

The club is TOR, eight games in. Scottie Barnes, its star, played the first
four and sat the last four; Jakob Poeltl, its centre, played all eight —
six points a game beside Barnes, twelve without him.
"""

from datetime import UTC, date, datetime

import pytest
from support.nba import box_scores, game_log, make_player

from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores
from thefrontoffice.adapters.outbound.competitions.nba.teammates import (
    LEFT_EARLY_MINUTES,
    REGULAR_MINUTES,
    Condition,
    Regular,
    Teammates,
    conditions,
    espn_status,
    reported,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog

STAR, CENTRE, GUARD = "s1", "c1", "g1"
NAMES = {STAR: "Scottie Barnes", CENTRE: "Jakob Poeltl", GUARD: "Jamal Shead"}
OUT = {STAR: Condition(status="O", returns=date(2026, 11, 22))}


_log = game_log


def _season() -> dict[str, list[NBAGameLog]]:
    return {
        STAR: [_log(STAR, d, 35.0, pts=25, fga=20, to=3) for d in (1, 2, 3, 4)],
        CENTRE: [_log(CENTRE, d, 20.0, pts=6 if d <= 4 else 12, reb=5) for d in range(1, 9)],
        GUARD: [_log(GUARD, d, 18.0, pts=4, ast=3) for d in range(1, 9)],
    }


def _scores(logs: dict[str, list[NBAGameLog]], names: dict[str, str] | None = None) -> BoxScores:
    return box_scores(logs, names or NAMES)


def _splits(
    logs: dict[str, list[NBAGameLog]] | None = None,
    known: dict[str, Condition] | None = None,
    name: str = "Jakob Poeltl",
    team: str = "TOR",
    weights: dict[str, float] | None = None,
):
    mates = Teammates(_scores(logs or _season()), weights)
    return mates.splits(make_player(name, team=team), OUT if known is None else known)


def test_a_centre_scores_his_games_without_the_star_against_his_games_with_him() -> None:
    (found,) = _splits()

    assert [m.regular.name for m in found.teammates] == ["Scottie Barnes"]
    assert (found.games, found.alongside_games) == (4, 4)
    assert (found.without["PTS"], found.alongside["PTS"]) == (12.0, 6.0)


def test_a_regular_is_a_heavy_minutes_player_or_the_clubs_top_usage_one() -> None:
    logs = _season()
    # Under the minutes, but ends more possessions than anybody: the club's top usage player.
    logs[STAR] = [_log(STAR, d, REGULAR_MINUTES - 4, fga=20, to=3) for d in (1, 2, 3, 4)]
    logs[GUARD] = [_log(GUARD, d, REGULAR_MINUTES + 2, fga=2) for d in range(1, 9)]

    regulars = {r.player_id for r in Teammates(_scores(logs)).regulars()}

    assert regulars == {STAR, GUARD}


def test_a_star_out_today_counts_though_he_sat_none_of_the_last_games() -> None:
    # Barnes sat three games early on, and has played every one since.
    logs = {
        STAR: [_log(STAR, d, 35.0) for d in range(1, 13) if d not in (3, 4, 5)],
        CENTRE: [_log(CENTRE, d, 20.0, pts=12 if d in (3, 4, 5) else 6) for d in range(1, 13)],
    }

    assert len(_splits(logs)) == 1
    assert _splits(logs, known={}) == []


def test_a_star_who_lately_sat_counts_though_nothing_is_reported() -> None:
    (found,) = _splits(known={})

    assert found.back
    assert found.cell() == "Barnes back"


def test_too_few_games_either_side_is_no_split() -> None:
    logs = _season()
    logs[STAR] = [_log(STAR, d, 35.0) for d in range(1, 8)]

    assert _splits(logs) == []


def test_a_game_the_star_left_early_counts_as_one_he_missed() -> None:
    logs = _season()
    logs[STAR] = [*logs[STAR], _log(STAR, 5, LEFT_EARLY_MINUTES - 1)]

    (found,) = _splits(logs)

    assert found.games == 4


def test_a_player_sleeper_places_at_another_club_gets_no_split() -> None:
    assert _splits(team="BOS") == []


def test_an_ambiguous_name_gets_no_split_rather_than_somebody_elses() -> None:
    names = {**NAMES, "c2": "Jonas Poeltl"}
    mates = Teammates(_scores(_season(), names))

    assert mates.splits(make_player("J. Poeltl", team="TOR"), OUT) == []


def test_a_teammate_ruled_out_reads_without_and_leads_with_the_figure_without_him() -> None:
    (found,) = _splits()

    assert not found.back
    assert found.cell() == "Barnes O"
    assert found.label().startswith("Without Scottie Barnes")
    assert "~22 Nov" in found.label()
    assert found.figures().index("12.0") < found.figures().index("6.0")
    assert found.stat().tone == "good"


def test_a_teammate_due_back_reads_with_and_leads_with_the_figure_beside_him() -> None:
    (found,) = _splits(known={STAR: Condition(status="GTD")})

    assert found.back
    assert found.label().startswith("With Scottie Barnes")
    assert found.figures().index("6.0") < found.figures().index("12.0")
    # He did more without Barnes, and Barnes plays: bad news.
    assert found.stat().tone == "warning"


def test_a_points_league_split_carries_fantasy_points() -> None:
    (found,) = _splits(weights={"12": 1.0, "15": 1.2})

    assert (found.without_points, found.alongside_points) == (pytest.approx(18.0), pytest.approx(12.0))
    assert found.gain == pytest.approx(6.0)
    assert "fpts" in found.figures()
    assert "fpts" in found.prompt()


def test_the_prompt_line_names_the_teammate_both_samples_and_the_figures() -> None:
    text = _splits()[0].prompt()

    assert "Scottie Barnes" in text
    assert "in 4G" in text
    assert text.index("12.0p") < text.index("6.0p")


def test_teammates_ruled_out_come_first_then_by_how_much_more_he_does_without_them() -> None:
    logs = _season()
    # A regular guard who sat games 3 to 5: Poeltl did a little less without him.
    logs[GUARD] = [_log(GUARD, d, 33.0) for d in (1, 2, 6, 7, 8)]
    both = {GUARD: Condition(status="O"), STAR: Condition(status="O")}

    def order(known: dict[str, Condition]) -> list[str]:
        return [s.teammates[0].regular.player_id for s in _splits(logs, known)]

    assert order(both) == [STAR, GUARD]
    assert order({**both, STAR: Condition(status="DTD")}) == [GUARD, STAR]


def test_espns_words_are_read_in_yahoos() -> None:
    assert (espn_status("Out"), espn_status("Day-To-Day"), espn_status("Other")) == ("O", "DTD", "Other")


def _report(name: str, status: str = "Out", club: str = "TOR", athlete_id: str = "") -> InjuryReport:
    return InjuryReport(
        name=name,
        club=club,
        status=status,
        updated=datetime(2026, 11, 18, tzinfo=UTC),
        athlete_id=athlete_id,
        returns=date(2026, 11, 22),
    )


def test_a_regular_is_found_on_espns_report_by_his_club_and_name() -> None:
    barnes = Regular(player_id=STAR, name="Scottie Barnes", team="TOR")

    found = reported([barnes], [_report("Scottie Barnes"), _report("Scottie Barnes", club="BOS")])

    assert found == {STAR: Condition(status="O", returns=date(2026, 11, 22))}


def test_a_regular_is_found_on_espns_report_by_espns_id_first() -> None:
    barnes = Regular(player_id=STAR, name="Scottie Barnes", team="TOR", espn_id="9")

    assert STAR in reported([barnes], [_report("S. Barnes", athlete_id="9")])


def test_a_regular_cleared_by_espn_carries_nothing() -> None:
    barnes = Regular(player_id=STAR, name="Scottie Barnes", team="TOR")

    assert reported([barnes], [_report("Scottie Barnes", status="Active")]) == {}


def test_yahoos_status_stands_over_espns_and_espns_return_date_is_kept() -> None:
    barnes = Regular(player_id=STAR, name="Scottie Barnes", team="TOR")
    espn = {STAR: Condition(status="O", returns=date(2026, 11, 22))}

    found = conditions([barnes], [make_player("Scottie Barnes", team="TOR", status="GTD")], espn)

    assert found[STAR] == Condition(status="GTD", returns=date(2026, 11, 22))


def test_a_yahoo_row_at_another_club_or_shared_by_two_is_not_his() -> None:
    barnes = Regular(player_id=STAR, name="Scottie Barnes", team="TOR")
    espn = {STAR: Condition(status="O")}
    rows = [
        make_player("Scottie Barnes", team="BOS", status=""),
        make_player("Scottie Barnes", team="TOR", status="", key="a"),
        make_player("Scottie Barnes", team="TOR", status="GTD", key="b"),
    ]

    assert conditions([barnes], rows, espn)[STAR].status == "O"


def _together() -> dict[str, list[NBAGameLog]]:
    """A regular guard who sat the very games Barnes sat."""
    return {**_season(), GUARD: [_log(GUARD, d, 33.0) for d in (1, 2, 3, 4)]}


def test_two_regulars_who_missed_the_same_games_share_one_split_naming_both() -> None:
    (found,) = _splits(_together(), {**OUT, GUARD: Condition(status="O")})

    assert [m.regular.player_id for m in found.teammates] == [STAR, GUARD]
    assert found.cell() == "Barnes, Shead O"
    assert "Scottie Barnes" in found.label() and "Jamal Shead" in found.label()
    assert found.games == 4


def test_two_out_together_with_different_statuses_each_carry_their_own() -> None:
    (found,) = _splits(_together(), {**OUT, GUARD: Condition(status="INJ")})

    assert found.cell() == "Barnes O, Shead INJ"


def test_one_out_and_one_due_back_are_not_merged() -> None:
    found = _splits(_together(), {**OUT, GUARD: Condition(status="GTD")})

    assert [s.back for s in found] == [False, True]
