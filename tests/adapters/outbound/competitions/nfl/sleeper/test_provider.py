"""Tests for the Sleeper football provider.

Covers `nfl/sleeper/provider.py`: the port itself — leagues, rosters, players, the
wire, and the links out. The week, the league and the prompt have their own
modules beside this one.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from support.espn import FakeESPN
from support.nfl import (
    DEFAULT_PROJECTIONS,
    SEASON_SCHEDULE,
    SLEEPER_USER_ID,
    FakeSleeper,
    at_week,
    game_line,
    league_client,
    nfl_provider,
    proj,
)
from support.stores import FakeProjectionLog
from support.summary import mine

from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
from thefrontoffice.adapters.outbound.competitions.nfl.views import GONE
from thefrontoffice.adapters.outbound.platforms.espn.types import ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperMatchup,
    SleeperRoster,
    TrendingPlayer,
)
from thefrontoffice.domain.errors import (
    InvalidRequestError,
    LeagueNotFoundError,
    NotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
)
from thefrontoffice.domain.models import PlayerQuery, Summary

# ── leagues ─────────────────────────────────────────────────────────────


def test_the_weeks_a_backtest_can_rebuild_are_the_finished_ones_after_the_first() -> None:
    """Week 1 has no games before it to shape a range, and the week in progress has no result."""
    client = FakeSleeper()
    client.week = 6

    assert nfl_provider(client).played_weeks("L1") == [2, 3, 4, 5]


def test_a_refresh_drops_the_league_it_names_and_the_week_kept_for_the_request() -> None:
    client = FakeSleeper()
    provider = nfl_provider(client)
    provider.summary("L1")
    fetched = client.matchup_fetches

    assert provider.refresh("L1") == 4
    provider.summary("L1")

    assert client.forgotten == ["L1"]
    assert client.matchup_fetches > fetched


def test_leagues_are_listed_with_format_and_size() -> None:
    refs = nfl_provider(FakeSleeper()).list_leagues()
    assert len(refs) == 1
    assert refs[0].name == "Sunday Money"
    # The format by its name alone: the header is read by someone who knows what PPR means.
    assert refs[0].detail.split(" · ") == ["12-team", "PPR"]


def test_a_league_you_are_not_in_raises() -> None:
    with pytest.raises(LeagueNotFoundError):
        nfl_provider(FakeSleeper()).build_context("nope")


def test_owning_no_roster_raises() -> None:
    client = FakeSleeper(rosters=[SleeperRoster(roster_id=9, owner_id="someone-else", player_ids=[], starter_ids=[])])
    with pytest.raises(LeagueNotFoundError):
        nfl_provider(client).build_context("L1")


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


@pytest.mark.parametrize(
    "excluded",
    [
        # Already on a roster in this league.
        PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
        # A position no fantasy league scores: the catalog carries every practice-squad body.
        PlayerMeta(player_id="ol1", name="A Guard", position="OL", team="NYJ"),
        # On no NFL roster: the catalog never forgets anybody, retired players included.
        PlayerMeta(player_id="retired", name="Long Retired", position="WR", team="FA"),
    ],
    ids=["rostered", "unscored-position", "unsigned"],
)
def test_the_wire_offers_only_players_a_manager_could_actually_sign(excluded: PlayerMeta) -> None:
    client = league_client()
    client.players_catalog = {
        excluded.player_id: excluded,
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

    assert unpublished.headline_label and benched.headline_label
    assert unpublished.headline_label != benched.headline_label


# ── the way across to the platform ──────────────────────────────────────


def test_a_league_links_to_itself_on_sleeper() -> None:
    """Reading it is this app; the moves are made there."""
    refs = nfl_provider(league_client()).list_leagues()

    assert refs[0].url == "https://sleeper.com/leagues/L1"


def test_a_player_links_to_their_own_page() -> None:
    detail = nfl_provider(league_client()).player("L1", "qb1")

    assert detail.url == "https://sleeper.com/players/nfl/qb1"


def test_a_free_agent_carries_the_numbers_behind_its_columns() -> None:
    """Sorting "22.3" as text is the bug this exists to prevent."""
    client = league_client()
    client.players_catalog = {"a": PlayerMeta(player_id="a", name="A", position="WR", team="NYJ", depth_chart_order=2)}

    card = nfl_provider(client).free_agents("L1", PlayerQuery()).players[0]

    assert card.values["Depth"] == 2.0


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
        **client.get_nfl_players(),
        "wr1": PlayerMeta(player_id="wr1", name="Star WR", position="WR", team="BUF"),
    }

    [card] = [c for c in nfl_provider(client).free_agents("L1", PlayerQuery()).players if c.player_id == "wr9"]

    assert card.values["Fits"] == -6.0
    # The cell holds the gap; who it is measured against is on hover.
    assert "Star WR" not in card.columns["Fits"] and "Star WR" in card.notes["Fits"]


def test_the_wire_leads_with_who_would_help_your_lineup_not_the_biggest_projection() -> None:
    """A quarterback outprojecting your own is still worth less than a receiver for an empty slot."""
    client = FakeSleeper(
        projections={
            **DEFAULT_PROJECTIONS,
            "qb9": proj("qb9", "Free QB", "QB", 25.0),
            "qb8": proj("qb8", "Backup QB", "QB", 16.0),
        }
    )
    client.players_catalog = {
        **client.get_nfl_players(),
        "qb9": PlayerMeta(player_id="qb9", name="Free QB", position="QB", team="NYJ"),
        "qb8": PlayerMeta(player_id="qb8", name="Backup QB", position="QB", team="MIA"),
    }

    order = list(_available(client))

    assert order.index("wr9") < order.index("qb9") < order.index("qb8")


def test_the_wire_reads_identity_then_value_then_usage_then_context() -> None:
    columns = list(_available(FakeSleeper(projections=DEFAULT_PROJECTIONS))["wr9"])

    assert columns[:6] == ["Player", "Pos", "Team", "Fits", "Proj", "ROS"]
    assert columns.index("Snap%") < columns.index("Without") < columns.index("Opponent") < columns.index("Status")


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
        SleeperMatchup(roster_id=1, matchup_id=7, starters=["qb1"], points=101.5),
        SleeperMatchup(roster_id=2, matchup_id=7, starters=["rb2"], points=88.0),
    ]
    return client


def test_the_matchup_to_simulate_is_the_lineup_the_app_recommends_against_theirs_as_set() -> None:
    """Yours starts only qb1; the bench back the to-do list puts in the empty slot is in the forecast too."""
    matchup = nfl_provider(_paired()).matchup_input("L1")

    assert matchup is not None
    assert sorted(o.player_id for o in matchup.mine) == ["qb1", "rb1"]
    assert [o.player_id for o in matchup.theirs] == ["rb2"]


def test_a_swap_the_recommended_lineup_makes_is_priced_by_undoing_it() -> None:
    matchup = nfl_provider(_paired()).matchup_input("L1")

    assert matchup is not None
    [made] = [m for m in matchup.moves if m.made]
    assert (made.out, made.into) == (("rb1",), ())
    assert not any(m.into and m.into[0].player_id == "rb1" for m in matchup.moves)


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


def test_a_held_out_week_that_will_not_load_fails_rather_than_scoring_perfectly() -> None:
    """Scored on no games at all, any settings have nothing to miss."""
    client = _paired()
    client.game_lines = [_line("rb1", 1, 9.0), _line("rb1", 2, 11.0), _line("rb1", 3, 30.0)]
    client.unloaded_weeks = {3}

    with pytest.raises(SleeperAPIError, match="week 3"):
        nfl_provider(client).ranged_games("L1", [3], [{}])


def test_each_candidate_ranges_the_same_played_games_under_its_own_settings() -> None:
    client = _paired()
    client.game_lines = [_line("rb1", 1, 9.0), _line("rb1", 2, 11.0), _line("rb1", 3, 30.0)]

    narrow, wide = nfl_provider(client).ranged_games("L1", [3], [{"projection_error": 0.0}, {"projection_error": 0.45}])

    assert [(o.player_id, actual) for o, actual in narrow] == [(o.player_id, actual) for o, actual in wide]
    assert narrow != wide


def test_last_season_is_read_for_the_shape_of_each_position() -> None:
    client = _paired()
    client.last_season_lines = [_line("old", w, 10.0 + w) for w in (1, 2, 3)]

    _before, last, _played = nfl_provider(client).played_week("L1", 3)

    assert last.games["old"] == (11.0, 12.0, 13.0)


def test_a_week_that_cannot_read_last_season_still_simulates() -> None:
    client = _paired()
    client.unloaded_weeks = set(range(1, 19))

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


def test_a_free_agent_whose_role_grew_says_so_in_the_trend_column() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.week = 5
    client.game_lines = [
        NFLGameLine(
            player_id="wr9",
            week=week,
            team="NYJ",
            opponent="MIA",
            position="WR",
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": 5},
        )
        for week, snaps in ((1, 12), (2, 14), (3, 50), (4, 50))
    ]

    cards = _available(client, sort="Trend")

    assert next(iter(cards)) == "wr9"
    assert cards["wr9"]["Trend"].startswith("snaps")


def test_a_free_agent_carries_his_snap_and_target_share_over_his_last_games_sortable() -> None:
    """Shares of the offense where his position has them; a kicker or a defense has neither."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.week = 5
    client.players_catalog = {
        **client.get_nfl_players(),
        "wr7": PlayerMeta(player_id="wr7", name="Other WR", position="WR", team="NYJ"),
        "k9": PlayerMeta(player_id="k9", name="Free K", position="K", team="NYJ"),
    }
    client.game_lines = [
        NFLGameLine(
            player_id=pid,
            week=week,
            team="NYJ",
            opponent="MIA",
            position="WR",
            stats={"off_snp": snaps, "tm_off_snp": 60, "rec_tgt": targets, "pts_ppr": 5},
        )
        for pid, snaps, targets in (("wr9", 45, 6), ("wr7", 15, 2))
        for week in (2, 3, 4)
    ]

    page = nfl_provider(client).free_agents("L1", PlayerQuery(sort="Snap%"))
    cards = {card.player_id: card for card in page.players}

    assert [c.player_id for c in page.players][:2] == ["wr9", "wr7"]
    assert cards["wr9"].values["Snap%"] == 0.75 and cards["wr9"].values["Tgt%"] == 0.75
    assert (cards["wr9"].columns["Snap%"], cards["wr9"].columns["Tgt%"]) == ("75%", "75%")
    assert (cards["k9"].columns["Snap%"], cards["k9"].columns["Tgt%"]) == ("—", "—")


def test_a_free_agent_sorts_by_the_rest_of_his_season() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    # A two-team final in week 5 ends the season there.
    client.league = replace(client.league, playoff_week_start=5, playoff_teams=2)
    client.weekly_projections[5] = {"bye1": proj("bye1", "Bye Guy", "TE", 40.0, team="LAR")}

    page = nfl_provider(client).free_agents("L1", PlayerQuery(sort="ROS"))

    # Week 4 is the default projections, week 5 his alone: 40 beats 14 + 0.
    assert [c.player_id for c in page.players][:2] == ["bye1", "wr9"]
    assert page.players[0].columns["ROS"] == "40.0"


def test_a_backup_who_jumped_while_the_starter_missed_his_game_reads_as_growing_while_the_starter_is_out() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.week = 4
    client.players_catalog = {
        **client.get_nfl_players(),
        "wr8": PlayerMeta(player_id="wr8", name="Hurt Starter", position="WR", team="NYJ", injury_status="Out"),
    }
    client.game_lines = [
        NFLGameLine(
            player_id=pid,
            week=week,
            team="NYJ",
            opponent="MIA",
            position="WR",
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": 5},
        )
        for pid, played in (("wr9", ((1, 12), (2, 14), (3, 50))), ("wr8", ((1, 50), (2, 50))))
        for week, snaps in played
    ]

    assert _available(client)["wr9"]["Trend"].startswith("snaps")


def _hurt_starter_client() -> FakeSleeper:
    """NYJ's starter wr8 is ruled out and missed week 3; the free agent wr9 scored 4 without him, 10 with."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.week = 4
    client.players_catalog = {
        **client.get_nfl_players(),
        "wr8": PlayerMeta(player_id="wr8", name="Hurt Starter", position="WR", team="NYJ", injury_status="Out"),
    }
    client.game_lines = [
        NFLGameLine(
            player_id=pid,
            week=week,
            team="NYJ",
            opponent="MIA",
            position="WR",
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": points},
        )
        for pid, played in (
            ("wr9", ((1, 30, 10.0), (2, 30, 10.0), (3, 30, 4.0))),
            ("wr8", ((1, 50, 20.0), (2, 50, 20.0))),
        )
        for week, snaps, points in played
    ]
    return client


def test_a_free_agent_names_the_hurt_starter_he_would_replace_with_his_split_in_the_tooltip() -> None:
    page = nfl_provider(_hurt_starter_client()).free_agents("L1", PlayerQuery())
    cards = {card.player_id: card for card in page.players}

    assert "Starter" in cards["wr9"].columns["Without"]
    assert "4.00" in cards["wr9"].notes["Without"] and "10.00" in cards["wr9"].notes["Without"]
    assert cards["bye1"].columns["Without"] == "—"
    assert cards["bye1"].notes == {}


def test_the_drawer_says_what_he_scored_without_his_hurt_teammate() -> None:
    detail = nfl_provider(_hurt_starter_client()).player("L1", "wr9")

    week = detail.groups[0]
    row = next(stat for stat in week.stats if stat.label.startswith("Without"))
    assert "Hurt Starter" in row.label
    assert row.tone == "warning"


# ── the roster as rows ──────────────────────────────────────────────────────


def test_roster_rows_mark_starters_and_bench() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"])],
    )
    rows = [c.columns for c in nfl_provider(client).roster("L1")]
    assert {r["Player"]: r["Slot"] for r in rows} == {"Star QB": "START", "Good RB": "BN"}


def test_roster_rows_name_the_reserve_slot_a_player_is_held_in() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=["qb1", "rb1", "rb2"],
                starter_ids=["qb1"],
                reserve_ids=["rb1", "rb2"],
                ir_ids=["rb1"],
            )
        ],
    )
    rows = [c.columns for c in nfl_provider(client).roster("L1")]
    assert {r["Player"]: r["Slot"] for r in rows} == {"Star QB": "START", "Good RB": "IR", "Bad RB": "TAXI"}


def test_roster_rows_say_who_is_ruled_out_rather_than_merely_listed() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"])],
    )
    catalog = client.get_nfl_players()
    hurt, doubtful = replace(catalog["qb1"], injury_status="IR"), replace(catalog["rb1"], injury_status="Questionable")
    client.players_catalog = {**catalog, "qb1": hurt, "rb1": doubtful}

    cards = {c.columns["Player"]: c for c in nfl_provider(client).roster("L1")}

    assert (cards["Star QB"].ruled_out, cards["Good RB"].ruled_out) == (True, False)
    assert cards["Good RB"].columns["Status"] == "Questionable"


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
        replace(client.rosters[0], player_ids=["qb1", "rb1", "rb3"]),
        *client.rosters[1:],
    ]
    client.matchups = [replace(client.matchups[0], starters=["qb1", "rb3"]), *client.matchups[1:]]
    client.projections = {
        **client.projections,
        "rb1": proj("rb1", "Good RB", "RB", 15.0),
        "rb3": replace(proj("rb3", "Hurt RB", "RB", 18.0), injury_status="Out"),
        "rb9": proj("rb9", "Spare RB", "RB", 10.0, team="NYJ", opp="NE"),
    }
    return client


def test_a_free_agent_is_priced_against_the_lineup_the_bench_would_already_make() -> None:
    """Against the lineup as set, he would be credited with filling a slot the bench fills anyway."""
    matchup = nfl_provider(_one_out()).matchup_input("L1", candidates=["rb9"])

    assert matchup is not None
    assert {o.player_id for o in matchup.mine} == {"qb1", "rb1"}


def test_a_free_agent_the_to_do_list_would_start_over_a_starter_is_priced_as_that_swap() -> None:
    client = _paired()
    client.league = replace(client.league, roster_positions=["QB", "RB", "BN", "BN"])
    client.matchups = [replace(client.matchups[0], starters=["qb1", "rb1"]), *client.matchups[1:]]
    client.projections = {
        **client.projections,
        "rb1": proj("rb1", "Good RB", "RB", 10.0),
        "rb9": proj("rb9", "Spare RB", "RB", 20.0, team="NYJ", opp="NE"),
    }
    client.players_catalog = {
        **client.get_nfl_players(),
        "rb9": PlayerMeta(player_id="rb9", name="Spare RB", position="RB", team="NYJ"),
    }

    matchup = nfl_provider(client).matchup_input("L1")

    assert matchup is not None
    assert any(m.into[0].player_id == "rb9" and m.out == ("rb1",) for m in matchup.moves)


def test_a_player_in_a_reserve_slot_is_no_start_to_price() -> None:
    """A taxi or injured-reserve slot is not the bench: nobody starts from it without a move first."""
    client = _paired()
    client.rosters = [replace(client.rosters[0], reserve_ids=["rb1"]), *client.rosters[1:]]

    matchup = nfl_provider(client).matchup_input("L1")

    assert matchup is not None
    assert not any(m.into[0].player_id == "rb1" for m in matchup.moves)


# ── the week's lineups ──────────────────────────────────────────────────


def _stale() -> FakeSleeper:
    """Your roster still starting Good RB, days after you benched him for Bad RB this week."""
    client = league_client()
    client.league = replace(client.league, roster_positions=["QB", "RB", "BN", "BN"])
    client.rosters = [
        replace(client.rosters[0], player_ids=["qb1", "rb1", "rb3"], starter_ids=["qb1", "rb1"]),
        replace(client.rosters[1], player_ids=["wr9"], starter_ids=["wr9"]),
    ]
    client.projections = {**client.projections, "rb3": proj("rb3", "Third RB", "RB", 2.0)}
    client.players_catalog = {
        **client.get_nfl_players(),
        "rb3": PlayerMeta(player_id="rb3", name="Third RB", position="RB", team="BUF"),
    }
    client.matchups = [SleeperMatchup(roster_id=1, matchup_id=None, starters=["qb1", "rb3"])]
    return client


def _starting(provider: SleeperNFLProvider) -> list[str]:
    return [spot.player for spot in mine(provider.summary("L1")).lineup]


def test_your_lineup_is_the_one_set_for_this_week_not_the_rosters_stale_copy() -> None:
    assert _starting(nfl_provider(_stale())) == ["Star QB", "Third RB"]


def test_a_team_with_no_matchup_this_week_starts_the_lineup_its_roster_carries() -> None:
    cards = {card.player_id: card.columns for card in nfl_provider(_stale()).roster_of("L1", "2")}

    assert cards["wr9"]["Slot"] == "START"


def test_where_the_weeks_matchups_will_not_load_the_rosters_lineup_stands() -> None:
    client = _stale()
    client.matchups_error = SleeperAPIError("down")

    assert _starting(nfl_provider(client)) == ["Star QB", "Good RB"]


def test_the_weeks_matchups_are_read_once_for_every_view_of_the_week() -> None:
    """The summary, the prompt, the forecast and the tables all read one week, not one fetch each."""
    client = _paired()
    provider = nfl_provider(client)

    provider.summary("L1")
    provider.build_context("L1")
    provider.matchup_input("L1")
    provider.roster("L1")

    assert client.matchup_fetches == 1


def test_a_move_can_name_only_yours_or_the_wires_before_their_kickoff() -> None:
    """BUF has kicked off, so its players are locked; Bad RB is somebody else's."""
    schedule = [replace(g, status="in_game") if g.home == "MIA" else g for g in SEASON_SCHEDULE]
    client = at_week(2)
    client.season_schedule = schedule
    movable = nfl_provider(client).build_context("L1").movable

    assert movable is not None
    assert "Waiver WR" in movable
    assert {"Star QB", "Good RB", "Bad RB"}.isdisjoint(movable)


def test_every_projection_and_stat_line_is_asked_for_in_the_leagues_own_scoring() -> None:
    rules = {"rec": 1.0, "fgm_40_49": 4.0}
    client = league_client()
    client.league = replace(client.league, scoring_rules=rules)
    provider = nfl_provider(client)

    provider.summary("L1")
    provider.build_context("L1")
    provider.player("L1", "qb1")

    assert client.rules_asked and all(asked == rules for asked in client.rules_asked)


# ── which week, and who played in it ────────────────────────────────────

WEEK_3 = [
    ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="complete"),
    ScheduledGame(week=3, date="2026-09-28", home="NE", away="NYJ", status="complete"),
]
WEEK_4 = [ScheduledGame(week=4, date="2026-10-01", home="BUF", away="NE", status="pre_game")]


def _week_three(wins: int = 1, losses: int = 1, points_for: float = 200.0) -> FakeSleeper:
    """Week 3 of a two-team league, Sleeper still calling it current: you beat them 120 to 95."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=[*WEEK_3, *WEEK_4],
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=["qb1", "rb1", "rb2"],
                starter_ids=["qb1", "rb1"],
                wins=wins,
                losses=losses,
                points_for=points_for,
            ),
            SleeperRoster(
                roster_id=2, owner_id="them", player_ids=["wr9"], starter_ids=["wr9"], wins=2, points_for=210.0
            ),
        ],
    )
    client.weekly_matchups = {
        3: [
            SleeperMatchup(roster_id=1, matchup_id=1, points=120.0, starters=["qb1", "rb1"]),
            SleeperMatchup(roster_id=2, matchup_id=1, points=95.0, starters=["wr9"]),
        ],
        4: [
            SleeperMatchup(roster_id=1, matchup_id=1, starters=["qb1", "rb2"]),
            SleeperMatchup(roster_id=2, matchup_id=1, starters=["wr9"]),
        ],
    }
    return client


def test_once_every_game_of_the_week_is_over_the_page_moves_to_the_week_being_set() -> None:
    summary = nfl_provider(_week_three()).summary("L1")

    assert summary.window.startswith("Week 4")
    assert [spot.player for spot in mine(summary).lineup[:2]] == ["Star QB", "Bad RB"]


def test_a_week_with_a_game_still_to_play_is_still_the_week() -> None:
    client = _week_three()
    client.season_schedule = [WEEK_3[0], replace(WEEK_3[1], status="pre_game"), *WEEK_4]

    assert nfl_provider(client).summary("L1").window.startswith("Week 3")


def test_the_live_scoreboard_ends_the_week_before_the_schedule_file_catches_up() -> None:
    client = _week_three()
    client.season_schedule = [replace(game, status="in_game") for game in WEEK_3] + WEEK_4
    espn = FakeESPN()
    espn.weekly_scoreboards = {3: [ScoreboardGame("BUF", "MIA", "post"), ScoreboardGame("NE", "NYJ", "post")]}

    assert nfl_provider(client, espn).summary("L1").window.startswith("Week 4")


def test_the_last_week_of_the_season_never_moves_past_it() -> None:
    client = _week_three()
    client.week = 18
    client.season_schedule = [replace(game, week=18) for game in WEEK_3]

    assert nfl_provider(client).summary("L1").window.startswith("Week 18")


def test_a_finished_week_counts_in_the_record_before_sleeper_settles_it() -> None:
    provider = nfl_provider(_week_three())

    standings = {row.team_id: (row.record, row.points) for row in provider.schedule("L1").standings}

    assert standings == {"1": ("2-1", "320.00"), "2": ("2-1", "305.00")}


def test_a_week_sleeper_has_already_counted_is_not_counted_twice() -> None:
    summary = nfl_provider(_week_three(wins=2, losses=1, points_for=320.0)).summary("L1")

    assert mine(summary).record == "2-1"


def test_a_league_that_plays_its_median_counts_a_second_game_for_the_top_half() -> None:
    client = _week_three(wins=2, losses=2)
    client.league = replace(client.league, median_game=True)

    assert mine(nfl_provider(client).summary("L1")).record == "4-2"


def test_a_playoff_week_leaves_the_regular_seasons_record_alone() -> None:
    client = _week_three()
    client.league = replace(client.league, playoff_teams=2, playoff_week_start=3)

    assert mine(nfl_provider(client).summary("L1")).record == "1-1"


def _let_go() -> FakeSleeper:
    """Mid-week: Good RB scored 15.5 for you, then was dropped; Waiver WR scored for them, then was traded away."""
    client = _week_three()
    client.season_schedule = [WEEK_3[0], replace(WEEK_3[1], status="pre_game"), *WEEK_4]
    client.rosters = [
        replace(client.rosters[0], player_ids=["qb1", "rb2"]),
        replace(client.rosters[1], player_ids=[]),
    ]
    client.weekly_matchups[3] = [
        SleeperMatchup(roster_id=1, matchup_id=1, points=37.5, starters=["qb1", "rb1"], players_points={"rb1": 15.5}),
        SleeperMatchup(roster_id=2, matchup_id=1, points=9.0, starters=["wr9"], players_points={"wr9": 9.0}),
    ]
    return client


def test_a_starter_let_go_after_his_game_keeps_his_slot_and_says_he_is_gone() -> None:
    rows = {spot.player: spot.detail for spot in mine(nfl_provider(_let_go()).summary("L1")).lineup}

    assert GONE in rows["Good RB"]
    assert GONE not in rows["Star QB"]


def test_the_opponents_starter_let_go_after_his_game_keeps_his_slot_too() -> None:
    opponent = nfl_provider(_let_go()).summary("L1").opponent

    assert opponent is not None
    assert [(spot.player, GONE in spot.detail) for spot in opponent.lineup] == [("Waiver WR", True)]


def test_a_starter_let_go_still_counts_toward_the_weeks_projection() -> None:
    points = mine(nfl_provider(_let_go()).summary("L1")).points

    assert points.endswith("40.00 proj")  # Star QB's 22 and Good RB's 18


def test_the_roster_table_lists_a_starter_let_go_as_starting() -> None:
    cards = {card.player_id: card.columns["Slot"] for card in nfl_provider(_let_go()).roster("L1")}

    assert cards == {"qb1": "START", "rb1": "START", "rb2": "BN"}


# ── other weeks of the season ───────────────────────────────────────────

WEEK_5 = [ScheduledGame(week=5, date="2026-10-08", home="BUF", away="MIA", status="pre_game")]


def _week_five() -> FakeSleeper:
    """Week 5 being played. In week 2 you held Waiver WR and started him, and have dropped him since."""
    client = _week_three()
    client.week = 5
    client.season_schedule = [*WEEK_5]
    client.league = replace(client.league, playoff_teams=4, playoff_week_start=14)
    client.weekly_matchups = {
        2: [
            SleeperMatchup(
                roster_id=1,
                matchup_id=1,
                points=101.0,
                starters=["qb1", "rb1", "", "wr9"],
                players=["qb1", "rb1", "wr9"],
                players_points={"wr9": 12.0},
            ),
            SleeperMatchup(roster_id=2, matchup_id=1, points=99.0, starters=["rb2"], players=["rb2"]),
        ],
        # Sleeper copies a roster's standing lineup into weeks to come: here, the worse back.
        7: [
            SleeperMatchup(roster_id=1, matchup_id=1, starters=["qb1", "rb2"]),
            SleeperMatchup(roster_id=2, matchup_id=1, starters=["wr9"]),
        ],
    }
    return client


def _headline(summary: Summary) -> dict[str, str]:
    return {stat.label: stat.value for stat in summary.headline}


def test_the_week_being_played_says_where_it_sits_in_the_season() -> None:
    weeks = nfl_provider(_week_five()).summary("L1").weeks

    assert weeks is not None
    assert (weeks.week, weeks.current, weeks.first, weeks.last) == (5, 5, 1, 15)


def test_a_week_played_shows_the_roster_that_played_it_and_its_final_score() -> None:
    summary = nfl_provider(_week_five()).week_of("L1", 2)
    lineup = mine(summary).lineup

    assert [spot.player for spot in lineup[:4]] == ["Star QB", "Good RB", "—", "Waiver WR"]
    assert all(GONE not in spot.detail for spot in lineup)  # he was on the roster that week
    assert _headline(summary)["Final"] == "101.00 – 99.00"
    assert summary.actions is None
    assert summary.weeks is not None and (summary.weeks.week, summary.weeks.current) == (2, 5)


def test_a_week_played_reads_each_record_as_it_stood_going_into_it() -> None:
    """Week 3 comes after one week counted, which you won, not the 1-1 you are now."""
    client = _week_five()
    client.weekly_matchups[1] = []  # nobody played week 1
    client.weekly_matchups[3] = [
        SleeperMatchup(roster_id=1, matchup_id=1, points=90.0, starters=["qb1"], players=["qb1", "rb1"]),
        SleeperMatchup(roster_id=2, matchup_id=1, points=95.0, starters=["rb2"], players=["rb2"]),
    ]

    summary = nfl_provider(client).week_of("L1", 3)

    assert mine(summary).record == "1-0"
    assert summary.opponent is not None and summary.opponent.record.startswith("0-1")


def test_a_week_played_keeps_todays_records_when_a_week_before_it_will_not_load() -> None:
    client = _week_five()
    client.unloaded_weeks = {1}

    assert mine(nfl_provider(client).week_of("L1", 3)).record == "1-1"


def test_a_week_to_come_starts_each_rosters_best_lineup_rather_than_sleepers_copy() -> None:
    summary = nfl_provider(_week_five()).week_of("L1", 7)

    assert [spot.player for spot in mine(summary).lineup[:3]] == ["Star QB", "Good RB", "Bad RB"]
    assert "Live" not in _headline(summary) and "Final" not in _headline(summary)
    assert summary.window.startswith("Week 7")


def test_a_playoff_week_to_come_names_no_opponent() -> None:
    """Sleeper fills the bracket with placeholder pairings until the regular season is over."""
    client = _week_five()
    client.weekly_matchups[14] = client.weekly_matchups[7]

    assert nfl_provider(client).week_of("L1", 14).opponent is None


def test_a_week_outside_the_season_is_refused() -> None:
    with pytest.raises(NotFoundError):
        nfl_provider(_week_five()).week_of("L1", 16)


def test_a_weeks_games_say_where_each_stands_and_whose_players_are_in_each() -> None:
    client = _week_five()
    client.season_schedule = [*WEEK_5, ScheduledGame(week=5, date="2026-10-11", home="NYJ", away="NE")]
    espn = FakeESPN()
    espn.weekly_scoreboards = {
        5: [
            ScoreboardGame("BUF", "MIA", "post", label="Final", home_score=27, away_score=20),
            ScoreboardGame("NYJ", "NE", "pre", label="Sun 1:00 PM"),
        ]
    }

    games = {
        (g.home, g.away): (g.detail, g.home_score, g.away_score, bool(g.yours))
        for g in nfl_provider(client, espn).games_of("L1", 5).games
    }

    # A game yet to kick off has no score rather than a nil-nil one.
    assert games == {
        ("BUF", "MIA"): ("Final", 27, 20, True),
        ("NYJ", "NE"): ("", None, None, False),
    }


def test_a_weeks_byes_are_the_clubs_the_season_schedules_that_have_no_game_in_it() -> None:
    client = _week_five()
    client.season_schedule = [
        *WEEK_5,
        ScheduledGame(week=4, date="2026-10-04", home="NYJ", away="NE"),
        ScheduledGame(week=6, date="2026-10-18", home="KC", away="DEN"),
    ]

    slate = nfl_provider(client, FakeESPN()).games_of("L1", 5)

    assert slate.byes == ["DEN", "KC", "NE", "NYJ"]


def test_a_week_with_no_games_listed_has_no_byes_either() -> None:
    client = _week_five()
    client.season_schedule = [ScheduledGame(week=4, date="2026-10-04", home="NYJ", away="NE")]

    assert nfl_provider(client, FakeESPN()).games_of("L1", 5).byes == []


def test_a_weeks_games_run_in_kickoff_order_each_with_its_start() -> None:
    client = _week_five()
    client.season_schedule = [*WEEK_5, ScheduledGame(week=5, date="2026-10-11", home="NYJ", away="NE")]
    espn = FakeESPN()
    early, late = datetime(2026, 10, 11, 17, tzinfo=UTC), datetime(2026, 10, 12, 0, 20, tzinfo=UTC)
    espn.weekly_scoreboards = {
        5: [ScoreboardGame("BUF", "MIA", "pre", kickoff=late), ScoreboardGame("NYJ", "NE", "pre", kickoff=early)]
    }

    games = nfl_provider(client, espn).games_of("L1", 5).games

    assert [(g.home, g.kickoff) for g in games] == [("NYJ", early), ("BUF", late)]


def test_a_week_of_games_outside_the_season_is_refused() -> None:
    with pytest.raises(NotFoundError):
        nfl_provider(_week_five()).games_of("L1", 0)


def test_the_wire_offers_sleepers_trending_adds_most_added_first_with_their_count() -> None:
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS, trending=[TrendingPlayer("qb1", 900), TrendingPlayer("wr9", 120)]
    )
    page = nfl_provider(client).free_agents("L1", PlayerQuery(view="Trending"))

    assert page.views == ["Trending", "IR"]
    # Star QB trends, but he is on a roster: nobody's to add.
    assert [(c.player_id, c.columns["Adds"]) for c in page.players] == [("wr9", "120")]


def test_a_view_is_matched_regardless_of_case() -> None:
    """`?view=trending` once answered with the whole pool, which reads as the trending list."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, trending=[TrendingPlayer("wr9", 120)])

    page = nfl_provider(client).free_agents("L1", PlayerQuery(view="trending"))

    assert [c.player_id for c in page.players] == ["wr9"]


def test_a_view_nobody_offers_is_refused_rather_than_ignored() -> None:
    with pytest.raises(InvalidRequestError):
        nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).free_agents("L1", PlayerQuery(view="hot"))


def test_the_wire_lists_free_agents_on_ir_on_their_own() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    catalog = client.get_nfl_players()
    hurt = next(pid for pid, meta in catalog.items() if pid not in {"qb1", "rb1"} and meta.position == "WR")
    client.players_catalog = {**catalog, hurt: replace(catalog[hurt], injury_status="IR")}

    page = nfl_provider(client).free_agents("L1", PlayerQuery(view="IR"))

    assert [c.player_id for c in page.players] == [hurt]
    assert page.players[0].columns["Back"] == "—"
    assert "Back" not in page.players[0].values


def test_the_ir_list_puts_the_soonest_back_first_and_unknown_returns_last() -> None:
    from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport

    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=SEASON_SCHEDULE)
    late, soon, unknown = "ir1", "ir2", "ir3"
    client.players_catalog = {
        **client.get_nfl_players(),
        **{
            pid: PlayerMeta(player_id=pid, name=pid, position="WR", team="KC", injury_status="IR", espn_id=pid)
            for pid in (late, soon, unknown)
        },
    }
    reports = [
        InjuryReport(
            name=pid, club="", status="Injured Reserve", updated=datetime.now(UTC), athlete_id=pid, returns=back
        )
        for pid, back in ((late, date(2027, 1, 3)), (soon, date(2026, 9, 15)))
    ]

    page = nfl_provider(client, FakeESPN(injuries=reports)).free_agents("L1", PlayerQuery(view="IR"))

    assert [c.player_id for c in page.players] == [soon, late, unknown]
    assert [c.columns["Back"] for c in page.players] == ["wk 2", "3 Jan", "—"]
    by_back = nfl_provider(client, FakeESPN(injuries=reports)).free_agents(
        "L1", PlayerQuery(view="IR", sort="Back", descending=True)
    )
    assert [c.player_id for c in by_back.players] == [late, soon, unknown]


def _dropped_by_the_report(espn_id: str = "") -> tuple[FakeSleeper, FakeESPN]:
    """One player on IR whom ESPN's league-wide report has dropped, and his own entry in its history."""
    from thefrontoffice.adapters.outbound.platforms.espn.types import Athlete, InjuryReport

    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_schedule=SEASON_SCHEDULE)
    client.players_catalog = {
        **client.get_nfl_players(),
        "ir1": PlayerMeta(
            player_id="ir1", name="Long Gone", position="RB", team="WAS", injury_status="IR", espn_id=espn_id
        ),
    }
    espn = FakeESPN()
    espn.rosters = [Athlete(athlete_id="77", name="Long Gone", club="WSH")]
    espn.histories = {
        "77": InjuryReport(
            name="Long Gone",
            club="WSH",
            status="Injured Reserve",
            updated=datetime(2026, 9, 28, tzinfo=UTC),
            athlete_id="77",
            returns=date(2026, 9, 15),
            injury="Left knee - acl, surgery",
        )
    }
    return client, espn


def test_a_player_the_report_has_dropped_is_found_on_his_clubs_roster_and_shows_when_he_is_back() -> None:
    client, espn = _dropped_by_the_report()

    page = nfl_provider(client, espn).free_agents("L1", PlayerQuery(view="IR"))
    detail = nfl_provider(client, espn).player("L1", "ir1")

    assert [c.columns["Back"] for c in page.players if c.player_id == "ir1"] == ["wk 2"]
    [group] = [g for g in detail.groups if g.title == "Injury"]
    assert {s.label: s.value for s in group.stats}["Back"] == "~15 Sep · wk 2"
    assert espn.asked_after == ["77"]


def test_a_player_sleeper_gives_an_espn_id_is_asked_after_without_reading_the_rosters() -> None:
    client, espn = _dropped_by_the_report(espn_id="77")
    espn.rosters = []

    page = nfl_provider(client, espn).free_agents("L1", PlayerQuery(view="IR"))

    assert [c.columns["Back"] for c in page.players if c.player_id == "ir1"] == ["wk 2"]
    assert espn.roster_reads == 0


def test_espn_failing_past_the_report_leaves_the_report_standing() -> None:
    from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError

    client, espn = _dropped_by_the_report()
    espn.backfill_error = ESPNAPIError("down")

    page = nfl_provider(client, espn).free_agents("L1", PlayerQuery(view="IR"))

    assert [c.columns["Back"] for c in page.players if c.player_id == "ir1"] == ["—"]


def test_the_week_being_played_keeps_each_projection_read_before_its_game() -> None:
    """Week 3 has kicked off nowhere: everyone projected is kept, as read."""
    log = FakeProjectionLog()
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)

    nfl_provider(client, pregame=log).summary("L1")

    assert log.week("2026", 3) == {pid: p.points for pid, p in DEFAULT_PROJECTIONS.items()}


def test_a_club_whose_game_has_kicked_off_keeps_nothing_new() -> None:
    log = FakeProjectionLog()
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=[ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="in_game")],
    )

    nfl_provider(client, pregame=log).summary("L1")

    assert set(log.week("2026", 3) or {}) == {"wr9"}
