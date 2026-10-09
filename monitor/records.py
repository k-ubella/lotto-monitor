"""Local SQLite records containing normalized results only."""

from contextlib import closing
from pathlib import Path
import sqlite3

from .balance import BalanceResult


def append_result(path: Path, result: BalanceResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS balance_results (
                    id INTEGER PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ok', 'unavailable', 'error')),
                    balance_krw INTEGER,
                    source TEXT NOT NULL,
                    CHECK((status = 'ok' AND balance_krw IS NOT NULL AND balance_krw >= 0)
                        OR (status != 'ok' AND balance_krw IS NULL))
                )
            """)
            connection.execute(
                "INSERT INTO balance_results (observed_at, status, balance_krw, source) VALUES (?, ?, ?, ?)",
                (result.observed_at, result.status, result.balance_krw, result.source),
            )


def read_results(path: Path) -> list[BalanceResult]:
    # URI read-only mode prevents a typo from creating an empty database.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT observed_at, status, balance_krw, source FROM balance_results ORDER BY id"
        ).fetchall()
    return [BalanceResult(*row) for row in rows]
