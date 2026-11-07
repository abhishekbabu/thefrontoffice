"""Tests for putting the engines' figures into words: `adapters/inbound/presenting.py`."""

from support.simulation import odds_split

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.application.week import SeasonView, WeekView, WirePage
from thefrontoffice.domain.models import (
    Action,
    Forecast,
    LeagueSchedule,
    MarginRange,
    PickupChance,
    PlayerCard,
    PlayerPage,
    PlayerQuery,
    PlayoffOdds,
    StandingRow,
    Stat,
    Summary,
    TeamOdds,
)


def _forecast(win: float) -> Forecast:
    return Forecast(win=win, margin=MarginRange(low=-36, median=-10, high=-6), simulations=1)


# ── the week ────────────────────────────────────────────────────────────


def _week_at(win: float) -> Summary:
    return presenting.week(WeekView(summary=Summary(headline=[Stat(label="Week", value="7")]), forecast=_forecast(win)))


def test_the_chance_of_winning_follows_the_providers_header() -> None:
    assert [s.label for s in _week_at(0.01).headline] == ["Week", "Win chance"]  # the margin rides with the chance


def test_a_long_shot_week_is_flagged_as_a_warning() -> None:
    assert _week_at(0.01).headline[1].tone == "warning"


def test_the_forecast_itself_travels_with_the_week() -> None:
    assert _week_at(0.01).forecast == _forecast(0.01)


def test_a_week_with_nothing_simulated_is_the_providers_alone() -> None:
    week = Summary(headline=[Stat(label="Week", value="7")])

    assert presenting.week(WeekView(summary=week)) == week


def test_the_week_header_carries_the_playoff_chance_and_what_this_week_is_worth() -> None:
    forecast = Forecast(win=0.5, margin=MarginRange(low=-1, median=0, high=1), simulations=1)

    summary = presenting.week(WeekView(summary=Summary(), forecast=forecast, odds=odds_split(0.9, 0.5)))

    [_, stat] = summary.headline
    assert stat.label == "Playoffs"
    assert all(figure in stat.value for figure in ("70%", "90%", "50%"))


def test_the_table_carries_each_teams_chance_on_its_row() -> None:
    schedule = LeagueSchedule(
        standings=[StandingRow(rank=1, name="A", team_id="a"), StandingRow(rank=2, name="Z", team_id="z")]
    )
    odds = PlayoffOdds(spots=1, teams=[TeamOdds(team_id="a", name="A", playoffs=0.61)], playoffs=0.61, simulations=1)

    attached = presenting.season(SeasonView(schedule=schedule, odds=odds))
    a, z = attached.standings

    assert (a.playoffs, z.playoffs) == ("61%", "")


def test_the_seasons_header_weighs_this_week_as_the_weeks_header_does() -> None:
    """One chance shown two ways on two pages reads as a bug in one of them."""
    odds = PlayoffOdds(spots=1, teams=[], playoffs=0.88, with_win=0.96, with_loss=0.79, simulations=1)

    headline = presenting.season(SeasonView(schedule=LeagueSchedule(), odds=odds, win=0.01)).headline

    # A one-in-a-hundred win weighs the 79% after a loss, not the season's 88%.
    assert {s.label: s.value for s in headline}["Playoffs"] == "79%"


# ── the wire ────────────────────────────────────────────────────────────


def _page(*ids: str) -> PlayerPage:
    return PlayerPage(
        players=[PlayerCard(player_id=pid, columns={"Player": pid, "Fits": "+1.0", "Opponent": "MIA"}) for pid in ids]
    )


def test_a_priced_page_shows_the_chance_beside_the_fit_and_a_dash_for_the_rest() -> None:
    page = presenting.wire(
        WirePage(
            page=_page("a", "b"), chances=[PickupChance(player_id="a", win_change=0.019, title="Start A")], priced=True
        )
    )

    a, b = page.players
    assert list(a.columns) == ["Player", "Fits", presenting.WIN_COLUMN, "Opponent"]
    assert (a.columns[presenting.WIN_COLUMN], a.values[presenting.WIN_COLUMN]) == ("+1.9%", 0.019)
    assert b.columns[presenting.WIN_COLUMN] == "—" and presenting.WIN_COLUMN not in b.values


def test_ordering_by_the_chance_keeps_the_unpriced_last_either_way() -> None:
    chances = [
        PickupChance(player_id="a", win_change=-0.01, title=""),
        PickupChance(player_id="c", win_change=0.02, title=""),
    ]

    for descending, expected in ((True, ["c", "a", "b"]), (False, ["a", "c", "b"])):
        query = PlayerQuery(sort=presenting.WIN_COLUMN, descending=descending)
        page = presenting.wire(WirePage(page=_page("a", "b", "c"), chances=chances, priced=True), query)
        assert [p.player_id for p in page.players] == expected


def test_sorting_by_the_chance_asks_the_competition_for_its_own_ranking() -> None:
    """The chance is priced for one page, so it cannot rank the pool the page is cut from."""
    assert presenting.ranking(PlayerQuery(sort=presenting.WIN_COLUMN)).sort == ""
    assert presenting.ranking(PlayerQuery(sort="Proj")).sort == "Proj"


def test_a_change_too_small_to_tell_from_noise_reads_as_none() -> None:
    assert [presenting.win_change(c) for c in (0.028, -0.004, 0.0001)] == ["+2.8%", "−0.4%", "no change"]


def test_each_priced_item_says_what_it_does_to_the_chance_in_words_and_tone() -> None:
    actions = [
        Action(kind="lineup", urgency="now", title="Start A", reason="r", win_change=0.028),
        Action(kind="lineup", urgency="now", title="Start B", reason="r", win_change=-0.004),
        Action(kind="lineup", urgency="now", title="Start C", reason="r"),
    ]
    week = presenting.week(WeekView(summary=Summary(actions=actions)))

    assert week.actions is not None
    gain, cost, unpriced = week.actions
    assert gain.chance is not None and (gain.chance.value, gain.chance.tone) == ("+2.8% to win", "good")
    assert cost.chance is not None and (cost.chance.value, cost.chance.tone) == ("−0.4% to win", "warning")
    assert unpriced.chance is None


def test_a_page_priced_to_no_effect_still_has_its_column() -> None:
    """Every game under way leaves nobody to price; the column says so rather than vanishing."""
    page = presenting.wire(WirePage(page=_page("a"), priced=True))

    assert page.players[0].columns[presenting.WIN_COLUMN] == "—"


def test_a_page_never_priced_has_no_chance_column() -> None:
    assert presenting.WIN_COLUMN not in presenting.wire(WirePage(page=_page("a"))).players[0].columns
