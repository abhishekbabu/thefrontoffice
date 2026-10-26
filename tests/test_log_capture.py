"""Tests for the `capture_logs` helper in conftest.

The reason it exists rather than `caplog` is that it captures one named logger
instead of everything the process emitted, so that is the property worth
pinning: a line from somewhere else must not satisfy an assertion about this
module.
"""

import logging

from support.logs import capture_logs

MINE = "thefrontoffice.tests.mine"
SOMEONE_ELSE = "thefrontoffice.tests.theirs"


def test_records_from_the_named_logger_are_captured() -> None:
    with capture_logs(MINE) as logs:
        logging.getLogger(MINE).info("the catalog was refreshed")
    assert "the catalog was refreshed" in logs.text


def test_another_logger_does_not_satisfy_the_assertion() -> None:
    """The whole point: `caplog` would return this line and pass."""
    with capture_logs(MINE) as logs:
        logging.getLogger(SOMEONE_ELSE).warning("2 matches for 'Williams'")
    assert logs.text == ""
    assert logs.records == []


def test_a_child_logger_still_reaches_its_parent() -> None:
    """Capturing a package captures the modules under it, as logging intends."""
    with capture_logs(MINE) as logs:
        logging.getLogger(f"{MINE}.client").info("nested")
    assert "nested" in logs.text


def test_records_below_the_level_are_not_captured() -> None:
    with capture_logs(MINE, logging.WARNING) as logs:
        logging.getLogger(MINE).info("chatter")
        logging.getLogger(MINE).warning("that mattered")
    assert "chatter" not in logs.text
    assert "that mattered" in logs.text


def test_messages_can_be_read_by_severity() -> None:
    with capture_logs(MINE) as logs:
        logging.getLogger(MINE).info("routine")
        logging.getLogger(MINE).warning("suspicious")
    assert logs.at(logging.WARNING) == ["suspicious"]
    assert logs.at(logging.INFO) == ["routine"]


def test_the_handler_is_removed_afterwards() -> None:
    """Otherwise every later test would keep appending to a dead capture."""
    logger = logging.getLogger(MINE)
    with capture_logs(MINE) as logs:
        logger.info("inside")
    logger.info("outside")
    assert "outside" not in logs.text
    assert not logger.handlers


def test_the_level_is_restored_afterwards() -> None:
    logger = logging.getLogger(MINE)
    logger.setLevel(logging.ERROR)
    with capture_logs(MINE, logging.DEBUG):
        pass
    assert logger.level == logging.ERROR


def test_a_raising_block_still_restores_the_logger() -> None:
    logger = logging.getLogger(MINE)
    logger.setLevel(logging.ERROR)
    try:
        with capture_logs(MINE, logging.DEBUG):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert logger.level == logging.ERROR
    assert not logger.handlers
