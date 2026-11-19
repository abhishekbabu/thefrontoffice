"""What a `DiskCache` directory holds on disk, read past the cache, as a person inspecting it would."""

import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DATABASE


def stored_text(directory: Path) -> str:
    """Every key and decompressed value the database in `directory` holds, as one string to search."""
    if not (directory / DATABASE).exists():
        return ""
    with closing(sqlite3.connect(directory / DATABASE)) as db:
        rows = db.execute("SELECT key, value FROM entries").fetchall()
    return "".join(key + zlib.decompress(value).decode("utf-8") for key, value in rows)
