# 8. The floor is not a target

Coverage is gated at 95%. The number exists to catch whole modules nobody
tested; it is not a score to maximise, and the difference matters because the
cheapest way to move it is to write tests that execute code without judging it.

A test that runs a function and asserts it did not raise is coverage-shaped and
information-free. It goes green on a function that returns the wrong answer,
which is worse than a gap: a gap is honest.

## Reject

```python
def test_build_context_runs() -> None:
    provider.build_context()  # no assertion at all


def test_report_generation() -> None:
    report = engine.generate()
    assert report is not None  # a truthiness check on an object


def test_every_error_class() -> None:
    for cls in (YahooAPIError, SleeperAPIError, FPLAPIError):
        assert issubclass(cls, FrontOfficeError)  # tests the class statement
```

## Keep

Each of those becomes a real test by naming what should come back:

```python
def test_a_failed_request_raises_rather_than_returning_none() -> None:
def test_the_headline_comes_from_the_provider_not_the_model() -> None:
def test_an_unmatched_player_carries_no_line() -> None:
```

## Reviewing against the floor

When coverage is the only argument for a test, the honest options are to write
a real assertion, or to leave the line uncovered and say why. If a module is
genuinely not worth testing — a thin `__main__`, a constants file — it belongs
in the coverage config, not behind a hollow test.

Flag as **high** severity: a test with no assertion, an assertion that cannot
fail (`assert x is not None` on a constructor result, `assert True`), and a loop
that asserts a property the type system already guarantees.
