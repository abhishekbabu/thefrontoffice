"""Asserting on what one named logger said."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager


class LogCapture(logging.Handler):
    """Every record one named logger emitted inside a `capture_logs` block."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        """The rendered messages, newline-joined, for substring assertions."""
        return "\n".join(record.getMessage() for record in self.records)

    def at(self, level: int) -> list[str]:
        """The messages logged at exactly `level`, for asserting on severity."""
        return [record.getMessage() for record in self.records if record.levelno == level]


@contextmanager
def capture_logs(name: str, level: int = logging.INFO) -> Iterator[LogCapture]:
    """Records from the logger called `name`, for the duration of the block.

    Narrower than pytest's `caplog`, which installs a handler at the root and
    hands back everything anything logged in that window. Naming the logger
    makes the test say which module is expected to speak, so a line that moves
    to another module fails here instead of passing on a coincidence. It also
    needs no propagation: the handler attaches to the logger under test.
    """
    capture = LogCapture()
    logger = logging.getLogger(name)
    previous_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(level)
    try:
        yield capture
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
