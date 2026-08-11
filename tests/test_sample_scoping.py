"""The scored population must be exactly the frozen study sample (D16).

The freeze is worthless if scoring ignores it. These tests pin the wiring: `--sample`
restricts selection to the sample's accession numbers, and nothing outside the sample leaks
in — regardless of anonymization order or how many other filings exist.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_score  # noqa: E402

from hindsight.score import anonymize as anon  # noqa: E402


def _add_filing(
    conn: sqlite3.Connection, accession: str, accepted: str, *, anonymized: bool
) -> None:
    conn.execute(
        """
        INSERT INTO filings
            (accession_no, cik, ticker, accepted_at_utc, raw_path, anonymized_text, anon_version)
        VALUES (?, 1, 'ACME', ?, 'data/raw/x.txt', ?, ?)
        """,
        (
            accession,
            accepted,
            ("anon text " * 50) if anonymized else None,
            anon.ANON_VERSION if anonymized else None,
        ),
    )


def test_restrict_to_returns_exactly_the_sample(conn: sqlite3.Connection) -> None:
    # Ten filings, all anonymized; only three are in the sample.
    for i in range(10):
        _add_filing(conn, f"acc-{i:02d}", f"2010-01-{i + 1:02d}T12:00:00Z", anonymized=True)
    sample = {"acc-02", "acc-05", "acc-08"}

    rows = run_score.select_filings(conn, limit=None, need_anon=True, restrict_to=sample)

    assert {r["accession_no"] for r in rows} == sample


def test_without_restrict_selects_everything(conn: sqlite3.Connection) -> None:
    for i in range(10):
        _add_filing(conn, f"acc-{i:02d}", f"2010-01-{i + 1:02d}T12:00:00Z", anonymized=True)

    rows = run_score.select_filings(conn, limit=None, need_anon=True, restrict_to=None)

    assert len(rows) == 10


def test_earliest_n_is_not_the_sample(conn: sqlite3.Connection) -> None:
    """The old behaviour — LIMIT N by timestamp — would have scored the wrong filings."""
    for i in range(10):
        _add_filing(conn, f"acc-{i:02d}", f"2010-01-{i + 1:02d}T12:00:00Z", anonymized=True)
    sample = {"acc-07", "acc-08", "acc-09"}  # the three latest, not the earliest

    earliest_three = {r["accession_no"] for r in run_score.select_filings(conn, 3, need_anon=True)}
    scoped = {
        r["accession_no"]
        for r in run_score.select_filings(conn, None, need_anon=True, restrict_to=sample)
    }

    assert earliest_three == {"acc-00", "acc-01", "acc-02"}
    assert scoped == sample
    assert earliest_three.isdisjoint(scoped)


def test_restrict_still_requires_anonymization(conn: sqlite3.Connection) -> None:
    """A sampled filing that has not been anonymized is not returned to a scorer."""
    _add_filing(conn, "acc-anon", "2010-01-01T12:00:00Z", anonymized=True)
    _add_filing(conn, "acc-raw", "2010-01-02T12:00:00Z", anonymized=False)
    sample = {"acc-anon", "acc-raw"}

    rows = run_score.select_filings(conn, None, need_anon=True, restrict_to=sample)

    assert {r["accession_no"] for r in rows} == {"acc-anon"}


def _add_prediction(
    conn: sqlite3.Connection, accession: str, model_id: str, prompt_version: str, run_mode: str
) -> None:
    conn.execute(
        """
        INSERT INTO predictions
            (accession_no, model_id, prompt_version, direction, probability,
             rationale, raw_response, created_at, run_mode)
        VALUES (?, ?, ?, 'up', 0.6, 'r', '{}', '2020-01-01T00:00:00Z', ?)
        """,
        (accession, model_id, prompt_version, run_mode),
    )


def test_already_scored_matches_only_same_configuration(conn: sqlite3.Connection) -> None:
    _add_filing(conn, "acc-01", "2010-01-01T12:00:00Z", anonymized=True)
    _add_filing(conn, "acc-02", "2010-01-02T12:00:00Z", anonymized=True)
    _add_prediction(conn, "acc-01", "deepseek-v4-flash", "p1.1", "historical")
    # Same filing, different config — must NOT count as already scored for the run below.
    _add_prediction(conn, "acc-02", "deepseek-v4-flash", "p1.0", "historical")
    _add_prediction(conn, "acc-02", "deepseek-v4-flash", "p1.1", "live")

    done = run_score.already_scored(conn, "deepseek-v4-flash", "p1.1", "historical")

    assert done == {"acc-01"}


def test_load_sample_accessions_reads_the_csv(tmp_path: Path) -> None:
    path = tmp_path / "study_sample.csv"
    path.write_text(
        "accession_no,ticker,accepted_at_utc,item_group,year\n"
        "acc-01,ACME,2010-01-01T12:00:00Z,earnings,2010\n"
        "acc-02,ACME,2010-01-02T12:00:00Z,other,2010\n",
        encoding="utf-8",
    )

    assert run_score.load_sample_accessions(path) == {"acc-01", "acc-02"}


def test_load_sample_accessions_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run_score.load_sample_accessions(tmp_path / "does_not_exist.csv")
