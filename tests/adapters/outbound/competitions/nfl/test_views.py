"""Tests for how a football player reads on the wire: `nfl/views.py`.

How a matchup reads, and how a free agent's fit is valued and ranked. The
drawer that opens on him is `test_drawer.py`.
"""

from dataclasses import replace

import pytest
from support.nfl import SLEEPER_USER_ID, SLUMPING_TE, FakeSleeper, game_line, nfl_provider, proj, slumping

from thefrontoffice.adapters.outbound.competitions.matchups import MATCHUP_SWING, RECENT_GAMES, Matchup, Recent
from thefrontoffice.adapters.outbound.competitions.nfl.views import ON_FORM, ease
from thefrontoffice.adapters.outbound.competitions.worth import SLUMP_LABEL
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.domain.models import OPPONENT_COLUMN, PlayerCard, PlayerQuery


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


def test_a_matchup_says_how_easy_it_has_been_lately_beside_its_season() -> None:
    matchup = Matchup(opponent="SF", position="TE", allowed=9.0, rank=20, defenses=32, recent=Recent(15.8, rank=4))

    assert ease(matchup).split(" · ") == ["13th-toughest", f"4th-easiest L{RECENT_GAMES}"]


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


def _against_wrs() -> list[NFLGameLine]:
    """Four defenses against one offense's receivers: NE gives up the most, LV the fewest."""
    allowed = {"NE": 30.0, "CHI": 20.0, "DEN": 10.0, "LV": 5.0}
    return [game_line(f"x{d}", 1, opponent=d, pts_ppr=pts) for d, pts in allowed.items()]


def test_a_fit_weighs_each_players_matchup() -> None:
    """Free, 10 projected against the softest defense, is worth 11; your starter, 12 against the toughest, 10.8."""
    [card] = [c for c in _cards(_wire(FREE_WR, game_lines=_against_wrs())) if c.player_id == "wr9"]

    assert card.values["Fits"] == pytest.approx(10.0 * (1 + MATCHUP_SWING) - 12.0 * (1 - MATCHUP_SWING))


def test_the_opponent_column_says_how_soft_the_defense_is_and_is_toned_by_it() -> None:
    cards = {c.player_id: c for c in _cards(_wire(FREE_WR, game_lines=_against_wrs()))}

    free = cards["wr9"]
    assert free.columns["Opponent"].startswith("vs NE")
    assert "easiest" in free.columns["Opponent"]
    assert free.tones["Opponent"] == "good"
    assert "to WRs" in free.notes["Opponent"]


def test_the_opponent_column_sorts_softest_matchup_first_and_a_player_without_one_last() -> None:
    """Free vs NE, the softest; another vs LV, the toughest; a third on bye, with no matchup at all."""
    tough = proj("wr8", "Lou Tough", "WR", 10.0, team="NYJ", opp="LV")
    idle = proj("wr7", "Bo Bye", "WR", 0.0, team="SEA", opp="")
    client = _wire(FREE_WR, tough, idle, game_lines=_against_wrs())

    cards = _cards(client, sort=OPPONENT_COLUMN, descending=True)

    assert [c.player_id for c in cards if c.player_id in {"wr9", "wr8", "wr7"}] == ["wr9", "wr8", "wr7"]
    assert cards[0].roles[OPPONENT_COLUMN] == "opponent"


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


# ── a slumping starter ──────────────────────────────────────────────────

STREAMER = proj("fa", "Aj Streamer", "TE", 7.0, team="SEA", opp="ARI")


def test_a_free_agent_against_a_slumping_starter_fits_on_form() -> None:
    """Both read three parts form to one part projection, a tenth up for steady snaps: 9.35 against 5.23."""
    [row] = nfl_provider(slumping(STREAMER)).free_agents("L1", PlayerQuery(position="TE")).players

    assert row.values["Fits"] == pytest.approx((0.75 * 9 + 0.25 * 7) * 1.1 - (0.75 * 3 + 0.25 * 10) * 1.1, abs=0.01)
    assert ON_FORM in row.notes["Fits"]


def test_a_slumping_starter_is_noted_on_his_projection_in_the_roster() -> None:
    rows = {row.player_id: row for row in nfl_provider(slumping(STREAMER, owned=True)).roster("L1")}

    assert rows[SLUMPING_TE.player_id].notes["Proj"].startswith(SLUMP_LABEL)
    assert "Proj" not in rows["fa"].notes
