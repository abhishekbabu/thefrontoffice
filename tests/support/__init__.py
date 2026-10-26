"""What tests share: stand-ins for the platforms and the model, and builders for the data they serve.

Imported by name — `from support.nfl import FakeSleeper` — because a test calls
these directly. Fixtures are different: pytest finds them in the `conftest.py`
of the directory a test sits in, or any above it, so the root `conftest.py`
holds what every test needs and a directory's own holds what only its tests do.
A `conftest.py` cannot be imported by name once there is more than one, which
is why nothing a test imports lives in one.
"""
