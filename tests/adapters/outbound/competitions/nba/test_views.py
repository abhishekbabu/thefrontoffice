"""Tests for how a basketball player reads in a table row, and the drawer's averages beside it: `nba/views.py`.

Covered through the provider, which hands each view Yahoo's averages for the player. The drawer's tabs are
`test_drawer.py`.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from support.espn import FakeESPN
from support.nba import FakeNBA, FakeYahoo, make_player, nba_provider, toronto, yahoo_league

from thefrontoffice.adapters.outbound.competitions.nba.form import RecentForm
from thefrontoffice.adapters.outbound.competitions.nba.rules import ASSISTS, BLOCKS, CATEGORIES, POINTS, REBOUNDS
from thefrontoffice.adapters.outbound.competitions.nba.views import by_worth, cards, cell, compared
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    ScheduledGame,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    StatCategory,
    YahooLine,
    YahooPlayer,
)
from thefrontoffice.application.comparing import comparison
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import PlayerQuery


def test_a_roster_card_carries_the_row_and_what_a_row_cannot() -> None:
    """The columns are the table; the id and the tone are what a table needs
    and a column should not be."""
    yahoo = FakeYahoo(roster=[make_player("A B", "PF,C", "LAL", status="O", selected_position="IL")])

    card = nba_provider(yahoo).roster()[0]

    assert card.columns["Player"] == "A B"
    assert card.columns["Slot"] == "IL"
    assert card.player_id
    assert card.ruled_out


def test_a_game_time_decision_is_flagged_without_being_ruled_out() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", status="GTD")])

    card = nba_provider(yahoo).roster()[0]

    assert (card.columns["Status"], card.ruled_out) == ("GTD", False)


SEASON_LINE = YahooLine(
    stats={
        "12": "15.7",
        "15": "7.1",
        "16": "3.3",
        "17": "1.1",
        "18": "0.7",
        "10": "0.3",
        "5": "0.536",
        "8": "1.0",
        "19": "1.9",
    }
)
MONTH_LINE = YahooLine(stats={"12": "17.7", "15": "8.7", "16": "4.0", "5": "0.51", "8": "-", "19": "2.3"})


def _averaged(*players: YahooPlayer, season: YahooLine = SEASON_LINE, month: YahooLine = MONTH_LINE) -> FakeYahoo:
    """`players` on your roster, each with these averages over the season and the last month."""
    yahoo = FakeYahoo(roster=list(players))
    yahoo.lines = {
        Average.SEASON: {p.player_key: season for p in players},
        Average.LAST_MONTH: {p.player_key: month for p in players},
    }
    return yahoo


def test_the_drawer_shows_yahoos_season_and_last_month_in_every_category_the_league_scores() -> None:
    yahoo = _averaged(make_player("A B", key="ab"))

    detail = nba_provider(yahoo).player("", "ab")

    groups = {g.title: {s.label: s.value for s in g.stats} for g in detail.groups}
    season, month = groups["Season"], groups["Last 30 days"]
    assert list(season) == [c.label for c in CATEGORIES]
    assert (season["PTS"], season["FG%"], season["FT%"], season["TO"]) == ("15.7", ".536", "1.000", "1.9")
    assert (month["PTS"], month["FT%"], month["STL"]) == ("17.7", "—", "—")
    assert (detail.headline, detail.headline_label) == ("15.7", "pts/game, season")
    assert yahoo.averaged == [(("ab",), (Average.SEASON, Average.LAST_MONTH))]


def test_the_drawer_leaves_out_a_last_month_no_different_from_the_season() -> None:
    """Early in the season the two spans are the same games: one group says it."""
    yahoo = _averaged(make_player("A B", key="ab"), month=SEASON_LINE)

    titles = [g.title for g in nba_provider(yahoo).player("", "ab").groups]

    assert "Season" in titles
    assert "Last 30 days" not in titles


def test_the_drawer_heads_with_his_games_left_this_week_and_carries_his_photo_and_owner() -> None:
    player = replace(make_player("A B", key="ab"), image_url="https://cdn/ab.png", owner="My Team")
    detail = nba_provider(FakeYahoo(roster=[player]), nba=FakeNBA(games={"LAL": 3})).player("", "ab")

    assert detail.groups[0].title == "This week"
    assert {s.label: s.value for s in detail.groups[0].stats} == {"G left": "3"}
    assert (detail.image_url, detail.owner) == ("https://cdn/ab.png", "My Team")


CLEARS = date(2026, 2, 11)
"""A Wednesday inside the fake's matchup week, 9-15 Feb."""


def _clubs_play(*days: int) -> FakeNBA:
    played = [date(2026, 2, day) for day in days]
    slate = [ScheduledGame(week=0, date=day.isoformat(), home="LAL", away="BOS") for day in played]
    return FakeNBA(dated={"LAL": played}, slate=slate)


def test_the_drawer_on_a_player_on_waivers_says_when_he_clears_and_counts_only_the_games_after() -> None:
    waiting = make_player("A B", key="ab", waiver_date=CLEARS)

    detail = nba_provider(FakeYahoo(available=[waiting]), nba=_clubs_play(10, 11, 12, 14)).player("", "ab")

    week = {s.label: s.value for s in detail.groups[0].stats}
    assert "Wed 11 Feb" in detail.owner
    assert week["G left"] == "2"
    assert week["Games"].count("vs BOS") == 2  # the 12th and 14th


def test_the_drawer_on_a_free_agent_counts_every_game_his_club_has_left() -> None:
    free = make_player("A B", key="ab")

    detail = nba_provider(FakeYahoo(available=[free]), nba=_clubs_play(10, 11, 12, 14)).player("", "ab")

    assert "clears" not in detail.owner
    assert {s.label: s.value for s in detail.groups[0].stats}["G left"] == "4"


def test_a_row_on_waivers_says_when_he_clears_them_and_a_free_agents_says_nothing() -> None:
    waiting = make_player("Waits", waiver_date=CLEARS)
    hurt = make_player("Hurt", status="O", waiver_date=CLEARS)
    free = make_player("Free")

    rows = {
        r.columns["Player"]: r for r in cards([waiting, hurt, free], {}, {"hurt": date(2026, 2, 20)}, by_points=True)
    }

    assert "11 Feb" in rows["Waits"].columns["Status"]
    assert "Wed 11 Feb" in rows["Waits"].notes["Status"]
    assert not rows["Waits"].ruled_out
    assert rows["Hurt"].columns["Status"].startswith("O")
    assert "11 Feb" in rows["Hurt"].columns["Status"]
    assert "20 Feb" in rows["Hurt"].notes["Status"]
    assert "Wed 11 Feb" in rows["Hurt"].notes["Status"]
    assert (rows["Free"].columns["Status"], rows["Free"].notes) == ("", {})


def test_the_drawer_names_his_status_in_words_rather_than_yahoos_code() -> None:
    """'O' alone in a header reads as the figure zero."""
    detail = nba_provider(FakeYahoo(roster=[make_player("A B", key="ab", status="O")])).player("", "ab")

    assert (detail.note, detail.tone) == ("Out", "warning")


def test_a_drawer_without_a_matchup_this_week_has_no_week_group() -> None:
    detail = nba_provider(FakeYahoo(roster=[make_player("A B", key="ab")], matchup_dates=None)).player("", "ab")

    assert "This week" not in [g.title for g in detail.groups]


def test_a_drawer_yahoo_has_no_averages_for_says_so_and_still_opens() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])
    yahoo.averages_error = YahooAPIError("down")

    detail = nba_provider(yahoo).player("", "ab")

    assert (detail.headline, detail.headline_label) == ("", "No games this season")
    assert {"Season", "Last 30 days"}.isdisjoint(g.title for g in detail.groups)


def test_two_players_compare_with_fewer_turnovers_and_more_of_everything_else_best() -> None:
    yahoo = _averaged(make_player("A B", key="ab"))
    yahoo.roster_players.append(make_player("C D", key="cd"))
    yahoo.lines[Average.SEASON]["cd"] = YahooLine(stats={"12": "12.0", "19": "1.0", "5": ".600"})
    provider = nba_provider(yahoo)

    tables = comparison([provider.player("", "ab"), provider.player("", "cd")]).tables
    [season] = [table for table in tables if table.title == "Season"]

    best = {row.label: row.best for row in season.rows}
    assert (best["PTS"], best["TO"], best["FG%"]) == ([0], [1], [1])


def test_a_category_row_carries_every_category_the_league_scores_as_yahoo_prints_it() -> None:
    """Sorted on its numbers, since as text 9.0 points sits above 20.0; a rate reads '.510', as every page prints it."""
    card = nba_provider(_averaged(make_player("A B"))).roster()[0]

    scored = [c.label for c in CATEGORIES]
    assert [column for column in card.columns if column in scored] == scored
    assert (card.columns["PTS"], card.columns["FG%"], card.columns["FT%"], card.columns["STL"]) == (
        "17.7",
        ".510",
        "—",
        "—",
    )
    assert (card.values["PTS"], card.values["FG%"]) == (17.7, 0.51)
    assert "FT%" not in card.values


def test_a_points_row_carries_fantasy_points_and_the_three_counts_a_row_has_room_for() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")], weights={"12": 1.0})
    yahoo.lines = {Average.LAST_MONTH: {"ab": YahooLine(stats={"12": "17.7", "15": "8.7", "16": "4.0"}, points="30.4")}}

    card = nba_provider(yahoo, league=yahoo_league(scoring_type="headpoint")).roster()[0]

    assert card.values == {"FPTS": 30.4, "PTS": 17.7, "REB": 8.7, "AST": 4.0}
    assert "Value" not in card.columns


def test_a_points_table_lists_the_most_fantasy_points_a_game_first() -> None:
    yahoo = FakeYahoo(roster=[make_player("Low", key="low"), make_player("High", key="high")], weights={"12": 1.0})
    yahoo.lines = {Average.LAST_MONTH: {"low": YahooLine(points="10.0"), "high": YahooLine(points="40.0")}}

    roster = nba_provider(yahoo, league=yahoo_league(scoring_type="headpoint")).roster()

    assert [card.columns["Player"] for card in roster] == ["High", "Low"]


def test_a_category_table_carries_each_players_value_a_game_and_lists_the_best_first() -> None:
    """Read on the to-do list's own scale, so the wire and the list agree on a player."""
    yahoo = FakeYahoo(
        roster=[make_player("Bench Guy", key="bench"), make_player("Star Guy", key="star")],
        available=[make_player("Wire Guy", key="wire")],
    )
    nba = FakeNBA(
        stats={
            "Bench Guy": {"recent": RecentForm(games=10, line={"PTS": 4.0, "REB": 2.0})},
            "Star Guy": {"recent": RecentForm(games=10, line={"PTS": 30.0, "REB": 10.0})},
            "Wire Guy": {"recent": RecentForm(games=10, line={"PTS": 12.0, "REB": 5.0})},
        }
    )
    provider = nba_provider(yahoo, nba=nba)

    roster = provider.roster()
    wire = provider.free_agents("", PlayerQuery()).players

    assert [card.columns["Player"] for card in roster] == ["Star Guy", "Bench Guy"]
    assert roster[0].values["Value"] > roster[1].values["Value"]
    assert wire[0].columns["Value"] != "—"


def test_a_table_without_a_matchup_this_week_dashes_its_values() -> None:
    card = nba_provider(FakeYahoo(roster=[make_player("A B")], matchup_dates=None)).roster()[0]

    assert card.columns["Value"] == "—"
    assert "Value" not in card.values


def test_a_table_whose_week_will_not_load_dashes_its_values_and_still_opens() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B")])
    yahoo.wire_error = YahooAPIError("down")

    card = nba_provider(yahoo).roster()[0]

    assert card.columns["Value"] == "—"


def test_the_wire_offers_one_filter_per_position_and_keeps_anybody_eligible_there() -> None:
    yahoo = FakeYahoo(
        available=[
            make_player("Combo Guard", "PG,SG", key="combo"),
            make_player("Big", "PF,C", key="big"),
            make_player("Wing", "SF", key="wing"),
        ]
    )
    yahoo.positions = ["PG", "SG", "G", "SF", "PF", "F", "C", "Util", "BN", "IL"]
    provider = nba_provider(yahoo)

    page = provider.free_agents("", PlayerQuery())

    assert page.positions == ["PG", "SG", "SF", "PF", "C", "G", "F"]
    names = {
        position: {p.columns["Player"] for p in provider.free_agents("", PlayerQuery(position=position)).players}
        for position in ("SG", "C", "F")
    }
    assert names == {"SG": {"Combo Guard"}, "C": {"Big"}, "F": {"Big", "Wing"}}


def test_a_league_without_combined_slots_offers_no_combined_filter() -> None:
    page = nba_provider(FakeYahoo(available=[make_player("Combo Guard", "PG,SG")])).free_agents("", PlayerQuery())

    assert page.positions == ["PG", "SG"]


def test_a_rivals_roster_carries_his_players_averages_too() -> None:
    yahoo = FakeYahoo()
    yahoo.lines = {Average.LAST_MONTH: {"their-team-one": MONTH_LINE}}

    [card] = nba_provider(yahoo).roster_of("", "t.2")

    assert card.columns["PTS"] == "17.7"


def test_the_wire_reads_the_averages_its_own_pages_carry_without_another_request() -> None:
    carried = make_player("Free Man", key="fa", stats={"12": "9.5"}, coverage=Average.LAST_MONTH)
    yahoo = FakeYahoo(available=[carried])

    [card] = nba_provider(yahoo).free_agents("", PlayerQuery()).players

    assert card.columns["PTS"] == "9.5"
    assert yahoo.averaged == []


def test_the_drawer_opens_for_a_player_on_nobodys_roster_or_a_rivals() -> None:
    """The wire and other managers' rosters open the same drawer as your own."""
    yahoo = FakeYahoo(available=[make_player("Free Man", key="fa")])
    provider = nba_provider(yahoo)

    assert provider.player("", "fa").name == "Free Man"
    assert provider.player("", "their-team-one").name == "Their Team One"


def test_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider().player("", "nobody")


def test_an_average_is_a_dash_when_there_is_none() -> None:
    """Out of season there is no line to show, and a zero would read as a bad
    one rather than an absent one."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    yahoo.averages_error = YahooAPIError("down")
    card = nba_provider(yahoo).roster()[0]

    assert card.columns["PTS"] == "—"
    assert "PTS" not in card.values


# ── teammates out ───────────────────────────────────────────────────────

POELTL = make_player("Jakob Poeltl", "C", "TOR", key="poeltl")
BARNES_OUT = [
    InjuryReport(
        name="Scottie Barnes",
        club="TOR",
        status="Out",
        updated=datetime(2026, 11, 18, tzinfo=UTC),
        returns=date(2026, 11, 22),
    )
]


def test_the_wire_shows_whose_absence_a_free_agent_gains_from_with_both_figures_on_hover() -> None:
    yahoo = FakeYahoo(available=[POELTL, make_player("Somebody Else", key="else")])
    provider = nba_provider(yahoo, nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT))

    poeltl, other = provider.free_agents("", PlayerQuery()).players

    assert poeltl.columns[WITHOUT_COLUMN] == "Barnes O"
    assert poeltl.notes[WITHOUT_COLUMN].startswith("Without Scottie Barnes")
    assert "12.0" in poeltl.notes[WITHOUT_COLUMN]
    assert other.columns[WITHOUT_COLUMN] == "—"
    assert WITHOUT_COLUMN not in other.notes


def test_a_roster_has_no_without_column() -> None:
    provider = nba_provider(
        FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT)
    )

    assert WITHOUT_COLUMN not in provider.roster()[0].columns


def test_the_drawer_lists_his_line_without_each_teammate_out() -> None:
    provider = nba_provider(
        FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=FakeESPN(injuries=BARNES_OUT)
    )

    [group] = [g for g in provider.player("", "poeltl").groups if g.title == "Teammates"]

    [row] = group.stats
    assert row.label.startswith("Without Scottie Barnes")
    assert row.tone == "good"


def test_a_teammate_who_lately_sat_counts_when_espns_report_will_not_load() -> None:
    espn = FakeESPN(injuries_error=ESPNAPIError("down"))
    provider = nba_provider(FakeYahoo(roster=[POELTL]), nba=FakeNBA(scores=toronto()), espn=espn)

    [group] = [g for g in provider.player("", "poeltl").groups if g.title == "Teammates"]

    assert group.stats[0].label.startswith("With Scottie Barnes")


def test_a_drawer_with_no_teammate_out_has_no_teammates_group() -> None:
    provider = nba_provider(FakeYahoo(roster=[make_player("A B", key="ab")]), nba=FakeNBA(scores=toronto()))

    assert "Teammates" not in [g.title for g in provider.player("", "ab").groups]


READING = Reading(
    player=make_player("A B"),
    line={POINTS.label: 22.1, REBOUNDS.label: 8.3, ASSISTS.label: 4.0, BLOCKS.label: 1.0},
    per_game=41.5,
    games=3,
    average=YahooLine(stats={"12": "12.7", "15": "2.0", "16": "3.3"}, points="30.15"),
)


def test_a_points_league_row_reads_games_left_and_yahoos_fantasy_points_a_game() -> None:
    """Yahoo's figure, as his table row and his drawer show it, not the one the week is weighed on."""
    assert cell(READING, by_points=True) == "3G · 30.15 fpts/g"


def test_a_category_league_row_reads_games_left_and_yahoos_line_a_row_has_room_for() -> None:
    assert cell(READING, by_points=False) == "3G · 12.7p 2.0r 3.3a"


def test_a_row_without_a_schedule_reads_the_game_alone() -> None:
    assert cell(replace(READING, games=None), by_points=True) == "30.15 fpts/g"


def test_a_row_without_yahoos_averages_reads_its_games_alone() -> None:
    assert cell(replace(READING, average=None), by_points=False) == "3G"


def test_a_category_item_names_what_drags_a_player_in_yahoos_figures_or_the_weighed_ones() -> None:
    weak = replace(
        READING,
        line={**(READING.line or {}), "FG%": 0.38, "TO": 2.9},
        weak=(StatCategory("5", "FG%"), StatCategory("19", "TO", fewer_wins=True)),
        average=YahooLine(stats={"5": "0.38"}),
    )

    [player] = compared([("out", "starter", weak)], False)

    figures = {f.label: f for f in player.figures}
    assert figures["Weak in"].value == "FG% .380 · 2.9 TO"
    assert figures["Cat value/g"].hint
    assert "FPTS" not in figures


def test_a_player_weak_nowhere_reads_a_dash() -> None:
    [player] = compared([("out", "starter", READING)], False)

    assert {f.label: f.value for f in player.figures}["Weak in"] == "—"


def test_a_points_item_shows_yahoos_fantasy_points_beside_the_value_it_is_weighed_on() -> None:
    [player] = compared([("in", "bench", READING)], True)

    figures = {f.label: f.value for f in player.figures}
    assert (figures["Pts value/g"], figures["FPTS"]) == ("41.5", "30.15")
    assert "Cat value/g" not in figures


def test_players_compared_carry_the_same_rows_with_a_dash_where_one_has_none() -> None:
    known, unknown = replace(READING, minutes=30.0), replace(READING, per_game=None, games=None)

    rows = [
        [(f.label, f.value) for f in p.figures]
        for p in compared([("in", "bench", known), ("out", "starter", unknown)], True)
    ]

    assert [label for label, _ in rows[0]] == [label for label, _ in rows[1]]
    assert dict(rows[0])["Week"] == "124.5"
    assert dict(rows[1])["Week"] == "—"


def test_games_left_read_as_a_floor_while_the_weeks_schedule_is_not_final() -> None:
    pending = replace(READING, provisional=True)

    assert cell(pending, by_points=True) == "3+G · 30.15 fpts/g"
    [_in] = compared([("in", "bench", pending)], True)
    assert {f.label: f.value for f in _in.figures}["G left"] == "3+"


def test_a_player_compared_carries_when_espn_expects_him_back() -> None:
    hurt, fit = replace(READING, back=date(2026, 12, 3)), READING

    rows = [
        {f.label: f.value for f in p.figures} for p in compared([("in", "bench", hurt), ("out", "starter", fit)], True)
    ]

    assert (rows[0]["Back"], rows[1]["Back"]) == ("~3 Dec", "—")


def _wire(*week: tuple[str, str, float | None, int | None]) -> list[str]:
    """The wire `by_worth` orders, each player `(name, Yahoo status, value a game, games he can play)`."""
    players = [make_player(name, status=status) for name, status, _, _ in week]
    readings = {
        p.player_key: Reading(player=p, line={}, per_game=per, games=games)
        for p, (_, _, per, games) in zip(players, week, strict=True)
    }
    rows = cards(players, {}, {}, by_points=False, readings=readings)
    return [row.columns["Player"] for row in by_worth(rows, readings)]


def test_a_player_ruled_out_this_week_sinks_below_one_who_plays_but_stays_on_the_wire() -> None:
    """Out until after the week, the best value a game adds nothing to it."""
    order = _wire(("Out", "O", 12.6, 0), ("Plays", "", 9.0, 2))

    assert order == ["Plays", "Out"]


def test_a_player_back_in_time_counts_the_games_after_his_return() -> None:
    assert _wire(("Steady", "", 9.0, 1), ("Back Sat", "O", 12.0, 2)) == ["Back Sat", "Steady"]


def test_a_game_time_decision_is_discounted_not_dropped() -> None:
    order = _wire(("Sure", "", 9.5, 3), ("Doubt", "GTD", 10.0, 3), ("Lesser", "", 9.0, 3))

    assert order == ["Sure", "Doubt", "Lesser"]  # 28.5, then 28 (his next game at 0.8), then 27


def test_with_no_games_left_those_who_can_play_still_lead_then_a_games_value() -> None:
    order = _wire(("Out", "O", 12.6, 0), ("Better", "", 9.0, 0), ("Worse", "", 8.0, 0))

    assert order == ["Better", "Worse", "Out"]


def test_a_player_whose_week_cannot_be_read_follows_in_his_own_order() -> None:
    order = _wire(("Unread", "", None, 3), ("Unscheduled", "", 9.0, None), ("Read", "", 5.0, 1))

    assert order == ["Read", "Unscheduled", "Unread"]  # the rest as the table ranks them: by value a game, blanks last


def test_a_wire_row_without_his_minutes_or_his_rostered_share_shows_dashes() -> None:
    """Shown where others on the page have them: a dash, not a nought that reads as nobody rostering him."""
    held = replace(make_player("Held", key="held"), rostered=40.0, rostered_change=1.0)
    [bare, _] = sorted(
        cards([make_player("Bare", key="bare"), held], {}, {}, by_points=False, wire=True),
        key=lambda card: card.player_id,
    )

    assert (bare.columns["Min"], bare.columns["Rost"]) == ("—", "—")
    assert "Min" not in bare.values and "Rost" not in bare.values
