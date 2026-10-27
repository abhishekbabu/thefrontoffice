"""Tests for the Sleeper football provider.

Covers `nfl/sleeper.py`: the port itself — leagues, rosters, players, the
wire, and the links out. The week, the league and the prompt have their own
modules beside this one.
"""

from dataclasses import replace
from datetime import UTC
from typing import Any

import pytest
from support.nfl import (
    DEFAULT_PROJECTIONS,
    SLEEPER_USER_ID,
    FakeESPN,
    FakeSleeper,
    game_line,
    league_client,
    nfl_provider,
    proj,
)

from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
)
from thefrontoffice.domain.errors import LeagueNotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import PlayerQuery

# ── leagues ─────────────────────────────────────────────────────────────


def test_leagues_are_listed_with_format_and_size() -> None:
    refs = nfl_provider(FakeSleeper()).list_leagues()
    assert len(refs) == 1
    assert refs[0].name == "Sunday Money"
    assert refs[0].competition == "nfl"
    assert "12-team" in refs[0].detail
    assert "PPR" in refs[0].detail


def test_missing_username_is_a_clear_error() -> None:
    provider = SleeperNFLProvider(username=None, client=FakeSleeper(), espn=FakeESPN())
    with pytest.raises(LeagueNotFoundError, match="SLEEPER_USERNAME"):
        provider.list_leagues()


def test_a_league_you_are_not_in_raises() -> None:
    with pytest.raises(LeagueNotFoundError, match="not one of yours"):
        nfl_provider(FakeSleeper()).build_context("nope")


def test_owning_no_roster_raises() -> None:
    client = FakeSleeper(rosters=[SleeperRoster(roster_id=9, owner_id="someone-else", player_ids=[], starter_ids=[])])
    with pytest.raises(LeagueNotFoundError, match="do not own a roster"):
        nfl_provider(client).build_context("L1")


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
    table = nfl_provider(client).player("L1", player_id).tables[0]
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
    assert table["Per game"][2] == f"{210.0 / 12:.1f}"
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

    assert _table(client)["Total"][1] == "300.0"  # pts_std, not pts_ppr


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


def test_a_player_carries_a_portrait_from_sleepers_own_cdn() -> None:
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "qb1")

    assert detail.image_url.endswith("/qb1.jpg")


def test_the_drawer_shows_what_the_projection_rests_on() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine

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

    [group] = [g for g in detail.groups if g.title == "Role and matchup"]
    stats = {stat.label: stat.value for stat in group.stats}
    assert stats["Matchup"].startswith("vs MIA, the most to RBs")
    assert stats["Snap share, last 2"] == "75%"
    assert stats["Carries a game"] == "16.0"
    assert stats["Targets a game"] == "3.0"
    assert stats["Target share"] == "100%"
    assert stats["Points a game, last 2"] == "17.0"


def test_the_drawer_shows_the_latest_news_about_the_player() -> None:
    from datetime import datetime

    from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

    article = NewsArticle(article_id="1", published=datetime.now(UTC), headline="Good RB takes over")
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS), FakeESPN({"BUF": [article]})).player(
        "L1", "rb1"
    )

    [group] = [g for g in detail.groups if g.title == "Latest news"]
    assert [s.value for s in group.stats] == [article.headline]


def test_every_club_is_asked_for_by_espns_abbreviation() -> None:
    """Sleeper's WAS is ESPN's WSH, and a free agent has no club to ask after."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.players_catalog = {
        **client.get_players(),
        "was1": PlayerMeta(player_id="was1", name="Capital Back", position="RB", team="WAS"),
        "fa1": PlayerMeta(player_id="fa1", name="Loose End", position="TE", team="FA"),
    }
    espn = FakeESPN()

    nfl_provider(client, espn).summary("L1")

    assert "WSH" in espn.asked
    assert "WAS" not in espn.asked and "FA" not in espn.asked


def test_with_nothing_played_the_drawer_has_no_role_section() -> None:
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "rb1")

    assert "Role and matchup" not in [g.title for g in detail.groups]


def test_a_team_defense_offers_no_portrait_to_fail_on() -> None:
    """Sleeper has no headshot for a defense, and offering the URL anyway put
    an empty photo tile in the drawer until the 404 came back."""
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "BUF")

    assert detail.image_url == ""
    assert detail.team_logo_url.endswith("/buf.png")


# ── the rest of the league ──────────────────────────────────────────────


def test_the_teams_list_puts_you_first() -> None:
    """You are the row somebody is looking for, and a fourteen-team league is
    long enough that hunting for it is a chore."""
    teams = nfl_provider(league_client()).teams("L1")

    assert teams[0].is_mine
    assert [t.is_mine for t in teams[1:]] == [False]


def test_a_team_carries_the_id_its_roster_is_behind() -> None:
    teams = nfl_provider(league_client()).teams("L1")
    assert {t.team_id for t in teams} == {"1", "2"}


def test_another_managers_roster_comes_back_in_your_own_columns() -> None:
    """One table renders both, so they have to agree about the shape."""
    provider = nfl_provider(league_client())

    mine = provider.roster("L1")
    theirs = provider.roster_of("L1", "2")

    assert set(theirs[0].columns) == set(mine[0].columns)
    assert [c.columns["Player"] for c in theirs] == ["Bad RB"]


def test_an_unknown_team_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        nfl_provider(league_client()).roster_of("L1", "999")


def test_free_agents_exclude_everyone_already_rostered() -> None:
    client = league_client()
    client.players_catalog = {
        "qb1": PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
        "free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ"),
    }

    agents = nfl_provider(client).free_agents("L1", PlayerQuery()).players

    assert [c.columns["Player"] for c in agents] == ["Waiver WR"]


def test_a_position_a_fantasy_league_does_not_score_is_left_out() -> None:
    """The catalog carries every practice-squad body in the league."""
    client = league_client()
    client.players_catalog = {
        "ol1": PlayerMeta(player_id="ol1", name="A Guard", position="OL", team="NYJ"),
        "free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ"),
    }

    agents = nfl_provider(client).free_agents("L1", PlayerQuery()).players

    assert [c.columns["Player"] for c in agents] == ["Waiver WR"]


def test_free_agents_have_no_lineup_column() -> None:
    """It would read "BN" down its whole length."""
    client = league_client()
    client.players_catalog = {"free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ")}

    assert "Slot" not in nfl_provider(client).free_agents("L1", PlayerQuery()).players[0].columns


# ── the one figure a player is judged on ────────────────────────────────


def test_a_player_with_no_projection_has_no_figure_at_all() -> None:
    """Not the string "no projection", which renders as though the absence of
    a number were the number."""
    client = FakeSleeper(projections={})

    detail = nfl_provider(client).player("L1", "qb1")

    assert detail.headline == ""


def test_nothing_published_yet_reads_differently_from_not_featuring() -> None:
    """A reader can act on the difference: the league has not posted week 3,
    versus it has and this player is not in it."""
    unpublished = nfl_provider(FakeSleeper(projections={})).player("L1", "qb1")

    scheduled = FakeSleeper(projections={"rb1": proj("rb1", "Good RB", "RB", 18.0)})
    benched = nfl_provider(scheduled).player("L1", "qb1")

    assert "not published yet" in unpublished.headline_label
    assert "Not projected to feature" in benched.headline_label


# ── the way across to the platform ──────────────────────────────────────


def test_a_league_links_to_itself_on_sleeper() -> None:
    """Reading it is this app; the moves are made there."""
    refs = nfl_provider(league_client()).list_leagues()

    assert refs[0].url == "https://sleeper.com/leagues/L1"


def test_a_player_links_to_their_own_page() -> None:
    detail = nfl_provider(league_client()).player("L1", "qb1")

    assert detail.url == "https://sleeper.com/players/nfl/qb1"


def test_a_player_on_no_nfl_roster_is_not_a_signing() -> None:
    """The catalog never forgets anybody — Reggie Wayne retired in 2014 and is
    still in it, unsigned. The default ranking hid him because he has no
    projection; sorting by experience put him on the first page."""
    client = league_client()
    client.players_catalog = {
        "signed": PlayerMeta(player_id="signed", name="On A Team", position="WR", team="NYJ"),
        "retired": PlayerMeta(player_id="retired", name="Long Retired", position="WR", team="FA"),
    }

    agents = nfl_provider(client).free_agents("L1", PlayerQuery()).players

    assert [c.columns["Player"] for c in agents] == ["On A Team"]


def test_a_page_reports_the_whole_pool_not_the_window() -> None:
    """Otherwise there is no way to know a second page exists."""
    client = league_client()
    client.players_catalog = {
        f"p{i}": PlayerMeta(player_id=f"p{i}", name=f"Player {i}", position="WR", team="NYJ") for i in range(120)
    }

    page = nfl_provider(client).free_agents("L1", PlayerQuery(limit=50))

    assert len(page.players) == 50
    assert page.total == 120


def test_a_free_agent_carries_the_numbers_behind_its_columns() -> None:
    """Sorting "22.3" as text is the bug this exists to prevent."""
    client = league_client()
    client.players_catalog = {"a": PlayerMeta(player_id="a", name="A", position="WR", team="NYJ", years_exp=7)}

    card = nfl_provider(client).free_agents("L1", PlayerQuery()).players[0]

    assert card.values["Exp"] == 7.0


def test_the_drawer_names_the_club_in_full_with_its_crest() -> None:
    """A column has room for "BUF"; a drawer has room for the name."""
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "qb1")
    assert detail.team == "BUF"
    assert detail.team_name == "Buffalo Bills"
    # Lowercase, or Sleeper's CDN 404s — the abbreviation everywhere else is upper.
    assert detail.team_logo_url == "https://sleepercdn.com/images/team_logos/nfl/buf.png"


def test_a_club_the_catalog_does_not_name_falls_back_to_its_abbreviation() -> None:
    """Worse than the full name, no worse than before, and not a failed page."""
    detail = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "bye1")
    assert detail.team_name == "LAR"


# ── the wire, for this roster ───────────────────────────────────────────


def _available(client: FakeSleeper, **query: object) -> dict[str, dict[str, str]]:
    page = nfl_provider(client).free_agents("L1", PlayerQuery.model_validate(query))
    return {card.player_id: card.columns for card in page.players}


def test_a_free_agent_shows_what_he_would_add_to_this_lineup() -> None:
    """The default roster starts nobody at WR, so a receiver fills an empty slot."""
    cards = _available(FakeSleeper(projections=DEFAULT_PROJECTIONS))

    assert cards["wr9"]["Fits"].startswith("+14.0")


def test_a_free_agent_short_of_every_starter_says_by_how_much() -> None:
    """In a deep league nobody on the wire outprojects a starter; how close
    each comes is then the whole question, so a shortfall is shown too."""
    league = SleeperLeague(
        league_id="L1", name="Deep", season="2026", total_rosters=14, scoring_format="pts_ppr", roster_positions=["WR"]
    )
    starter = proj("wr1", "Star WR", "WR", 20.0)
    client = FakeSleeper(
        projections={**DEFAULT_PROJECTIONS, "wr1": starter},
        league=league,
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["wr1"], starter_ids=["wr1"])],
    )
    client.players_catalog = {
        **client.get_players(),
        "wr1": PlayerMeta(player_id="wr1", name="Star WR", position="WR", team="BUF"),
    }

    fits = _available(client)["wr9"]["Fits"]

    assert fits.startswith("-6.0") and "Star WR" in fits


def test_the_wire_sorts_by_fit_across_the_whole_pool() -> None:
    cards = _available(FakeSleeper(projections=DEFAULT_PROJECTIONS), sort="Fits")

    assert next(iter(cards)) == "wr9"


def test_judging_the_wire_names_each_candidate_by_id_with_how_he_fits() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    fits = _available(client)["wr9"]["Fits"]

    context = nfl_provider(client).build_wire_context("L1", ["wr9"])

    [line] = context.candidate_lines.values()
    assert "wr9" in line and fits in line
    assert line in context.prompt


def test_a_rostered_player_cannot_be_judged_as_a_free_agent() -> None:
    with pytest.raises(PlayerNotFoundError):
        nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_wire_context("L1", ["qb1"])


# ── the matchup, simulated ──────────────────────────────────────────────


def _paired() -> FakeSleeper:
    """The default two rosters, paired this week, with the starters and points each played."""
    client = league_client()
    client.matchups = [
        {"roster_id": 1, "matchup_id": 7, "starters": ["qb1"], "points": 101.5},
        {"roster_id": 2, "matchup_id": 7, "starters": ["rb2"], "points": 88.0},
    ]
    return client


def test_the_matchup_to_simulate_has_both_lineups() -> None:
    matchup = nfl_provider(_paired()).matchup_input("L1")

    assert matchup is not None
    assert [o.player_id for o in matchup.mine] == ["qb1"]
    assert [o.player_id for o in matchup.theirs] == ["rb2"]


def test_a_bench_player_who_can_fill_an_empty_slot_is_a_move_to_price() -> None:
    matchup = nfl_provider(_paired()).matchup_input("L1")

    assert matchup is not None
    assert any(m.into[0].player_id == "rb1" and m.out == () for m in matchup.moves)


def test_a_week_with_no_opponent_has_nothing_to_simulate() -> None:
    assert nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).matchup_input("L1") is None


def test_a_played_week_is_rebuilt_from_its_starters_and_its_result() -> None:
    [played] = nfl_provider(_paired()).played_matchups("L1", 3)

    assert (played.week, played.mine, played.theirs) == (3, 101.5, 88.0)
    assert [o.player_id for o in played.matchup.mine] == ["qb1"]


def _line(pid: str, week: int, points: float) -> NFLGameLine:
    """A Buffalo back's game: two thirds of the snaps, and `points`."""
    return game_line(pid, week, "RB", "BUF", "MIA", off_snp=40, tm_off_snp=60, pts_ppr=points)


def test_a_played_week_for_tuning_is_known_only_from_the_games_before_it() -> None:
    """A range scored against a week it was shaped by would grade itself."""
    client = _paired()
    client.game_lines = [_line("rb1", 1, 9.0), _line("rb1", 2, 11.0), _line("rb1", 3, 30.0)]

    before, _last, played = nfl_provider(client).played_week("L1", 3)

    assert before.games["rb1"] == (9.0, 11.0)
    assert ("rb1", 30.0) in [(p.player_id, actual) for p, actual in played]


def test_last_season_is_read_for_the_shape_of_each_position() -> None:
    client = _paired()
    client.last_season_lines = [_line("old", w, 10.0 + w) for w in (1, 2, 3)]

    _before, last, _played = nfl_provider(client).played_week("L1", 3)

    assert last.games["old"] == (11.0, 12.0, 13.0)


def test_a_week_that_cannot_read_last_season_still_simulates() -> None:
    client = _paired()
    client.game_lines_error = SleeperAPIError("down")

    assert nfl_provider(client).matchup_input("L1") is not None


def test_a_free_agent_is_priced_at_every_start_he_could_make() -> None:
    """The default roster starts nobody at WR, so a free receiver fills the empty slot."""
    matchup = nfl_provider(_paired()).matchup_input("L1", candidates=["wr9"])

    assert matchup is not None and matchup.moves
    assert {m.into[0].player_id for m in matchup.moves} == {"wr9"}


def test_a_rostered_player_is_never_priced_as_a_free_agent() -> None:
    matchup = nfl_provider(_paired()).matchup_input("L1", candidates=["rb2"])

    assert matchup is not None and matchup.moves == ()


def test_a_warning_about_next_weeks_bye_is_not_priced_as_a_move() -> None:
    """It names your own starter; priced as a pickup it would be him added to his own lineup."""
    client = _paired()
    client.season_schedule = [*client.season_schedule, ScheduledGame(week=4, date="2026-10-04", home="KC", away="LV")]
    provider = nfl_provider(client)
    summary = provider.summary("L1")
    assert summary.actions and any(a.key.startswith("bye:") for a in summary.actions)

    matchup = provider.matchup_input("L1")

    assert matchup is not None
    starters = {o.player_id for o in matchup.mine}
    assert all(o.player_id not in starters for m in matchup.moves for o in m.into)


def test_a_free_agent_whose_role_grew_says_so_in_the_usage_column() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.week = 4
    client.game_lines = [
        NFLGameLine(
            player_id="wr9",
            week=week,
            team="NYJ",
            opponent="MIA",
            position="WR",
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": 5},
        )
        for week, snaps in ((1, 12), (2, 14), (3, 50))
    ]

    cards = _available(client, sort="Usage")

    assert next(iter(cards)) == "wr9"
    assert cards["wr9"]["Usage"].startswith("snaps")


# ── the roster as rows ──────────────────────────────────────────────────────


def test_roster_rows_mark_starters_and_bench() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"])],
    )
    rows = [c.columns for c in nfl_provider(client).roster("L1")]
    assert {r["Player"]: r["Slot"] for r in rows} == {"Star QB": "START", "Good RB": "BN"}


def test_roster_rows_skip_players_missing_from_the_catalog() -> None:
    client = FakeSleeper(
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["ghost"], starter_ids=[])]
    )
    assert nfl_provider(client).roster("L1") == []


def _one_out() -> FakeSleeper:
    """Two backs for one slot: the starter ruled out though Sleeper still projects him higher."""
    client = _paired()
    client.league = replace(client.league, roster_positions=["QB", "RB", "BN", "BN"])
    client.rosters = [
        replace(client.rosters[0], player_ids=["qb1", "rb1", "rb3"], starter_ids=["qb1", "rb3"]),
        *client.rosters[1:],
    ]
    client.projections = {
        **client.projections,
        "rb1": proj("rb1", "Good RB", "RB", 15.0),
        "rb3": replace(proj("rb3", "Hurt RB", "RB", 18.0), injury_status="Out"),
        "rb9": proj("rb9", "Spare RB", "RB", 10.0, team="NYJ", opp="NE"),
    }
    return client


def test_the_best_lineup_benches_a_starter_who_is_ruled_out_whatever_he_is_still_projected() -> None:
    [swap] = nfl_provider(_one_out()).summary("L1").swaps

    assert "Good RB" in swap.start and swap.out == "Hurt RB"


def test_a_free_agent_is_priced_against_the_lineup_the_bench_would_already_make() -> None:
    """Against the lineup as set, he would be credited with filling a slot the bench fills anyway."""
    matchup = nfl_provider(_one_out()).matchup_input("L1", candidates=["rb9"])

    assert matchup is not None
    assert {o.player_id for o in matchup.mine} == {"qb1", "rb1"}
