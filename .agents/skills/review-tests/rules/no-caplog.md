# 9. Capture the logger you mean

Assert on logs through `capture_logs` from `tests/support/logs.py`, never pytest's
`caplog`.

```python
from support.logs import capture_logs

GEMINI_LOGGER = GeminiClient.__module__     # the module logs via getLogger(__name__)


def test_token_usage_is_logged() -> None:
    with capture_logs(GEMINI_LOGGER) as logs:
        client.generate_structured("p", ScoutReport)
    assert "3400 in" in logs.text
```

## Why not `caplog`

`caplog` installs a handler at the **root** logger and hands back everything
anything logged during the block. Three consequences:

- **The assertion doesn't say what it means.** `"2 matches" in caplog.text`
  passes no matter which module emitted it. Move the line to a different module
  and the test keeps passing on a coincidence.
- **It depends on propagation.** Any logger between the emitter and the root
  that sets `propagate = False` makes the records vanish, and the test fails for
  a reason that has nothing to do with the behavior.
- **It is shared state.** It mutates root-level handlers and levels for the
  duration, which is fragile under any parallel runner.

`capture_logs(name, level=logging.INFO)` attaches to one named logger, restores
its level afterwards, and needs no propagation. `AGENTS.md` requires every
module to log through `logger = logging.getLogger(__name__)`, so the logger name
is always the module path — and `SomeClass.__module__` gets it without a string
literal that a file move would silently invalidate.

## The API

- `logs.text` — messages newline-joined, for substring assertions
- `logs.at(logging.WARNING)` — messages logged at exactly that level, when the
  severity is part of the contract
- `logs.records` — the raw `LogRecord`s

## What to flag

- Any use of `caplog` or `pytest.LogCaptureFixture`
- `capture_logs` given a string literal where a `__module__` would follow a move
- Asserting a message was logged when the caller-visible behavior would be the
  better assertion — a log line is the right target only when the log *is* the
  feature, as with token accounting
