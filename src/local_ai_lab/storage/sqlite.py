from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def ensure_local_database_path(path: Path) -> Path:
    raw = str(path)
    if raw.startswith(("\\\\", "//")):
        raise ValueError("SQLite databases on network/UNC paths are forbidden")
    resolved = path.expanduser().resolve()
    drive = os.path.splitdrive(str(resolved))[0]
    if os.name == "nt" and not drive:
        raise ValueError("SQLite database must resolve to a local drive")
    return resolved


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = ensure_local_database_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
