"""Experiment 008 — the peer map must be point-in-time (invariant 2, no survivorship).

A company that left the industry group's index membership before a date must not appear as a
peer on that date, and must appear while it was a member. This is the silent failure mode for
a lead-lag test: a survivorship leak would quietly inflate the peer basket with names that were
not actually tradeable members at the time.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from hindsight.experiments import diffusion


@pytest.fixture
def conn(tmp_path, monkeypatch) -> sqlite3.Connection:  # type: ignore[no-untyped-def]
    # Three names in the same 3-digit SIC (370/371...), one of which leaves the index in 2016.
    csv_path = tmp_path / "industry.csv"
    csv_path.write_text(
        "cik,ticker,sic,sic_description\n"
        "1,AAA,3711,Motor vehicles\n"
        "2,BBB,3713,Truck bodies\n"
        "3,CCC,3714,Motor vehicle parts\n"
        "4,ZZZ,2834,Pharmaceuticals\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(diffusion, "INDUSTRY_CSV", csv_path)

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE universe (ticker TEXT, start_date TEXT, end_date TEXT)")
    c.executemany(
        "INSERT INTO universe (ticker, start_date, end_date) VALUES (?, ?, ?)",
        [
            ("AAA", "2010-01-01", None),
            ("BBB", "2010-01-01", None),
            ("CCC", "2010-01-01", "2016-06-30"),  # left the index mid-2016
            ("ZZZ", "2010-01-01", None),
        ],
    )
    return c


def test_active_member_is_a_peer(conn: sqlite3.Connection) -> None:
    peers = diffusion.PeerMap(conn).peers("AAA", date(2014, 1, 2))
    assert set(peers) == {"BBB", "CCC"}  # both auto-industry peers, both members in 2014


def test_departed_member_excluded_after_it_leaves(conn: sqlite3.Connection) -> None:
    # After 2016-06-30, CCC is no longer a member and must not appear as a peer.
    peers = diffusion.PeerMap(conn).peers("AAA", date(2018, 1, 2))
    assert set(peers) == {"BBB"}


def test_departed_member_present_while_a_member(conn: sqlite3.Connection) -> None:
    peers = diffusion.PeerMap(conn).peers("AAA", date(2015, 5, 1))
    assert "CCC" in peers


def test_filer_never_its_own_peer(conn: sqlite3.Connection) -> None:
    assert "AAA" not in diffusion.PeerMap(conn).peers("AAA", date(2014, 1, 2))


def test_other_industry_not_a_peer(conn: sqlite3.Connection) -> None:
    # ZZZ (pharma) shares no 3-digit SIC with the auto names.
    assert "ZZZ" not in diffusion.PeerMap(conn).peers("AAA", date(2014, 1, 2))


def test_singleton_industry_has_no_peers(conn: sqlite3.Connection) -> None:
    assert diffusion.PeerMap(conn).peers("ZZZ", date(2014, 1, 2)) == []
