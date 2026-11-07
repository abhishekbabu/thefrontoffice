"""Tests for the terminal's Yahoo login: it logs in only when it has to, and always checks the grant."""

import pytest
import yahoo_login
from support.wiring import FakeLogin

from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError


def test_without_a_token_it_logs_in_and_verifies() -> None:
    account = FakeLogin()

    assert yahoo_login.run(account, force=False) == 0
    assert account.logins == [True]
    assert account.verified.is_set()


def test_a_kept_token_is_only_checked() -> None:
    account = FakeLogin(token=True)

    assert yahoo_login.run(account, force=False) == 0
    assert account.logins == []
    assert account.verified.is_set()


def test_force_logs_in_again_over_a_kept_token() -> None:
    account = FakeLogin(token=True)

    yahoo_login.run(account, force=True)

    assert account.logins == [True]


def test_a_failure_prints_the_terminals_remedy(capsys: pytest.CaptureFixture[str]) -> None:
    assert yahoo_login.run(FakeLogin(error=YahooLoginRequiredError()), force=False) == 1
    assert "just yahoo-login" in capsys.readouterr().out
