# 2. Assert behavior, not implementation

A test should describe what the caller observes. Asserting on which
collaborator was called, in what order, or how many times, welds the test to
today's structure — so a refactor that preserves every observable behavior
still turns the suite red, and the suite stops being a safety net and becomes a
tax on changing anything.

## Reject

```python
def test_projections_are_fetched() -> None:
    provider.build_context()
    assert sleeper.get_projections_called == 1  # an internal call count
    assert yahoo.search.call_args[0][0] == "nba.l.1"
```

## Keep

```python
def test_an_unmatched_player_carries_no_line() -> None:
    context = provider.build_context()
    assert context.players["Nobody Here"].projection is None
```

## The exception that is not one

Sometimes the call *is* the behavior — a cache hit must not reach the network,
and that is only observable as "the fetch was not called":

```python
def test_a_hit_never_calls_the_fetch() -> None:
    cache.set("k", "stored")
    calls: list[int] = []
    value = cache.cached("k", timedelta(hours=1), lambda: calls.append(1) or "fetched")
    assert value == "stored"
    assert calls == []
```

That is legitimate: not touching the network *is* the contract. The difference
is whether the caller would notice. A caller notices an avoided HTTP request; a
caller does not notice which private helper assembled the result.
