"""Point-in-time membership — the guard against survivorship bias (invariant 2)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from hindsight.ingest import universe
from hindsight.ingest.universe import EPOCH, Membership
from hindsight.manifest import RunManifest


class TestMembershipInterval:
    M = Membership("XYZ", "Xyz Corp", 123, date(2012, 3, 1), date(2016, 9, 15))

    def test_before_start_excluded(self) -> None:
        assert not self.M.contains(date(2012, 2, 29))

    def test_start_date_included(self) -> None:
        assert self.M.contains(date(2012, 3, 1))

    def test_middle_included(self) -> None:
        assert self.M.contains(date(2014, 6, 1))

    def test_removal_date_excluded(self) -> None:
        # Exclusive at the end: on the day it is removed it is no longer a member.
        assert not self.M.contains(date(2016, 9, 15))

    def test_day_before_removal_included(self) -> None:
        assert self.M.contains(date(2016, 9, 14))

    def test_open_interval_has_no_end(self) -> None:
        current = Membership("AAPL", "Apple", 320193, date(2000, 1, 1), None)
        assert current.contains(date(2026, 1, 1))


class TestReconstruction:
    """A synthetic Wikipedia pair, walked backwards."""

    @staticmethod
    def tables() -> list[pd.DataFrame]:
        current = pd.DataFrame(
            {
                "Symbol": ["AAA", "BBB", "CCC"],
                "Security": ["Alpha Inc", "Beta Corp", "Gamma Co"],
                "CIK": [111, 222, 333],
            }
        )
        changes = pd.DataFrame(
            {
                ("Date", ""): ["March 15, 2020", "June 1, 2015"],
                ("Added", "Ticker"): ["CCC", "BBB"],
                ("Added", "Security"): ["Gamma Co", "Beta Corp"],
                ("Removed", "Ticker"): ["DDD", "EEE"],
                ("Removed", "Security"): ["Delta Ltd", "Epsilon Plc"],
                ("Reason", ""): ["merger", "merger"],
            }
        )
        changes.columns = pd.MultiIndex.from_tuples(changes.columns)
        return [current, changes]

    @pytest.fixture
    def rebuilt(self) -> dict[str, list[Membership]]:
        out: dict[str, list[Membership]] = {}
        for m in universe.reconstruct_membership(self.tables()):
            out.setdefault(m.ticker, []).append(m)
        return out

    def test_added_ticker_starts_on_its_add_date(
        self, rebuilt: dict[str, list[Membership]]
    ) -> None:
        assert rebuilt["CCC"][0].start_date == date(2020, 3, 15)
        assert rebuilt["CCC"][0].end_date is None

    def test_never_added_member_reaches_back_to_epoch(
        self, rebuilt: dict[str, list[Membership]]
    ) -> None:
        assert rebuilt["AAA"][0].start_date == EPOCH
        assert rebuilt["AAA"][0].end_date is None

    def test_removed_companies_are_recovered(self, rebuilt: dict[str, list[Membership]]) -> None:
        # DDD and EEE are gone from today's index but must exist historically —
        # this is the entire point of the backward walk.
        assert "DDD" in rebuilt and "EEE" in rebuilt
        assert rebuilt["DDD"][0].end_date == date(2020, 3, 15)
        assert rebuilt["EEE"][0].end_date == date(2015, 6, 1)

    def test_removed_company_is_a_member_before_removal(
        self, rebuilt: dict[str, list[Membership]]
    ) -> None:
        assert rebuilt["DDD"][0].contains(date(2018, 1, 1))
        assert not rebuilt["DDD"][0].contains(date(2021, 1, 1))

    def test_ticker_added_later_is_not_a_member_earlier(
        self, rebuilt: dict[str, list[Membership]]
    ) -> None:
        assert not rebuilt["CCC"][0].contains(date(2018, 1, 1))
        assert rebuilt["CCC"][0].contains(date(2021, 1, 1))


class TestTickerNormalization:
    def test_dotted_class_shares_become_dashed(self) -> None:
        assert universe._normalize_ticker("BRK.B") == "BRK-B"

    def test_whitespace_and_case(self) -> None:
        assert universe._normalize_ticker(" aapl ") == "AAPL"


class TestFreezeRoundTrip:
    def test_csv_round_trip_preserves_intervals(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        original = [
            Membership("AAA", "Alpha Inc", 111, date(2010, 1, 1), None),
            Membership("DDD", "Delta Ltd", None, EPOCH, date(2020, 3, 15)),
        ]
        path = universe.write_frozen_csv(original, tmp_path / "u.csv")
        assert universe.load_frozen_csv(path) == original

    def test_missing_csv_gives_actionable_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(FileNotFoundError, match="--rebuild"):
            universe.load_frozen_csv(tmp_path / "nope.csv")


class TestPointInTimeQuery:
    """The CLAUDE.md acceptance test: left the index in 2016, present in 2014, absent in 2018."""

    @pytest.fixture
    def loaded(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        universe.load_to_db(
            conn,
            [
                Membership("AAPL", "Apple", 320193, date(2000, 1, 1), None),
                Membership("YHOO", "Yahoo", 1011006, date(2000, 1, 1), date(2016, 6, 20)),
            ],
        )
        return conn

    def test_departed_member_present_in_2014(self, loaded: sqlite3.Connection) -> None:
        tickers = [r["ticker"] for r in universe.members_on(loaded, date(2014, 6, 1))]
        assert tickers == ["AAPL", "YHOO"]

    def test_departed_member_absent_in_2018(self, loaded: sqlite3.Connection) -> None:
        tickers = [r["ticker"] for r in universe.members_on(loaded, date(2018, 6, 1))]
        assert tickers == ["AAPL"]

    def test_boundary_day_of_removal_is_excluded(self, loaded: sqlite3.Connection) -> None:
        assert [r["ticker"] for r in universe.members_on(loaded, date(2016, 6, 20))] == ["AAPL"]
        assert "YHOO" in [r["ticker"] for r in universe.members_on(loaded, date(2016, 6, 19))]

    def test_reload_is_idempotent(self, loaded: sqlite3.Connection) -> None:
        before = loaded.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
        universe.load_to_db(
            loaded,
            [
                Membership("AAPL", "Apple", 320193, date(2000, 1, 1), None),
                Membership("YHOO", "Yahoo", 1011006, date(2000, 1, 1), date(2016, 6, 20)),
            ],
        )
        assert loaded.execute("SELECT COUNT(*) FROM universe").fetchone()[0] == before


class TestHealth:
    def test_health_counts_members_per_year(self) -> None:
        members = [Membership(f"T{i}", f"Co {i}", i, date(2009, 1, 1), None) for i in range(500)]
        health = universe.membership_health(members)
        assert health[2018] == 500

    def test_health_reflects_departures(self) -> None:
        members = [Membership("X", "X Co", 1, date(2009, 1, 1), date(2015, 1, 1))]
        health = universe.membership_health(members)
        assert health[2014] == 1
        assert health[2016] == 0


class TestManifestRecordsExclusions:
    """Gaps in Wikipedia's 'selected changes' table must surface as counted exclusions."""

    @staticmethod
    def _tables_with_orphan_add() -> list[pd.DataFrame]:
        # ZZZ is recorded as added but is not in today's index, so its removal row is
        # missing from the source. That is a real gap and must not pass unnoticed.
        current = pd.DataFrame({"Symbol": ["AAA"], "Security": ["Alpha Inc"], "CIK": [111]})
        changes = pd.DataFrame(
            {
                ("Date", ""): ["March 15, 2020"],
                ("Added", "Ticker"): ["ZZZ"],
                ("Added", "Security"): ["Zeta Inc"],
                ("Removed", "Ticker"): [None],
                ("Removed", "Security"): [None],
                ("Reason", ""): ["addition"],
            }
        )
        changes.columns = pd.MultiIndex.from_tuples(changes.columns)
        return [current, changes]

    def test_orphan_addition_is_counted(self) -> None:
        manifest = RunManifest("test")
        universe.reconstruct_membership(self._tables_with_orphan_add(), manifest)
        assert manifest.exclusions["universe_add_without_open_interval"] == 1
        assert "ZZZ 2020-03-15" in manifest.exclusion_examples["universe_add_without_open_interval"]

    def test_unparseable_dates_are_counted(self) -> None:
        current = pd.DataFrame({"Symbol": ["AAA"], "Security": ["Alpha Inc"], "CIK": [111]})
        changes = pd.DataFrame(
            {
                ("Date", ""): ["not a date"],
                ("Added", "Ticker"): ["BBB"],
                ("Added", "Security"): ["Beta"],
                ("Removed", "Ticker"): [None],
                ("Removed", "Security"): [None],
                ("Reason", ""): ["x"],
            }
        )
        changes.columns = pd.MultiIndex.from_tuples(changes.columns)
        manifest = RunManifest("test")
        universe.reconstruct_membership([current, changes], manifest)
        assert manifest.exclusions["universe_unparseable_change_date"] == 1
