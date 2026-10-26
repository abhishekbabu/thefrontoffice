# 5. One reason to fail

A test that checks five things reports the first failure and hides the rest, and
its name cannot describe what it covers — which is why such tests end up called
`test_provider` or `test_the_happy_path`.

## Reject

```python
def test_the_provider() -> None:
    context = provider.build_context()
    assert context.roster
    assert context.opponent.name == "TiffAtRR"
    assert context.projections["Jared Goff"] == 20.3
    assert context.headline.startswith("Week 1")
    assert provider.cache_hits == 3
```

When this fails on line 3 you learn nothing about lines 4–6, and the name
promises the whole provider works.

## Keep

```python
def test_the_roster_reaches_the_context() -> None:
def test_the_opponent_is_named() -> None:
def test_a_projection_is_carried_per_player() -> None:
```

## Shared setup, separate assertions

Splitting does not mean repeating setup. Hoist it into a helper or fixture and
keep one assertion each — `tests/adapters/outbound/competitions/nba/test_yahoo_trade.py` does exactly this
with its `_context()` helper.

## Where several assertions are one behavior

Asserting three fields of one returned object is one behavior if the behavior is
"the object is built correctly from this input". The signal is whether the
assertions can fail *independently for different reasons*. Three fields off one
construction share a cause; a roster, a cache count and a headline do not.
