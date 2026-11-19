"""The seed a competition's simulations are played from, the same for the same week."""

import hashlib


def seed(*parts: object) -> int:
    """The same simulation for the same week, so the numbers hold still between reloads."""
    return int(hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).hexdigest()[:12], 16)
