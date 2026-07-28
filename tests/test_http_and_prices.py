"""Caching behaviour and price adjustment arithmetic."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from hindsight import config
from hindsight.ingest import http, prices
from hindsight.manifest import RunManifest


class TestCachePaths:
    def test_mirrors_remote_path_so_cache_is_browsable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "RAW_DIR", tmp_path)
        path = http.cache_path_for(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019318000005/x.htm"
        )
        assert (
            path
            == tmp_path
            / "www.sec.gov"
            / "Archives"
            / "edgar"
            / "data"
            / "320193"
            / "000032019318000005"
            / "x.htm"
        )

    def test_query_string_is_folded_into_the_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "RAW_DIR", tmp_path)
        path = http.cache_path_for(
            "https://api.tiingo.com/tiingo/daily/aapl/prices?startDate=2018-01-01"
        )
        assert "startDate" in path.name

    def test_no_traversal_from_hostile_urls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "RAW_DIR", tmp_path)
        path = http.cache_path_for("https://evil.test/../../etc/passwd")
        assert tmp_path in path.parents


class TestRateLimiter:
    def test_enforces_minimum_interval(self) -> None:
        import time

        limiter = http.RateLimiter(max_per_second=20.0)
        start = time.monotonic()
        for _ in range(4):
            limiter.wait()
        # 4 calls at 20/s means at least 3 intervals of 50ms.
        assert time.monotonic() - start >= 0.12


class TestAdjustment:
    """A split between entry and exit must not read as a -50% return."""

    def test_factor_for_two_for_one_split(self) -> None:
        assert prices.adjustment_factor(close=100.0, adj_close=50.0) == pytest.approx(0.5)

    def test_adjusted_open_uses_same_day_factor(self) -> None:
        factor = prices.adjustment_factor(close=100.0, adj_close=50.0)
        assert 96.0 * factor == pytest.approx(48.0)

    def test_unadjusted_day_is_identity(self) -> None:
        assert prices.adjustment_factor(close=100.0, adj_close=100.0) == pytest.approx(1.0)

    def test_missing_data_degrades_to_one(self) -> None:
        assert prices.adjustment_factor(None, 50.0) == 1.0
        assert prices.adjustment_factor(100.0, None) == 1.0
        assert prices.adjustment_factor(0.0, 50.0) == 1.0


class TestUpsert:
    BARS = [
        {
            "date": "2018-02-01T00:00:00.000Z",
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "adjClose": 1.4,
            "volume": 1000,
        },
        {
            "date": "2018-02-02T00:00:00.000Z",
            "open": 1.5,
            "high": 2.5,
            "low": 1.0,
            "close": 2.0,
            "adjClose": 1.9,
            "volume": 2000,
        },
    ]

    def test_writes_rows(self, conn: sqlite3.Connection) -> None:
        assert prices.upsert_prices(conn, "AAPL", self.BARS) == 2
        row = conn.execute("SELECT * FROM prices WHERE date='2018-02-01'").fetchone()
        assert row["ticker"] == "AAPL"
        assert row["adj_close"] == pytest.approx(1.4)

    def test_tiingo_timestamp_becomes_plain_date(self, conn: sqlite3.Connection) -> None:
        prices.upsert_prices(conn, "AAPL", self.BARS)
        dates = [r[0] for r in conn.execute("SELECT date FROM prices ORDER BY date")]
        assert dates == ["2018-02-01", "2018-02-02"]

    def test_reingest_does_not_duplicate(self, conn: sqlite3.Connection) -> None:
        prices.upsert_prices(conn, "AAPL", self.BARS)
        prices.upsert_prices(conn, "AAPL", self.BARS)
        assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 2

    def test_covered_tickers_supports_resume(self, conn: sqlite3.Connection) -> None:
        prices.upsert_prices(conn, "AAPL", self.BARS)
        covered = prices.covered_tickers(conn, date(2018, 1, 1), date(2018, 12, 31))
        assert covered == {"AAPL"}
        assert prices.covered_tickers(conn, date(2019, 1, 1), date(2019, 12, 31)) == set()


class TestCoverageReport:
    def test_counts_against_real_session_count(self, conn: sqlite3.Connection) -> None:
        prices.upsert_prices(conn, "AAPL", TestUpsert.BARS)
        report = prices.coverage_report(conn, date(2018, 1, 1), date(2018, 12, 31))
        assert report["expected_sessions"] == 251
        assert report["tickers_with_prices"] == 1
        # 2 of 251 sessions is nowhere near full coverage, and must be reported as such.
        assert report["tickers_near_full_coverage"] == 0


class TestRateLimitIsNotMistakenForMissingData:
    """A spent quota must never be recorded as absent coverage.

    Conflating the two would invent a survivorship signal: tickers the vendor simply
    wasn't asked about would look like tickers it had no data for.
    """

    class QuotaFetcher:
        hits = misses = 0

        def __init__(self, allow: int) -> None:
            self.allow = allow
            self.calls = 0

        def get_text(self, url: str, **kwargs: object) -> str:
            self.calls += 1
            if self.calls > self.allow:
                raise http.RateLimitExhaustedError("hourly allocation spent")
            return json.dumps(TestUpsert.BARS)

    def test_benchmark_is_fetched_before_the_quota_can_run_out(
        self, conn: sqlite3.Connection
    ) -> None:
        """Without SPY no excess return is computable, so it cannot be last in line."""
        manifest = RunManifest("test")
        prices.ingest_prices(
            conn,
            ["AAA", "BBB", "CCC", "ZZZ"],
            date(2018, 1, 1),
            date(2018, 12, 31),
            manifest,
            fetcher=self.QuotaFetcher(allow=1),  # only one request succeeds
        )
        covered = prices.covered_tickers(conn, date(2018, 1, 1), date(2018, 12, 31))
        assert covered == {config.BENCHMARK_TICKER}

    def test_run_halts_instead_of_marking_the_rest_unavailable(
        self, conn: sqlite3.Connection
    ) -> None:
        manifest = RunManifest("test")
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        prices.ingest_prices(
            conn,
            tickers,
            date(2018, 1, 1),
            date(2018, 12, 31),
            manifest,
            fetcher=self.QuotaFetcher(allow=2),  # type: ignore[arg-type]
        )
        assert manifest.counts["halted_on_rate_limit"] == 1
        # Nothing was blamed on the vendor lacking data.
        assert manifest.exclusions.get("tiingo_no_coverage", 0) == 0
        assert manifest.exclusions.get("tiingo_fetch_failed", 0) == 0

    def test_unattempted_tickers_are_counted(self, conn: sqlite3.Connection) -> None:
        manifest = RunManifest("test")
        prices.ingest_prices(
            conn,
            ["AAA", "BBB", "CCC", "DDD"],
            date(2018, 1, 1),
            date(2018, 12, 31),
            manifest,
            fetcher=self.QuotaFetcher(allow=2),  # type: ignore[arg-type]
        )
        # 5 wanted (4 + SPY); 2 succeeded, the 3rd hit the wall, so 3 go unattempted.
        assert manifest.counts["tickers_unattempted"] == 3
        assert any("resume" in e for e in manifest.errors)

    def test_progress_before_the_wall_is_committed(self, conn: sqlite3.Connection) -> None:
        manifest = RunManifest("test")
        prices.ingest_prices(
            conn,
            ["AAA", "BBB", "CCC", "DDD"],
            date(2018, 1, 1),
            date(2018, 12, 31),
            manifest,
            fetcher=self.QuotaFetcher(allow=2),  # type: ignore[arg-type]
        )
        assert len(prices.covered_tickers(conn, date(2018, 1, 1), date(2018, 12, 31))) == 2

    def test_resume_skips_what_already_landed(self, conn: sqlite3.Connection) -> None:
        for attempt in range(2):
            manifest = RunManifest("test")
            prices.ingest_prices(
                conn,
                ["AAA", "BBB", "CCC", "DDD"],
                date(2018, 1, 1),
                date(2018, 12, 31),
                manifest,
                fetcher=self.QuotaFetcher(allow=2),  # type: ignore[arg-type]
            )
            if attempt == 1:
                assert manifest.counts["tickers_already_covered"] == 2
        # Two runs of two tickers each covers all four plus the benchmark.
        assert len(prices.covered_tickers(conn, date(2018, 1, 1), date(2018, 12, 31))) == 4


class TestNoCoverageIsRecorded:
    def test_missing_ticker_is_an_exclusion_not_a_silent_skip(
        self, conn: sqlite3.Connection
    ) -> None:
        """A delisted ticker Tiingo cannot serve is exactly what invariant 2 protects."""

        class FailingFetcher:
            hits = misses = 0

            def get_text(self, url: str, **kwargs: object) -> str:
                raise RuntimeError("no coverage")

        manifest = RunManifest("test")
        prices.ingest_prices(
            conn,
            ["DEADCO"],
            date(2018, 1, 1),
            date(2018, 12, 31),
            manifest,
            fetcher=FailingFetcher(),  # type: ignore[arg-type]
        )
        assert manifest.exclusions["tiingo_fetch_failed"] == 2  # DEADCO and the benchmark
        assert manifest.total_excluded == 2
