"""Tests for the seed a simulation is played from: `competitions/seeds.py`."""

from thefrontoffice.adapters.outbound.competitions.seeds import seed


def test_the_same_week_seeds_the_same_simulation_and_another_week_another() -> None:
    assert seed("466.l.1", 5) == seed("466.l.1", 5)
    assert seed("466.l.1", 5) != seed("466.l.1", 6)
