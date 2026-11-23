"""Tests for a basketball player's line without a regular teammate: `nba/teammates.py`.

The club is TOR, eight games in. Scottie Barnes, its star, played the first
four and sat the last four; Jakob Poeltl, its centre, played all eight —
six points a game beside Barnes, twelve without him.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from support.nba import box_scores, game_log, make_player

from thefrontoffice.adapters.outbound.competitions.nba.form import MIN_FORM_GAMES, BoxScores
from thefrontoffice.adapters.outbound.competitions.nba.rules import Line
from thefrontoffice.adapters.outbound.competitions.nba.teammates import (
    KEEPER_HORIZON,
    LEFT_EARLY_MINUTES,
    REGULAR_MINUTES,
    RETURN_SOON,
    SEASON_GAMES,
    Condition,
    Regular,
    Returning,
    Teammates,
    conditions,
    espn_status,
    reported,
    shares_position,
)
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason

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


# ── a teammate due back soon ────────────────────────────────────────────

BIG, BACKUP = "d1", "r1"
DETROIT = {BIG: "Jalen Duren", BACKUP: "Paul Reed", GUARD: "Jamal Shead"}
POSITIONS = {BIG: "C", BACKUP: "C", GUARD: "PG"}
TODAY = date(2026, 11, 22)
DUE = {BIG: Condition(status="O", returns=date(2026, 11, 24))}
LAST_SEASON = {BIG: NBASeason(player_id=BIG, season="2025", games=70, minutes=70 * 30.0, totals={})}


def _detroit(together: int = 2) -> dict[str, list[NBAGameLog]]:
    """Duren played the first `together` games, under a regular's minutes, and has sat since; Reed played all ten."""
    return {
        BIG: [_log(BIG, d, 20.0, team="DET", pts=12) for d in range(1, together + 1)],
        BACKUP: [_log(BACKUP, d, 26.0, team="DET", pts=12, reb=8) for d in range(1, 11)],
        GUARD: [_log(GUARD, d, 18.0, team="DET", pts=4) for d in range(1, 11)],
    }


def _returning(
    logs: dict[str, list[NBAGameLog]] | None = None,
    known: dict[str, Condition] | None = None,
    before: dict[str, NBASeason] | None = None,
    position: str = "PF,C",
    name: str = "Paul Reed",
) -> list[Returning]:
    scores = box_scores(logs or _detroit(), DETROIT, team="DET", positions=POSITIONS)
    mates = Teammates(scores, before=LAST_SEASON if before is None else before)
    return mates.returning(make_player(name, team="DET", position=position), DUE if known is None else known, TODAY)


def test_a_starter_due_back_whom_he_has_barely_played_beside_is_flagged() -> None:
    """Two games together is no split, and that is the point: his role is the one the absence gave him."""
    (found,) = _returning()

    assert found.teammate.regular.name == "Jalen Duren"
    assert (found.without, found.alongside) == (8, 2)
    assert found.teammate.condition.returns == date(2026, 11, 24)
    assert "Duren" in found.cell() and "24 Nov" in found.cell()
    assert "Jalen Duren" in found.note() and "Jalen Duren" in found.prompt()
    assert found.stat().tone == "warning"


def test_a_teammate_hurt_early_is_a_regular_by_last_seasons_minutes() -> None:
    """Two games this season, at twenty minutes, say nothing of the starter he was all of last season."""
    this_season = Teammates(box_scores(_detroit(), DETROIT, team="DET")).regulars()
    with_last = Teammates(box_scores(_detroit(), DETROIT, team="DET"), before=LAST_SEASON).regulars()

    assert BIG not in {r.player_id for r in this_season}
    assert BIG in {r.player_id for r in with_last}


def test_a_short_last_season_does_not_make_a_regular() -> None:
    brief = {BIG: NBASeason(player_id=BIG, season="2025", games=SEASON_GAMES - 1, minutes=40.0 * 19, totals={})}

    assert _returning(before=brief) == []


@pytest.mark.parametrize(
    "known",
    [
        {BIG: Condition(status="O", returns=TODAY + RETURN_SOON + timedelta(days=1))},
        {BIG: Condition(status="O")},
        {BIG: Condition(returns=date(2026, 11, 24))},
    ],
)
def test_only_a_hurt_teammate_with_a_return_date_soon_is_flagged(known: dict[str, Condition]) -> None:
    """A return never guessed: no date, one past the week, or a teammate playing, is no warning."""
    assert _returning(known=known) == []


def test_a_teammate_at_another_position_is_not_flagged() -> None:
    assert _returning(name="Jamal Shead", position="PG") == []


def test_enough_games_beside_him_leave_it_to_the_split() -> None:
    assert _returning(_detroit(together=MIN_FORM_GAMES)) == []


def test_a_player_sleeper_cannot_place_at_his_club_gets_no_flag() -> None:
    mates = Teammates(box_scores(_detroit(), DETROIT, team="DET", positions=POSITIONS), before=LAST_SEASON)

    assert mates.returning(make_player("Paul Reed", team="BOS", position="C"), DUE, TODAY) == []


@pytest.mark.parametrize(
    ("eligible", "position", "shares"),
    [("PF,C", "C", True), ("SF,PF", "PF", True), ("G", "SG", True), ("PG,SG", "C", False), ("C", "", False)],
)
def test_a_position_is_shared_within_its_group(eligible: str, position: str, shares: bool) -> None:
    assert shares_position(eligible, position) is shares


# ── a role propped up by a teammate due back ────────────────────────
# Poeltl's split says twelve points a game without Barnes and six beside him: four games each side.

PROPPED_TODAY = date(2026, 11, 20)


def _points(line: Line) -> float | None:
    return line.get("PTS")


def _propped(logs: dict[str, list[NBAGameLog]] | None = None, known: dict[str, Condition] | None = None):
    mates = Teammates(_scores(logs or _season()))
    poeltl = make_player("Jakob Poeltl", team="TOR")
    return mates.propped(poeltl, OUT if known is None else known, PROPPED_TODAY, _points)


def test_a_split_clearly_better_without_a_teammate_due_back_props_his_role_and_says_how_much_is_left() -> None:
    (found,) = _propped()

    assert [m.regular.name for m in found.split.teammates] == ["Scottie Barnes"]
    assert found.returns == date(2026, 11, 22)
    assert found.cut == pytest.approx(0.5)  # six beside him over twelve without
    assert "Barnes" in found.cell() and "22 Nov" in found.cell()


def test_a_split_barely_better_without_him_props_nothing() -> None:
    logs = _season()
    logs[CENTRE] = [_log(CENTRE, d, 20.0, pts=11 if d <= 4 else 12) for d in range(1, 9)]

    assert _propped(logs) == []


def test_minutes_up_without_him_prop_his_role_whatever_the_points() -> None:
    logs = _season()
    logs[CENTRE] = [_log(CENTRE, d, 20.0 if d <= 4 else 26.0, pts=10) for d in range(1, 9)]

    (found,) = _propped(logs)

    assert found.cut == 1.0  # no fewer points beside him: nothing to take off a game


@pytest.mark.parametrize(
    "known",
    [
        {STAR: Condition(status="O")},  # no return dated: never guessed
        {STAR: Condition(status="O", returns=PROPPED_TODAY + KEEPER_HORIZON + timedelta(days=1))},
        {STAR: Condition(status="GTD", returns=date(2026, 11, 22))},  # due to play: the split already reads "with"
    ],
)
def test_only_a_teammate_ruled_out_and_dated_back_within_the_keeper_horizon_props_a_role(
    known: dict[str, Condition],
) -> None:
    assert _propped(known=known) == []
