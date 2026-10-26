# 6. Use the fakes, not monkeypatch

Engines and providers take their collaborators as required keyword arguments
precisely so a test can hand them a stand-in. `tests/support/` already holds
one per outbound dependency — `FakeSleeper` and `FakeESPN` (`support.nfl`),
`FakeYahoo` and `FakeNBA` (`support.nba`), `FakeAI` and `FakeChat` (`support.ai`),
`FakeSession` (`support.http`) — with builders like `nfl_provider` beside them.

Monkeypatching reaches around that design. It binds the test to the import path
of the thing it patches, so moving a module breaks tests that never named it;
it leaks when a patch target is imported under two names; and it hides the fact
that the collaborator was always meant to be injected.

## Reject

```python
def test_the_scout_reads_projections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "thefrontoffice.adapters.outbound.platforms.sleeper.client.SleeperClient.get_projections",
        lambda self, *a, **k: {"123": 20.3},
    )
```

## Keep

```python
def test_the_scout_reads_projections() -> None:
    engine = ScoutEngine(nba_provider(FakeYahoo()), ai=FakeAI(), answers=FakeAnswers())
```

## Extending a fake

When a test needs behavior a fake lacks, add it to the fake in `tests/support/`
rather than defining a second one-off double in the test module. A second fake
for the same collaborator is how two tests come to disagree about what the real
thing does. Fakes are plain classes — no framework, no autospec.

## Where monkeypatch is still right

Process-level state that is not injected, and is not supposed to be: the
environment, the clock, module globals. `_isolate_from_local_env` in the
root `conftest.py` is the model — it patches the `settings` singleton, which is
deliberately a singleton and has no keyword to hand in.
