"""Schema invariants that the database enforces rather than trusts."""

from __future__ import annotations

import sqlite3

import pytest

from hindsight import db


def _insert_filing(conn: sqlite3.Connection, accession: str = "0000000000-18-000001") -> str:
    conn.execute(
        """
        INSERT INTO filings (accession_no, cik, ticker, accepted_at_utc, period_of_report,
                             item_codes, raw_path)
        VALUES (?, 320193, 'AAPL', '2018-02-01T21:30:17+00:00', '2018-02-01',
                '2.02', 'data/raw/x.txt')
        """,
        (accession,),
    )
    return accession


def _insert_prediction(conn: sqlite3.Connection, accession: str, version: str = "v1") -> int:
    cur = conn.execute(
        """
        INSERT INTO predictions (accession_no, model_id, prompt_version, direction,
                                 probability, rationale, raw_response, created_at, run_mode)
        VALUES (?, 'claude-opus-5', ?, 'up', 0.7, 'why', '{}',
                '2026-07-27T00:00:00+00:00', 'historical')
        """,
        (accession, version),
    )
    return int(cur.lastrowid or 0)


class TestMigrations:
    def test_migrate_sets_version(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION

    def test_migrate_is_idempotent(self, conn: sqlite3.Connection) -> None:
        db.migrate(conn)
        db.migrate(conn)
        assert set(db.table_counts(conn)) == {
            "filings",
            "universe",
            "prices",
            "predictions",
            "evaluations",
        }

    def test_exactly_five_tables(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        assert sorted(r[0] for r in rows) == [
            "evaluations",
            "filings",
            "predictions",
            "prices",
            "universe",
        ]

    def test_refuses_to_open_a_newer_database(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 5}")
        with pytest.raises(RuntimeError, match="newer than this code"):
            db.migrate(conn)


class TestPredictionsImmutable:
    """Invariant: corrections are new rows, never updates. Enforced by a trigger."""

    def test_update_is_rejected(self, conn: sqlite3.Connection) -> None:
        acc = _insert_filing(conn)
        _insert_prediction(conn, acc)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE predictions SET direction = 'down'")

    def test_correction_as_new_row_is_allowed(self, conn: sqlite3.Connection) -> None:
        acc = _insert_filing(conn)
        _insert_prediction(conn, acc, "v1")
        _insert_prediction(conn, acc, "v2")
        assert conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 2

    def test_same_prompt_version_twice_is_rejected(self, conn: sqlite3.Connection) -> None:
        acc = _insert_filing(conn)
        _insert_prediction(conn, acc, "v1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_prediction(conn, acc, "v1")


class TestConstraints:
    def test_direction_is_constrained(self, conn: sqlite3.Connection) -> None:
        acc = _insert_filing(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO predictions (accession_no, model_id, prompt_version, direction,
                                         probability, created_at, run_mode)
                VALUES (?, 'm', 'v1', 'sideways', 0.7, 'now', 'historical')
                """,
                (acc,),
            )

    def test_probability_below_half_is_rejected(self, conn: sqlite3.Connection) -> None:
        # PREREGISTRATION §7 fixes the range at 0.50-1.00: direction carries the sign.
        acc = _insert_filing(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO predictions (accession_no, model_id, prompt_version, direction,
                                         probability, created_at, run_mode)
                VALUES (?, 'm', 'v1', 'up', 0.25, 'now', 'historical')
                """,
                (acc,),
            )

    def test_null_probability_allowed_for_parse_failures(self, conn: sqlite3.Connection) -> None:
        # §7: a filing that fails to parse is recorded as null, not dropped.
        acc = _insert_filing(conn)
        conn.execute(
            """
            INSERT INTO predictions (accession_no, model_id, prompt_version, direction,
                                     probability, raw_response, created_at, run_mode)
            VALUES (?, 'm', 'v1', NULL, NULL, 'unparseable', 'now', 'historical')
            """,
            (acc,),
        )
        assert conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1

    def test_run_mode_is_constrained(self, conn: sqlite3.Connection) -> None:
        # §15: live predictions are never merged into historical results, so the
        # distinction has to be unfakeable at write time.
        acc = _insert_filing(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO predictions (accession_no, model_id, prompt_version, direction,
                                         probability, created_at, run_mode)
                VALUES (?, 'm', 'v1', 'up', 0.7, 'now', 'backtest')
                """,
                (acc,),
            )

    def test_prediction_requires_an_existing_filing(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_prediction(conn, "does-not-exist")

    def test_evaluation_keyed_by_cost_level(self, conn: sqlite3.Connection) -> None:
        # A return means nothing without stating what it cost, so cost is in the key.
        acc = _insert_filing(conn)
        pid = _insert_prediction(conn, acc)
        for cost in (0, 10, 25):
            conn.execute(
                """
                INSERT INTO evaluations (prediction_id, horizon, entry_date, exit_date,
                                         raw_return, excess_return, cost_bps, net_return)
                VALUES (?, 5, '2018-02-02', '2018-02-09', 0.03, 0.02, ?, ?)
                """,
                (pid, cost, 0.02 - cost / 10000),
            )
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 3


class TestPrices:
    def test_ticker_date_is_unique(self, conn: sqlite3.Connection) -> None:
        for _ in range(2):
            conn.execute(
                """
                INSERT OR REPLACE INTO prices
                    (ticker, date, open, high, low, close, adj_close, volume)
                VALUES ('AAPL', '2018-02-01', 1, 2, 0.5, 1.5, 1.4, 100)
                """
            )
        assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 1
