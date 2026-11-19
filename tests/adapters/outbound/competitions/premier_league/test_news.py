"""Tests for reading FPL's one line of news into the drawer's Injury group."""

from datetime import UTC, date, datetime, timedelta

from support.fpl import player

from thefrontoffice.adapters.outbound.competitions.premier_league.news import BackBy, group, read
from thefrontoffice.adapters.outbound.platforms.fpl.types import Gameweek

NOV_16 = datetime(2026, 11, 16, 19, tzinfo=UTC)

# GW11 locks on Sat 21 Nov, and one a week after.
GAMEWEEKS = [
    Gameweek(id=i, name=f"Gameweek {i}", deadline=datetime(2026, 11, 21, 11, tzinfo=UTC) + timedelta(weeks=i - 11))
    for i in range(11, 21)
]


def test_an_injury_line_splits_into_what_is_wrong_and_when_he_is_back() -> None:
    news = read(player(3, "DEF", 6.0, status="i", news="Knee injury - Expected back 28 Nov", news_added=NOV_16))

    assert (news.what, news.word, news.returns) == ("Knee injury", "Expected back 28 Nov", date(2026, 11, 28))


def test_a_return_month_before_the_news_is_next_year() -> None:
    news = read(player(3, "DEF", 6.0, status="i", news="Hamstring injury - Expected back 2 Jan", news_added=NOV_16))
    assert news.returns == date(2027, 1, 2)


def test_a_suspension_names_no_injury_but_has_a_return() -> None:
    news = read(player(3, "DEF", 6.0, status="s", news="Suspended until 29 Nov", news_added=NOV_16))
    assert (news.what, news.word, news.returns) == ("", "Suspended until 29 Nov", date(2026, 11, 29))


def test_no_day_is_guessed_where_the_line_gives_none_or_no_time_was_published() -> None:
    assert read(player(3, "DEF", 6.0, news="Thigh injury - Unknown return date", news_added=NOV_16)).returns is None
    assert read(player(3, "DEF", 6.0, news="Knee injury - Expected back 28 Nov")).returns is None
    assert read(player(3, "DEF", 6.0, news="Knee injury - Expected back 31 Nov", news_added=NOV_16)).returns is None
    assert read(player(3, "DEF", 6.0, news="Knee injury - Expected back 3 Foo", news_added=NOV_16)).returns is None


def test_a_return_day_reads_with_the_gameweek_it_makes_him_available_for() -> None:
    back = BackBy(GAMEWEEKS)
    assert back(date(2026, 11, 28)) == "~28 Nov · GW12"
    assert back(date(2027, 6, 1)) == "~1 Jun"  # past the last deadline: the day alone


def test_a_flagged_player_gets_the_injury_group_every_sport_shows() -> None:
    hurt = player(
        3, "DEF", 6.0, status="i", chance_of_playing=0, news="Knock - Expected back 23 Nov", news_added=NOV_16
    )
    found = group(hurt, GAMEWEEKS)

    assert found is not None
    assert found.title == "Injury"
    assert [(s.label, s.value) for s in found.stats] == [
        ("Status", "injured 0%"),
        ("Body part", "Knock"),
        ("Back", "~23 Nov · GW12"),
        ("Mon 16 Nov", "Expected back 23 Nov"),
    ]


def test_a_suspension_and_a_departure_are_headed_for_what_they_are() -> None:
    banned = group(player(3, "DEF", 6.0, status="s", news="Suspended until 29 Nov", news_added=NOV_16), GAMEWEEKS)
    gone = group(player(3, "DEF", 6.0, status="u", news="Has joined Al Hilal permanently"), GAMEWEEKS)

    assert banned is not None and banned.title == "Suspension"
    assert gone is not None and gone.title == "Availability"
    assert gone.stats[-1].label == "Latest"  # no time published, so no day to file it under


def test_a_fit_player_has_no_group() -> None:
    assert group(player(3, "DEF", 6.0), GAMEWEEKS) is None
