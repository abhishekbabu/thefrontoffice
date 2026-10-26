# 4. The name is the specification

A test name is read far more often than the body — in failure output, in a diff,
in a suite listing. It should say the scenario and the expected outcome, so a
failure is legible before anyone opens the file.

This repo already sets the bar. From `tests/adapters/outbound/competitions/test_names.py`:

```python
def test_an_ambiguous_surname_resolves_to_nothing() -> None:
def test_a_unique_surname_matches_a_differing_first_name() -> None:
def test_ambiguity_is_detected_whichever_order_names_arrive() -> None:
```

Each is a sentence about behavior. Read the three together and you have the
matching rule without reading a line of `names.py`.

## Reject

```python
def test_normalize() -> None:              # no scenario, no outcome
def test_names_2() -> None:                # says nothing at all
def test_error() -> None:                  # which error, and then what?
def test_it_works() -> None:               # what is "works"?
```

## Rename to

```python
def test_accents_are_stripped() -> None:
def test_an_unknown_name_matches_nothing() -> None:
def test_a_failed_request_raises_rather_than_returning_none() -> None:
```

## The test

Read the name aloud without the `test_` prefix. If it is not a claim that can be
true or false, it is not a name — it is a label.
