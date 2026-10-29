# 7. Hermetic by default

The default suite must run with no network, no credentials and nothing left on
disk. That is what makes it usable in a pre-commit hook and identical on three
operating systems in CI. A single test that reaches out makes the whole suite
fail on a plane, flake on a rate limit, or depend on whose laptop it runs on.

Two things hold the line, and both belong in a review:

**`_isolate_from_local_env` (autouse).** Points the Yahoo token at a path that
cannot exist and every platform cache directory under `tmp_path`, so a run
neither reads a cache this machine happened to warm nor leaves one behind. A
test that constructs its own client must take the same care — pass a
`JsonDiskCache(tmp_path / "cache")`, never the default path.

**The `integration` marker.** Declared in `pyproject.toml` and deselected by
`addopts = "-m 'not integration'"`. Anything touching a live API — Yahoo,
Sleeper, FPL, Gemini — carries it. That marker is the only sanctioned way to
reach the network.

## Reject

```python
def test_the_catalog_parses() -> None:
    client = SleeperClient()  # real cache path, real HTTP
    assert client.get_players("nfl")
```

## Keep

```python
def test_the_catalog_parses(tmp_path: Path) -> None:
    client = SleeperClient(cache=JsonDiskCache(tmp_path / "cache"), session=FakeSession(...))


@pytest.mark.integration
def test_the_live_catalog_still_has_the_fields_we_read() -> None:
    """Deselected by default; opt in with `-m integration`."""
```

## What to flag

- A client, provider or engine built without its cache or session substituted
- `requests`, `httpx` or an SDK constructed in a test body with real config
- Writes anywhere but `tmp_path`
- A test that hits a live API and is *not* marked `integration`
- A test marked `integration` that does not need to be — the marker means it is
  never run by `just check`, so an over-marked test is an unrun test
