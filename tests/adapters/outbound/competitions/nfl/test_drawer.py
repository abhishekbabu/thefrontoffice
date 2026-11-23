"""Tests for the drawer that opens on a football player: `nfl/drawer.py`.

Its week, projected line, profile, injury, recent weeks, game log and seasons,
read through the provider the way a page opens him.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from support.espn import FakeESPN
from support.nfl import (
    DEFAULT_PROJECTIONS,
    SEASON_SCHEDULE,
    FakeSleeper,
    game_line,
    nfl_provider,
)

from thefrontoffice.adapters.outbound.competitions.nfl.rules import status_word
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    SeasonStats,
    SleeperLeague,
)
from thefrontoffice.domain.models import PlayerDetail, Stat

LINE = {
    "pass_att": 0.4,
    "rush_att": 0.1,
    "rush_yd": 0.7,
    "rush_td": 0.01,
    "rec_tgt": 6.2,
    "rec": 4.1,
    "rec_yd": 52.3,
    "rec_td": 0.3,
    "fum_lost": 0.04,
}


def _drawer(player_id: str, client: FakeSleeper | None = None) -> PlayerDetail:
    projections = {pid: replace(p, stats=LINE) for pid, p in DEFAULT_PROJECTIONS.items()}
    return nfl_provider(client or FakeSleeper(projections=projections)).player("L1", player_id)


def _group(detail: PlayerDetail, title: str) -> list[Stat]:
    [group] = [g for g in detail.groups if g.title == title]
    return group.stats


def test_the_drawer_opens_on_this_week_and_files_every_group_and_table_under_a_tab_it_offers() -> None:
    detail = _drawer("qb1")

    assert detail.tabs[0] == "This week"
    assert {g.tab for g in detail.groups} <= {"", *detail.tabs}
    assert {t.tab for t in detail.tables} <= set(detail.tabs)


def test_a_receivers_projected_line_is_his_receiving_alone() -> None:
    stats = _group(_drawer("wr9"), "Projected line")

    assert [s.label for s in stats] == ["Targets", "Receptions", "Rec yards", "Rec TD"]


def test_a_running_backs_projected_line_drops_what_rounds_to_nothing() -> None:
    stats = {s.label: s.value for s in _group(_drawer("rb1"), "Projected line")}

    assert "Rush TD" not in stats  # 0.01
    assert stats["Carries"] == "0.1" and stats["Rec yards"] == "52.3"
    assert "Pass att" not in stats and "Fumbles lost" not in stats


def test_a_quarterbacks_projected_line_is_passing_and_rushing() -> None:
    labels = [s.label for s in _group(_drawer("qb1"), "Projected line")]

    assert labels == ["Pass att", "Carries", "Rush yards"]


def test_every_projected_figure_improves_upward_but_interceptions() -> None:
    projections = {"qb1": replace(DEFAULT_PROJECTIONS["qb1"], stats={"pass_yd": 250.0, "pass_int": 0.8})}
    stats = {s.label: s.better for s in _group(_drawer("qb1", FakeSleeper(projections=projections)), "Projected line")}

    assert stats == {"Pass yards": "higher", "Interceptions": "lower"}


def test_who_he_is_reads_on_two_lines() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_nfl_players()
    client.players_catalog = {
        **catalog,
        "rb1": replace(catalog["rb1"], depth_chart_order=2, years_exp=3, age=24, number=11, college="Alabama"),
    }

    stats = {s.label: s.value for s in _group(_drawer("rb1", client), "Player")}

    assert stats == {"Depth chart": "2", "Profile": "3 seasons · age 24 · #11 · Alabama"}


@pytest.mark.parametrize(("years", "said"), [(0, "rookie"), (1, "1 season")])
def test_experience_reads_as_said(years: int, said: str) -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_nfl_players()
    client.players_catalog = {**catalog, "rb1": replace(catalog["rb1"], years_exp=years)}

    stats = {s.label: s.value for s in _group(_drawer("rb1", client), "Player")}

    assert stats["Profile"] == said


def test_the_first_tab_shows_his_last_five_weeks_of_points_snaps_and_touches() -> None:
    lines = [
        game_line(
            "rb1",
            week,
            position="RB",
            team="BUF",
            opponent="MIA",
            off_snp=snaps,
            tm_off_snp=100,
            rush_att=week,
            rec_tgt=1,
            rec_yd=9,
            pts_ppr=float(week),
        )
        for week, snaps in enumerate((10, 15, 21, 40, 82, 90, 95), start=1)
    ]
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, game_lines=lines)
    client.week = 8

    detail = _drawer("rb1", client)
    [recent] = [t for t in detail.tables if t.title == "Recent weeks"]

    assert recent.tab == detail.tabs[0]
    assert recent.columns == ["Pts", "Snaps", "Car", "Tgt"]
    assert [row.label.split()[0] for row in recent.rows] == ["W3", "W4", "W5", "W6", "W7"]
    assert [row.values[1] for row in recent.rows] == ["21%", "40%", "82%", "90%", "95%"]


def test_a_player_who_has_not_played_has_no_recent_weeks() -> None:
    assert all(t.title != "Recent weeks" for t in _drawer("rb1").tables)


def test_a_seasons_position_rank_improves_downward() -> None:
    stats = SeasonStats(
        player_id="qb1",
        season="2025",
        games=16,
        points={"pts_ppr": 300.0},
        position_rank=4,
        splits={"pass_yd": 4000.0, "pass_int": 9.0},
    )
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats={"2025": {"qb1": stats}})

    [table] = [t for t in _drawer("qb1", client).tables if t.title == "By season"]
    better = {row.label: row.better for row in table.rows}

    assert better["Position rank"] == "lower" and better["Interceptions"] == "lower"
    assert better["Per game"] == "higher" and better["Passing yards"] == "higher"


def test_a_receivers_recent_weeks_leave_out_the_carries_he_never_gets() -> None:
    line = game_line("wr9", 1, position="WR", team="NYJ", off_snp=50, tm_off_snp=60, rec_tgt=7, pts_ppr=12.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, game_lines=[line])

    [recent] = [t for t in _drawer("wr9", client).tables if t.title == "Recent weeks"]

    assert recent.columns == ["Pts", "Snaps", "Tgt"]


# ── the seasons behind the projection ───────────────────────────────────


def _stats(pid: str, season: str, *, games: int, ppr: float, rank: int = 0, **splits: float) -> SeasonStats:
    return SeasonStats(
        player_id=pid,
        season=season,
        games=games,
        points={"pts_ppr": ppr, "pts_half_ppr": ppr - 10, "pts_std": ppr - 20},
        position_rank=rank,
        splits=splits,
    )


HISTORY = {
    "2025": {"qb1": _stats("qb1", "2025", games=16, ppr=320.0, rank=4, pass_yd=4200.0, pass_td=30.0)},
    "2024": {"qb1": _stats("qb1", "2024", games=12, ppr=210.0, rank=14, pass_yd=2800.0, pass_td=18.0)},
}


def _table(client: FakeSleeper, player_id: str = "qb1") -> dict[str, Any]:
    """The by-season table as {row label: values}, columns newest first."""
    [table] = [t for t in nfl_provider(client).player("L1", player_id).tables if t.title == "By season"]
    return {"__columns__": table.columns, **{row.label: row.values for row in table.rows}}


def test_the_seasons_are_columns_so_they_can_be_read_across() -> None:
    """A stack makes you hold last year's yards in your head while scrolling
    to this year's."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    assert _table(client)["__columns__"] == ["2026", "2025", "2024"]


def test_a_season_nobody_has_played_yet_reports_nothing() -> None:
    """The fake sits in the regular season but has no 2026 totals, which is
    every August: a column of noughts claims answers it does not have."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert table["Total"][0] == "N/A"
    assert table["Games"][0] == "N/A"


def test_a_finished_season_is_scored_per_game_not_only_as_a_total() -> None:
    """A total mostly measures availability: 12 games is not a worse week."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert table["Per game"][2] == "17.50"  # 210 points over 12 games
    assert table["Games"][2] == "12"


def test_a_season_is_scored_in_the_leagues_own_currency() -> None:
    """75 receptions is 37.5 points between full PPR and standard."""
    league = SleeperLeague(
        league_id="L1",
        name="Sunday Money",
        season="2026",
        total_rosters=12,
        scoring_format="pts_std",
        roster_positions=["QB", "RB", "BN"],
    )
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY, league=league)

    assert _table(client)["Total"][1] == "300.00"  # pts_std, not pts_ppr


def test_a_split_a_position_never_records_has_no_row_at_all() -> None:
    """A running back has no completion percentage, and a whole row of N/A is
    a row of nothing."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert "Passing yards" in table
    assert "Receptions" not in table


def test_a_rookie_gets_no_table_rather_than_a_table_of_nothing() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats={})

    assert nfl_provider(client).player("L1", "qb1").tables == []


def test_a_failed_history_lookup_does_not_take_the_player_down() -> None:
    """The week was already fetched and is still true."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats_error=SleeperAPIError("down"))

    detail = nfl_provider(client).player("L1", "qb1")

    assert detail.name == "Star QB"
    assert detail.tables == []


# ── the season game by game ─────────────────────────────────────────────

# Buffalo away in week 1, idle in week 2, at home in week 3 — the week in progress.
BUFFALO_SCHEDULE = [
    ScheduledGame(week=1, date="2026-09-13", home="MIA", away="BUF"),
    ScheduledGame(week=2, date="2026-09-20", home="KC", away="LV"),
    ScheduledGame(week=3, date="2026-09-27", home="BUF", away="NYJ"),
]


def _rb_week(week: int, opponent: str, **stats: float) -> NFLGameLine:
    return game_line("rb1", week, position="RB", team="BUF", opponent=opponent, **stats)


def _log(client: FakeSleeper, player_id: str = "rb1") -> dict[str, Any]:
    """The game log as {row label: values}, plus its columns."""
    [table] = [t for t in nfl_provider(client).player("L1", player_id).tables if t.title == "Game log"]
    return {"__columns__": table.columns, **{row.label: row.values for row in table.rows}}


def test_each_game_is_a_row_leading_with_the_points_it_scored_in_the_leagues_currency() -> None:
    line = _rb_week(1, "MIA", gp=1, off_snp=45, tm_off_snp=60, rush_att=18, pts_ppr=21.4, pts_std=17.4)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])

    log = _log(client)

    assert log["__columns__"][0] == "Pts"
    assert log["W1 @ MIA"][0] == "21.40"


def test_a_game_reads_its_snap_share_and_box_score() -> None:
    line = _rb_week(1, "MIA", gp=1, off_snp=45, tm_off_snp=60, rush_att=18, rush_yd=96, rec=3, pts_ppr=21.4)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])

    log = _log(client)
    row = dict(zip(log["__columns__"], log["W1 @ MIA"], strict=True))

    assert (row["Snaps"], row["Car"], row["Rush yd"], row["Rec"], row["Rec TD"]) == ("75%", "18", "96", "3", "0")


def test_a_running_back_is_logged_without_passing_columns() -> None:
    line = _rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])

    assert "Cmp/Att" not in _log(client)["__columns__"]


def test_a_kicker_is_logged_as_kicks_made_of_tried() -> None:
    line = game_line("k1", 1, position="K", team="BUF", opponent="MIA", gp=1, fgm=2, fga=3, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])
    client.players_catalog = {
        **client.get_nfl_players(),
        "k1": PlayerMeta(player_id="k1", name="Boot", position="K", team="BUF"),
    }

    log = _log(client, "k1")

    assert dict(zip(log["__columns__"], log["W1 @ MIA"], strict=True))["FG"] == "2/3"


def test_a_bye_reads_as_a_bye_rather_than_as_a_game_missed() -> None:
    line = _rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])

    assert set(_log(client)["W2 bye"]) == {"N/A"}


def test_a_finished_game_he_sat_out_reads_as_one_he_did_not_play() -> None:
    """A gap is part of the record: an average over the games he played hides it."""
    schedule = [*BUFFALO_SCHEDULE, ScheduledGame(week=2, date="2026-09-20", home="BUF", away="NE")]
    line = _rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=schedule, game_lines=[line])

    assert set(_log(client)["W2 vs NE · DNP"]) == {"N/A"}


def test_a_week_whose_lines_would_not_load_is_no_row_rather_than_a_game_missed() -> None:
    schedule = [*BUFFALO_SCHEDULE, ScheduledGame(week=2, date="2026-09-20", home="BUF", away="NE")]
    line = _rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=schedule, game_lines=[line])
    client.unloaded_weeks = {2}

    assert [label for label in _log(client) if label.startswith("W")] == ["W1 @ MIA"]


def test_this_weeks_game_has_no_row_until_he_has_played_in_it() -> None:
    """Until then it has not been played, and a "did not play" would be a guess."""
    line = _rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0)
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE, game_lines=[line])

    assert not any(label.startswith("W3") for label in _log(client))


def test_the_log_counts_the_games_his_averages_do() -> None:
    """A row filed for a game he never took a snap in is no game in the log, as it is none in his role."""
    schedule = [*BUFFALO_SCHEDULE, ScheduledGame(week=2, date="2026-09-20", home="BUF", away="NE")]
    lines = [_rb_week(1, "MIA", gp=1, off_snp=30, tm_off_snp=60, pts_ppr=8.0), _rb_week(2, "NE", gp=1)]
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=schedule, game_lines=lines)

    assert set(_log(client)["W2 vs NE · DNP"]) == {"N/A"}


def test_a_player_who_has_not_played_a_game_has_no_log() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=BUFFALO_SCHEDULE)

    assert all(t.title != "Game log" for t in nfl_provider(client).player("L1", "rb1").tables)


def test_game_lines_that_will_not_load_do_not_take_the_player_down() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.unloaded_weeks = {1, 2, 3}

    detail = nfl_provider(client).player("L1", "rb1")

    assert detail.name == "Good RB"
    assert all(t.title != "Game log" for t in detail.tables)


def test_a_player_carries_a_portrait_from_sleepers_own_cdn() -> None:
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "qb1")

    assert detail.image_url.endswith("/qb1.jpg")


def test_the_drawer_shows_what_the_projection_rests_on() -> None:
    lines = [
        NFLGameLine(
            player_id="rb1",
            week=w,
            team="BUF",
            opponent="MIA",
            position="RB",
            stats={"off_snp": 45, "tm_off_snp": 60, "rush_att": 16, "rec_tgt": 3, "pts_ppr": 17},
        )
        for w in (1, 2)
    ]
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS, game_lines=lines)).player("L1", "rb1")

    [group] = [g for g in detail.groups if g.title.startswith("Week")]
    stats = {stat.label: stat.value for stat in group.stats}
    # Who he plays and what that defense allows, on one row.
    assert stats["Opponent"].startswith("vs ")
    assert "·" in stats["Opponent"]
    assert "Matchup" not in stats
    assert stats["Snap share, last 2"] == "75%"
    assert stats["Carries a game"] == "16.0"
    assert stats["Targets a game"] == "3.0"
    assert stats["Target share"] == "100%"
    assert stats["Points a game, last 2"] == "17.00"


def test_the_drawer_shows_the_latest_news_about_the_player() -> None:

    from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

    article = NewsArticle(article_id="1", published=datetime.now(UTC), headline="Good RB takes over")
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS), FakeESPN({"BUF": [article]})).player(
        "L1", "rb1"
    )

    [group] = [g for g in detail.groups if g.tab == "News"]
    assert [s.value for s in group.stats] == [article.headline]


def test_every_club_is_asked_for_by_espns_abbreviation() -> None:
    """Sleeper's WAS is ESPN's WSH, and a free agent has no club to ask after."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.players_catalog = {
        **client.get_nfl_players(),
        "was1": PlayerMeta(player_id="was1", name="Capital Back", position="RB", team="WAS"),
        "fa1": PlayerMeta(player_id="fa1", name="Loose End", position="TE", team="FA"),
    }
    espn = FakeESPN()

    nfl_provider(client, espn).summary("L1")

    assert "WSH" in espn.asked
    assert "WAS" not in espn.asked and "FA" not in espn.asked


def test_with_nothing_played_the_drawer_has_no_role_and_no_matchup() -> None:
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "rb1")

    [week] = [g for g in detail.groups if g.title.startswith("Week")]
    assert [s.label for s in week.stats] == ["Opponent"]
    assert "·" not in week.stats[0].value


def test_the_drawer_says_the_projection_once_and_a_healthy_player_has_no_status() -> None:
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "rb1")

    labels = {s.label for g in detail.groups for s in g.stats}
    assert detail.headline == "18.00"
    assert "Projected" not in labels
    assert "Status" not in labels
    assert "Injury" not in [g.title for g in detail.groups]


def test_a_designated_player_shows_sleepers_status_where_espn_has_no_row() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_nfl_players()
    client.players_catalog = {**catalog, "rb1": replace(catalog["rb1"], injury_status="Questionable")}

    [group] = [g for g in nfl_provider(client).player("L1", "rb1").groups if g.title == "Injury"]

    assert {s.label: s.value for s in group.stats}["Status"] == "Questionable"


def test_a_list_sleeper_writes_as_a_code_is_said_in_words_in_the_header_and_its_group() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_nfl_players()
    client.players_catalog = {**catalog, "rb1": replace(catalog["rb1"], injury_status="IR")}

    detail = nfl_provider(client).player("L1", "rb1")
    [group] = [g for g in detail.groups if g.title == "Injury"]

    assert detail.note == status_word("IR") != "IR"
    assert {s.label: s.value for s in group.stats}["Status"] == status_word("IR")
    assert detail.tone == "warning"


def test_the_drawer_shows_espns_injury_with_its_return_week() -> None:
    from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport

    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=SEASON_SCHEDULE)
    catalog = client.get_nfl_players()
    client.players_catalog = {**catalog, "rb1": replace(catalog["rb1"], espn_id="42")}
    report = InjuryReport(
        name="Someone Else",
        club="XXX",
        status="Out",
        updated=datetime.now(UTC),
        athlete_id="42",
        returns=date(2026, 9, 15),
        injury="Ankle",
        comment="Good RB (ankle) won't play.",
        url="https://espn.example/rb1",
    )

    detail = nfl_provider(client, FakeESPN(injuries=[report])).player("L1", "rb1")

    [group] = [g for g in detail.groups if g.title == "Injury"]
    stats = {s.label: s for s in group.stats}
    assert stats["Status"].value == "Out"
    assert stats["Back"].value == "~15 Sep · wk 2"
    assert any(s.url == "https://espn.example/rb1" for s in group.stats)


def test_a_team_defense_offers_no_portrait_to_fail_on() -> None:
    """Sleeper has no headshot for a defense, and offering the URL anyway put
    an empty photo tile in the drawer until the 404 came back."""
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "BUF")

    assert detail.image_url == ""
    assert detail.team_logo_url.endswith("/buf.png")


def test_a_player_carries_this_seasons_position_rank_and_none_before_he_plays() -> None:
    played = {**HISTORY, "2026": {"qb1": _stats("qb1", "2026", games=10, ppr=250.0, rank=3)}}

    assert (
        nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=played)).player("L1", "qb1").rank
        == "QB3"
    )
    assert (
        nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)).player("L1", "qb1").rank == ""
    )
