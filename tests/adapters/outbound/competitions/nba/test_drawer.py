"""Tests for the drawer's tabs on a basketball player: `nba/drawer.py`.

His week, projected line, recent games, game log, and the tabs read only when
opened, covered through the provider. The drawer's averages, owner and
teammates are read beside his row in `test_views.py`.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from support.espn import FakeESPN
from support.nba import FakeNBA, FakeSleeperProjections, FakeYahoo, make_player, nba_provider, toronto, yahoo_league

from thefrontoffice.adapters.outbound.competitions.nba.drawer import Drawer, DrawerWeek, detail
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores, RecentForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.views import BACK
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, Streak
from thefrontoffice.adapters.outbound.competitions.worth import SLUMP_LABEL
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    GameProjection,
    NBAGameLog,
    NBASeason,
    PlayerMeta,
    ScheduledGame,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    MovedPlayer,
    YahooTransaction,
)
from thefrontoffice.domain.errors import NotFoundError, PlayerNotFoundError
from thefrontoffice.domain.models import PlayerDetail


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


def test_his_news_tab_leads_with_his_clubs_stories_that_do_not_name_him() -> None:
    story = NewsArticle(article_id="1", published=datetime.now(UTC), headline="Lakers fire coach JJ Redick")

    groups = _tab("News", espn=FakeESPN(news={"LAL": [story]})).groups

    assert [(g.title, g.tab) for g in groups] == [("Team news", "News")]
    [stat] = groups[0].stats
    assert stat.label.startswith("Coach") and stat.value == story.headline


def test_his_news_tab_names_a_club_regular_out_for_long_from_the_box_scores() -> None:
    story = NewsArticle(article_id="1", published=datetime.now(UTC), headline="Scottie Barnes out for the season")
    yahoo = FakeYahoo(roster=[make_player("A B", "PG", team="TOR", key="ab")])

    groups = (
        nba_provider(yahoo, nba=FakeNBA(scores=toronto()), espn=FakeESPN(news={"TOR": [story]}))
        .player_tab("", "ab", "News")
        .groups
    )

    assert [s.label.split(",")[0] for g in groups if g.title == "Team news" for s in g.stats] == ["Out long-term"]


def test_a_tab_the_drawer_does_not_defer_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        _tab("This week")


def test_a_tab_for_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider(FakeYahoo()).player_tab("", "nobody", "News")


def test_box_scores_that_will_not_load_leave_his_clubs_stories_that_name_nobody() -> None:
    story = NewsArticle(article_id="1", published=datetime.now(UTC), headline="Lakers fire coach JJ Redick")

    nba = _guard()
    nba.scores_error = SleeperAPIError("down")

    groups = _tab("News", nba=nba, espn=FakeESPN(news={"LAL": [story]})).groups

    assert [g.title for g in groups] == ["Team news"]


def test_the_week_names_his_streak_and_a_return_in_doubt() -> None:
    """Labelled as every view labels it, so the drawer and the to-do list read one call."""
    player = make_player("A B", "PG", key="ab", status="O")
    sunk = Streak(hot=False, games=5, recent=4.1, usual=10.2, line={}, ahead={})
    reading = Reading(player=player, line={}, per_game=6.0, games=0, streak=sunk, missed=5)

    opened = detail(Drawer(player, None, None, (), None, week=DrawerWeek(left="0", reading=reading)))

    week = {s.label: s for s in opened.groups[0].stats}
    assert week[SLUMP_LABEL].tone == "warning" and "4.1" in week[SLUMP_LABEL].value
    assert week[BACK].tone == "warning" and "5" in week[BACK].value
