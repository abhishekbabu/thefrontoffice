"""Tests for how a basketball player reads in a table row and in his drawer: `nba/views.py`.

Covered through the provider, which hands each view Yahoo's averages for the player.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from support.espn import FakeESPN
from support.nba import FakeNBA, FakeSleeperProjections, FakeYahoo, make_player, nba_provider, toronto, yahoo_league

from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores, RecentForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.rules import ASSISTS, BLOCKS, CATEGORIES, POINTS, REBOUNDS
from thefrontoffice.adapters.outbound.competitions.nba.views import by_worth, cards, cell, compared
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport, NewsArticle
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    GameProjection,
    NBAGameLog,
    NBASeason,
    PlayerMeta,
    ScheduledGame,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    MovedPlayer,
    StatCategory,
    YahooLine,
    YahooPlayer,
    YahooTransaction,
)
from thefrontoffice.application.comparing import comparison
from thefrontoffice.domain.errors import NotFoundError, PlayerNotFoundError
from thefrontoffice.domain.models import PlayerDetail, PlayerQuery


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


# ── the drawer's tabs ───────────────────────────────────────────────────


def _log(day: int, opponent: str, team: str = "LAL", minutes: float = 30.0, **stats: float) -> NBAGameLog:
    return NBAGameLog(
        player_id="ab", date=f"2026-02-{day:02d}", opponent=opponent, stats=stats, team=team, minutes=minutes
    )


GUARD_LOG = [  # newest first, as Sleeper's logs are kept
    _log(8, "MIA", minutes=36, pts=30, reb=4, ast=8, fgm=11, fga=20, ftm=6, fta=7, to=3, tpm=2),
    _log(6, "BOS", minutes=32, pts=20, reb=5, ast=6, fgm=8, fga=16, ftm=4, fta=4, to=2, tpm=0),
    _log(4, "NYK", minutes=20, pts=8, reb=2, ast=3, fgm=3, fga=9, ftm=2, fta=2, to=1, tpm=0),
]
SLATE = [
    ScheduledGame(week=17, date="2026-02-04", home="LAL", away="NYK"),
    ScheduledGame(week=17, date="2026-02-06", home="BOS", away="LAL"),
    ScheduledGame(week=17, date="2026-02-08", home="LAL", away="MIA"),
    ScheduledGame(week=18, date="2026-02-10", home="LAL", away="BOS"),
    ScheduledGame(week=18, date="2026-02-12", home="MIA", away="LAL"),
]
DEFENSES = BoxScores(
    logs={
        "g1": [NBAGameLog(player_id="g1", date="2026-02-01", opponent="BOS", stats={"pts": 30.0}, team="NYK")],
        "g2": [NBAGameLog(player_id="g2", date="2026-02-01", opponent="MIA", stats={"pts": 10.0}, team="TOR")],
    },
    players={
        "g1": PlayerMeta(player_id="g1", name="Guard One", position="PG", team="NYK"),
        "g2": PlayerMeta(player_id="g2", name="Guard Two", position="PG", team="TOR"),
    },
)


def _guard(**kwargs: object) -> FakeNBA:
    nba = FakeNBA(
        slate=SLATE,
        games={"LAL": 2},
        logs={"A B": GUARD_LOG},
        scores=DEFENSES,
        stats={
            "A B": {"recent": RecentForm(games=3, line=nine_cat(GUARD_LOG)), "minutes": (36.0, 32.0, 20.0)},
            # The rest of the pool a value a game is scaled across: their roster and the wire.
            "Their Team One": {"recent": RecentForm(games=3, line=nine_cat(GUARD_LOG[2:]))},
            "Waiver One": {"recent": RecentForm(games=3, line=nine_cat(GUARD_LOG[1:2]))},
        },
    )
    nba.profiles = {
        "A B": PlayerMeta(player_id="ab", name="A B", position="PG", years_exp=3, age=24, number=11, college="Duke")
    }
    for name, value in kwargs.items():
        setattr(nba, name, value)
    return nba


def _opened(nba: FakeNBA | None = None) -> PlayerDetail:
    return nba_provider(FakeYahoo(roster=[make_player("A B", "PG", key="ab")]), nba=nba or _guard()).player("", "ab")


def test_the_drawer_offers_the_week_and_the_game_log_and_defers_the_tabs_that_cost_a_request() -> None:
    detail = _opened()

    assert detail.tabs == ["This week", "Game log", "Seasons", "History", "News"]
    assert (detail.deferred, detail.moves_tab) == (["Seasons", "History", "News"], "History")


def test_the_week_lists_his_games_and_what_his_next_opponent_gives_up_to_his_position() -> None:
    week = {s.label: s for s in _opened().groups[0].stats}

    assert week["Games"].value == "Tue 10 vs BOS · Thu 12 @ MIA"
    assert week["Next"].value == "vs BOS · the most to PGs (30.0 pts a game)"
    assert week["Next"].tone == "neutral"  # two defenses: the softest quarter of two holds nobody


def test_the_week_weighs_him_as_the_to_do_list_does_and_reads_his_minutes_and_usage_over_the_window() -> None:
    week = {s.label: s.value for s in _opened().groups[0].stats}

    assert week["G left"] == "2"
    assert float(week["Cat value/g"]) > 0
    assert week["Minutes/g"] == "29.3 last 3"
    assert week["Usage/g"] == f"{(20 + 0.44 * 7 + 3 + 16 + 0.44 * 4 + 2 + 9 + 0.44 * 2 + 1) / 3:.1f} last 3"


def test_a_window_longer_than_his_last_five_reads_both() -> None:
    long = [_log(day, "BOS", minutes=10.0 if day < 10 else 30.0) for day in range(16, 0, -1)]

    week = {s.label: s.value for s in _opened(_guard(logs={"A B": long})).groups[0].stats}

    assert week["Minutes/g"] == f"30.0 last 5 · {(7 * 30 + 9 * 10) / 16:.1f} last 6 wks"


def test_the_drawer_carries_sleepers_projection_a_game_and_who_he_is() -> None:
    rows = [
        GameProjection(
            player_id="ab",
            name="A B",
            team="LAL",
            opponent="BOS",
            date="2026-02-10",
            stats={"pts": 24.0, "reb": 7.0, "ast": 5.0, "tpm": 2.0, "fgm": 9.0, "fga": 18.0},
        )
    ]
    provider = nba_provider(
        FakeYahoo(roster=[make_player("A B", "PG", key="ab")]), nba=_guard(), sleeper=FakeSleeperProjections(rows=rows)
    )

    groups = {g.title: g for g in provider.player("", "ab").groups}

    projected = {s.label: s.value for s in groups["Projected line"].stats}
    assert (projected["PTS"], projected["FG%"], groups["Projected line"].note) == ("24.0", ".500", "1 game")
    assert [s.value for s in groups["Player"].stats] == ["3 seasons · age 24 · #11 · Duke"]


def test_a_projected_line_says_which_way_each_category_improves_so_a_comparison_can_mark_it() -> None:
    """Fewer turnovers is the better projection; more of everything else."""
    rows = [
        GameProjection(
            player_id="ab",
            name="A B",
            team="LAL",
            opponent="BOS",
            date="2026-02-10",
            stats={"pts": 24.0, "reb": 7.0, "ast": 5.0, "tpm": 2.0, "fgm": 9.0, "fga": 18.0, "to": 3.0},
        )
    ]
    provider = nba_provider(
        FakeYahoo(roster=[make_player("A B", "PG", key="ab")]), nba=_guard(), sleeper=FakeSleeperProjections(rows=rows)
    )

    [projected] = [g for g in provider.player("", "ab").groups if g.title == "Projected line"]

    better = {s.label: s.better for s in projected.stats}
    assert (better["TO"], better["PTS"], better["FG%"]) == ("lower", "higher", "higher")


def test_the_game_log_reads_every_game_oldest_first_home_or_away_with_his_shooting_made_over_tried() -> None:
    tables = {t.title: t for t in _opened().tables}

    log = tables["Game log"]
    assert log.tab == "Game log"
    assert [r.label for r in log.rows] == ["4 Feb vs NYK", "6 Feb @ BOS", "8 Feb vs MIA"]
    newest = dict(zip(log.columns, log.rows[-1].values, strict=True))
    assert (newest["Min"], newest["PTS"], newest["FG"], newest["FT"], newest["TO"]) == ("36", "30", "11/20", "6/7", "3")
    assert float(newest["Value"]) > float(dict(zip(log.columns, log.rows[0].values, strict=True))["Value"])


def test_the_week_shows_his_last_games_cut_to_value_minutes_and_points() -> None:
    recent = next(t for t in _opened().tables if t.title == "Recent games")

    assert (recent.tab, recent.columns) == ("This week", ["Value", "Min", "PTS"])
    assert len(recent.rows) == 3


def test_a_points_league_logs_each_games_fantasy_points() -> None:
    provider = nba_provider(
        FakeYahoo(roster=[make_player("A B", "PG", key="ab")], weights={"12": 1.0, "16": 1.5}),
        nba=_guard(),
        league=yahoo_league(scoring_type="headpoint"),
    )

    log = next(t for t in provider.player("", "ab").tables if t.title == "Game log")

    assert dict(zip(log.columns, log.rows[-1].values, strict=True))["FPTS"] == "42.0"


def test_a_game_log_without_the_schedule_reads_each_opponent_bare() -> None:
    log = next(t for t in _opened(_guard(slate=[])).tables if t.title == "Game log")

    assert log.rows[0].label == "4 Feb NYK"


def test_a_player_sleeper_has_no_games_of_has_no_game_log() -> None:
    assert _opened(_guard(logs={})).tables == []


def _tab(
    tab: str, nba: FakeNBA | None = None, yahoo: FakeYahoo | None = None, espn: FakeESPN | None = None
) -> PlayerDetail:
    yahoo = yahoo or FakeYahoo(roster=[make_player("A B", "PG", key="ab")])
    return nba_provider(yahoo, nba=nba or _guard(), espn=espn).player_tab("", "ab", tab)


def _season(games: int, pts: float, rank: int = 0) -> NBASeason:
    return NBASeason(
        player_id="ab",
        season="",
        games=games,
        minutes=games * 30.0,
        totals={"pts": pts, "fgm": pts / 2.5, "fga": pts / 1.25},
        position_rank=rank,
    )


def test_his_seasons_read_this_one_and_the_two_before_it_a_game_at_a_time() -> None:
    nba = _guard()
    nba.seasons = {("A B", "2026"): _season(10, 200.0, rank=12), ("A B", "2025"): _season(70, 1050.0)}

    [table] = _tab("Seasons", nba).tables

    assert (table.tab, table.columns) == ("Seasons", ["2026-27", "2025-26", "2024-25"])
    rows = {r.label: r.values for r in table.rows}
    assert rows["PTS"] == ["20.0", "15.0", "N/A"]
    assert rows["FG%"] == [".500", ".500", "N/A"]
    assert rows["Games"] == ["10", "70", "N/A"]
    assert rows["Position rank"] == ["#12", "N/A", "N/A"]


def test_seasons_that_will_not_load_leave_an_empty_tab() -> None:
    nba = _guard()
    nba.season_error = SleeperAPIError("down")

    assert _tab("Seasons", nba).tables == []


def test_his_history_is_every_league_move_he_was_part_of() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", "PG", key="ab")])
    yahoo.moves = [
        YahooTransaction(
            kind="add/drop",
            timestamp=1795079686,
            players=(
                MovedPlayer("ab", "A B", "PG", "LAL", kind="add", source="freeagents", destination="My Team"),
                MovedPlayer("cd", "C D", "C", "BOS", kind="drop", source="My Team", destination="waivers"),
            ),
        ),
        YahooTransaction(kind="add", timestamp=1795000000, players=(MovedPlayer("ef", "E F", "C", "MIA", kind="add"),)),
    ]

    detail = _tab("History", yahoo=yahoo)

    [move] = detail.moves
    assert (move.who, move.what, move.detail, move.is_mine) == ("My Team", "Add/drop", "+A B, -C D", True)


def test_his_news_is_his_clubs_feed_where_it_names_him() -> None:
    article = NewsArticle(article_id="1", published=datetime.now(UTC), headline="A B scores 30", url="https://espn/1")
    espn = FakeESPN(news={"LAL": [article, replace(article, article_id="2", headline="Lakers win")]})

    [group] = _tab("News", espn=espn).groups

    assert (group.tab, [s.value for s in group.stats], group.stats[0].url) == (
        "News",
        ["A B scores 30"],
        "https://espn/1",
    )


def test_a_tab_the_drawer_does_not_defer_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        _tab("This week")


def test_a_tab_for_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider(FakeYahoo()).player_tab("", "nobody", "News")


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
