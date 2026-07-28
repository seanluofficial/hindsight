"""SQLite schema, connections, and migrations.

The four pipeline stages never call each other; they communicate only through this
database. Five tables, as specified in CLAUDE.md.

Two invariants are enforced here rather than left to convention:

* Predictions are immutable. A trigger rejects UPDATE on `predictions` outright, so a
  correction has to be a new row with a new prompt_version. Rewriting history is the
  easiest way to fool yourself about a backtest, so the database refuses.
* Timestamps are UTC. Columns storing an instant are suffixed `_utc` and hold ISO-8601
  strings with an explicit offset.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hindsight import config

SCHEMA_VERSION = 1

_SCHEMA = """
-- One row per 8-K we ingested. `anonymized_text` stays NULL until the score stage.
CREATE TABLE IF NOT EXISTS filings (
    accession_no     TEXT PRIMARY KEY,
    cik              INTEGER NOT NULL,
    ticker           TEXT    NOT NULL,
    accepted_at_utc  TEXT    NOT NULL,
    period_of_report TEXT,
    item_codes       TEXT,
    raw_path         TEXT    NOT NULL,
    anonymized_text  TEXT,
    anon_version     TEXT
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker_time ON filings (ticker, accepted_at_utc);
CREATE INDEX IF NOT EXISTS idx_filings_accepted    ON filings (accepted_at_utc);

-- Point-in-time index membership. `end_date` NULL means "still a member".
-- A company that left in 2016 keeps its row, so 2014 samples still contain it (invariant 2).
CREATE TABLE IF NOT EXISTS universe (
    ticker     TEXT NOT NULL,
    cik        INTEGER,
    start_date TEXT NOT NULL,
    end_date   TEXT,
    PRIMARY KEY (ticker, start_date)
);
CREATE INDEX IF NOT EXISTS idx_universe_cik ON universe (cik);

CREATE TABLE IF NOT EXISTS prices (
    ticker    TEXT NOT NULL,
    date      TEXT NOT NULL,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    adj_close REAL,
    volume    REAL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices (date);

-- Immutable. Corrections are new rows with a new prompt_version, never updates.
CREATE TABLE IF NOT EXISTS predictions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    accession_no   TEXT NOT NULL REFERENCES filings (accession_no),
    model_id       TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    direction      TEXT CHECK (direction IN ('up', 'down')),
    -- §7 fixes the range at 0.50-1.00; `direction` carries the sign.
    probability    REAL CHECK (
                       probability IS NULL
                       OR (probability >= 0.50 AND probability <= 1.00)
                   ),
    rationale      TEXT,
    raw_response   TEXT,
    created_at     TEXT NOT NULL,
    run_mode       TEXT NOT NULL CHECK (run_mode IN ('historical', 'live')),
    UNIQUE (accession_no, model_id, prompt_version, run_mode)
);
CREATE INDEX IF NOT EXISTS idx_predictions_accession ON predictions (accession_no);

-- A prediction yields one row per (horizon, cost level). Cost is part of the key
-- because a return is meaningless without stating what it cost to capture.
CREATE TABLE IF NOT EXISTS evaluations (
    prediction_id INTEGER NOT NULL REFERENCES predictions (id),
    horizon       INTEGER NOT NULL,
    entry_date    TEXT    NOT NULL,
    exit_date     TEXT    NOT NULL,
    raw_return    REAL,
    excess_return REAL,
    cost_bps      REAL    NOT NULL,
    net_return    REAL,
    PRIMARY KEY (prediction_id, horizon, cost_bps)
);

CREATE TRIGGER IF NOT EXISTS predictions_are_immutable
BEFORE UPDATE ON predictions
BEGIN
    SELECT RAISE(ABORT,
        'predictions are immutable: write a new row with a new prompt_version');
END;
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas this project depends on."""
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database up to SCHEMA_VERSION. Idempotent.

    Versioning uses PRAGMA user_version so the five-table contract stays five tables.
    """
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database is at schema v{current}, newer than this code (v{SCHEMA_VERSION}). "
            "Check out a newer revision rather than downgrading the file."
        )
    if current < SCHEMA_VERSION:
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return SCHEMA_VERSION


@contextmanager
def session(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Connect, migrate, and always close."""
    conn = connect(db_path)
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row count per table — the cheapest sanity check there is."""
    tables = ("filings", "universe", "prices", "predictions", "evaluations")
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
