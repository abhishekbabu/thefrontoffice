"""Tests for the domain exception hierarchy and its messages."""

from thefrontoffice.domain.errors import (
    AIUnavailableError,
    PlayerNotFoundError,
    TeamNotFoundError,
    TradeParseError,
)


def test_team_not_found_names_the_league() -> None:
    e = TeamNotFoundError("Dunder Mifflin")
    assert "Dunder Mifflin" in str(e)
    assert e.league_name == "Dunder Mifflin"


def test_player_not_found_lists_every_unresolved_name() -> None:
    e = PlayerNotFoundError(["Lebron Jamez", "Jayson Taytum"])
    assert "Lebron Jamez" in str(e)
    assert "Jayson Taytum" in str(e)
    assert e.names == ["Lebron Jamez", "Jayson Taytum"]


def test_player_not_found_names_a_lone_unresolved_player() -> None:
    assert "Lebron Jamez" in str(PlayerNotFoundError(["Lebron Jamez"]))


def test_trade_parse_error_quotes_what_was_typed() -> None:
    assert "nonsense" in str(TradeParseError("nonsense"))


def test_ai_unavailable_names_every_key_that_would_turn_it_on() -> None:
    from thefrontoffice.config import env_file

    message = str(AIUnavailableError())
    assert all(key in message for key in env_file.MODEL_KEYS)
