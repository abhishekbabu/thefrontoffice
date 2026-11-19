"""Tests for how a football player reads in his drawer and on the wire: `nfl/views.py`.

The drawer's week, injury and game log are covered through the provider in
`test_sleeper.py`; these cover what the drawer leaves out, how its first tab
shows a role changing, which way each figure improves for a comparison, and
how a free agent's fit is valued and ranked.
"""

from dataclasses import replace

import pytest
from support.nfl import DEFAULT_PROJECTIONS, SLEEPER_USER_ID, FakeSleeper, game_line, nfl_provider, proj

from thefrontoffice.adapters.outbound.competitions.matchups import Matchup
from thefrontoffice.adapters.outbound.competitions.nfl.views import ease
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.domain.models import PlayerCard, PlayerDetail, PlayerQuery, Stat


@pytest.mark.parametrize(
    ("rank", "said"),
    [
        (1, "easiest"),
        (6, "6th-easiest"),
        (16, "16th-easiest"),
        (17, "16th-toughest"),
        (30, "3rd-toughest"),
        (32, "toughest"),
    ],
)
def test_a_matchup_reads_as_how_easy_or_tough_it_is_from_the_nearer_end(rank: int, said: str) -> None:
    """Rank 1 gives up the most: the easiest. Counted from whichever end is nearer, so no '27th-easiest'."""
    assert ease(Matchup(opponent="DAL", position="WR", allowed=20.0, rank=rank, defenses=32)) == said


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


# ── the wire: how a free agent fits ─────────────────────────────────────

MY_WR = proj("wr1", "Wade Starter", "WR", 12.0, team="KC", opp="LV")
MY_K = proj("k1", "Kip Starter", "K", 8.0, team="KC", opp="LV")
FREE_WR = proj("wr9", "Wes Free", "WR", 10.0, team="NYJ", opp="NE")
FREE_K = proj("k9", "Kai Free", "K", 9.5, team="NYJ", opp="NE")


def _wire(
    *free: WeeklyProjection,
    mine: tuple[WeeklyProjection, ...] = (MY_WR, MY_K),
    game_lines: list[NFLGameLine] | None = None,
) -> FakeSleeper:
    """A league that starts a receiver and a kicker; `mine` on your roster, `free` on the wire."""
    players = [*mine, *free]
    client = FakeSleeper(
        projections={p.player_id: p for p in players},
        league=SleeperLeague(
            league_id="L1",
            name="Small",
            season="2026",
            total_rosters=10,
            scoring_format="pts_ppr",
            roster_positions=["WR", "K", "BN"],
        ),
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=[p.player_id for p in mine],
                starter_ids=[p.player_id for p in mine],
            )
        ],
        game_lines=game_lines,
    )
    client.players_catalog = {
        p.player_id: PlayerMeta(
            player_id=p.player_id, name=p.name, position=p.position, team=p.team, injury_status=p.injury_status
        )
        for p in players
    }
    return client


def _cards(client: FakeSleeper, **query: object) -> list[PlayerCard]:
    return nfl_provider(client).free_agents("L1", PlayerQuery.model_validate(query)).players


def test_a_fit_weighs_recent_form_beside_the_projection_for_both_players() -> None:
    """Free, 10 projected and 20 a game, is worth 15; your starter, 12 and 4 a game, 8.

    Both on a steady part-time share of the snaps, which moves neither's worth.
    """
    part_time = {"off_snp": 24.0, "tm_off_snp": 60.0}
    lines = [game_line("wr9", w, team="NYJ", pts_ppr=20.0, **part_time) for w in (1, 2)]
    lines += [game_line("wr1", w, team="KC", pts_ppr=4.0, **part_time) for w in (1, 2)]

    [card] = [c for c in _cards(_wire(FREE_WR, game_lines=lines)) if c.player_id == "wr9"]

    assert card.values["Fits"] == 7.0
    assert "Wade Starter" in card.notes["Fits"]


def test_a_kicker_follows_every_skill_player_while_yours_plays() -> None:
    """Kai projects 1.5 more than your kicker and Wes 2 fewer than your receiver; Wes still leads."""
    order = [c.player_id for c in _cards(_wire(FREE_K, FREE_WR))]

    assert order.index("wr9") < order.index("k9")


def test_a_kicker_still_ranks_among_kickers_under_his_position() -> None:
    cards = _cards(_wire(FREE_K, FREE_WR), position="K")

    assert [c.player_id for c in cards] == ["k9"]
    assert cards[0].values["Fits"] == 1.5


def test_a_kicker_ranks_by_fit_with_everyone_when_your_slot_is_empty() -> None:
    [first, *_] = _cards(_wire(FREE_K, FREE_WR, mine=(MY_WR,)))

    assert first.player_id == "k9"
    assert first.values["Fits"] == 9.5 and first.notes["Fits"] == "at K, empty"


def test_a_starter_who_cannot_play_this_week_leaves_a_hole_his_replacement_fills() -> None:
    """Kip on bye scores nothing this week, so Kai gains his whole value and ranks with everyone."""
    on_bye = replace(MY_K, opponent="", points=0.0)

    [first, *_] = _cards(_wire(FREE_K, FREE_WR, mine=(MY_WR, on_bye)))

    assert first.player_id == "k9"
    assert first.values["Fits"] == 9.5
    assert "Kip Starter" in first.notes["Fits"] and "bye" in first.notes["Fits"]


def test_a_ruled_out_starter_is_named_with_his_ruling() -> None:
    out = replace(MY_WR, injury_status="Out")

    [card] = [c for c in _cards(_wire(FREE_WR, mine=(out, MY_K))) if c.player_id == "wr9"]

    assert card.values["Fits"] == 10.0
    assert "Wade Starter" in card.notes["Fits"] and "out" in card.notes["Fits"]


def test_a_free_agent_out_past_this_week_follows_everyone_who_can_play() -> None:
    """Ian's 20 a game is his worth, but no slot of yours gets it: he is on IR."""
    on_ir = replace(proj("wr8", "Ian Hurt", "WR", 0.0, team="MIA", opp="BUF"), injury_status="IR")
    lines = [game_line("wr8", w, team="MIA", pts_ppr=20.0, off_snp=24.0, tm_off_snp=60.0) for w in (1, 2)]

    cards = _cards(_wire(on_ir, FREE_WR, game_lines=lines))
    order = [c.player_id for c in cards]
    fits = {c.player_id: c.values["Fits"] for c in cards}

    assert fits["wr8"] > fits["wr9"]
    assert order.index("wr9") < order.index("wr8")
