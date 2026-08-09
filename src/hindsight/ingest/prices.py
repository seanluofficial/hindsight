"""Daily OHLC from Tiingo, plus the SPY benchmark.

Tiingo was chosen over the free alternatives because it keeps serving history for tickers
that have since been delisted or acquired. Those are precisely the names a survivorship-
biased study loses, and losing them is what makes a backtest look better than reality.

**Adjustment.** The schema stores raw OHLC alongside `adj_close`. Returns must never mix
the two: a 2-for-1 split between entry and exit would show up as a -50% move. Tiingo's
adjustment is uniform within a day, so the correct entry price is

    adj_open = open * (adj_close / close)

and the same factor recovers adjusted high/low. The evaluate stage is required to apply
it; `adjustment_factor()` below exists so there is exactly one implementation.

**Rate limits.** The Tiingo free tier caps unique symbols per hour and per month. A full
2010-2024 universe runs to ~1,100 distinct tickers and will exceed it. Ingest is
therefore resumable: tickers already covered are skipped, so the job can be re-run across
several sessions, or against a paid tier, without refetching.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import requests

from hindsight import config, trading_calendar
from hindsight.ingest.http import CachedFetcher, RateLimiter, RateLimitExhaustedError
from hindsight.manifest import RunManifest

log = logging.getLogger(__name__)

# Well under Tiingo's ceiling; the bottleneck is their hourly symbol cap, not throughput.
_tiingo_limiter = RateLimiter(max_per_second=5.0)

_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume")


# Tiingo reports quota exhaustion as HTTP 200 with a plain-text body. Two variants seen:
# the hourly allocation, and the free tier's 500-unique-symbols-per-month cap.
_QUOTA_MARKERS = (
    b"run over your",
    b"symbol look up",
    b"hourly request allocation",
    b"upgrade at https://api.tiingo.com/pricing",
)


def looks_like_quota_error(body: bytes) -> bool:
    """True if this 200 response is really a quota refusal.

    Tiingo does not use 429 for these, so status codes alone cannot catch them.
    """
    head = body[:400].lower()
    return any(marker in head for marker in _QUOTA_MARKERS)


def _reject_quota_bodies(body: bytes) -> None:
    """Validator: refuse to cache a quota error.

    Without this the error text is written to `data/raw/` and every later run reads the
    stored error instead of retrying — the ticker would never recover, even after the cap
    resets. That is silent, permanent data loss, and it looks identical to missing coverage.
    """
    if looks_like_quota_error(body):
        raise RateLimitExhaustedError(body[:200].decode("utf-8", errors="replace").strip())


def purge_poisoned_cache(dry_run: bool = False) -> list[str]:
    """Delete cached Tiingo responses that are really quota errors.

    Needed once, because these were cached before the validator existed. Returns the
    paths removed so the count lands in a manifest rather than happening invisibly.
    """
    root = config.RAW_DIR / "api.tiingo.com"
    removed: list[str] = []
    if not root.exists():
        return removed
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            head = path.read_bytes()[:400]
        except OSError:
            continue
        if looks_like_quota_error(head):
            removed.append(str(path))
            if not dry_run:
                path.unlink()
    return removed


def make_tiingo_fetcher() -> CachedFetcher:
    """A fetcher authenticated by header.

    The token goes in a header rather than the query string on purpose: the disk cache is
    keyed by URL, and a token in the query would be written into filenames under data/raw/.
    """
    fetcher = CachedFetcher(
        user_agent=config.EDGAR_USER_AGENT,
        limiter=_tiingo_limiter,
        max_retries=3,
        body_validator=_reject_quota_bodies,
    )
    fetcher.session.headers.update(
        {
            "Content-Type": "application/json",
            "Authorization": f"Token {config.tiingo_api_key()}",
        }
    )
    return fetcher


def adjustment_factor(close: float | None, adj_close: float | None) -> float:
    """Split/dividend factor for one day. Returns 1.0 when it cannot be computed."""
    if not close or adj_close is None:
        return 1.0
    return adj_close / close


def prices_url(ticker: str, start: date, end: date) -> str:
    symbol = ticker.lower()
    return (
        f"{config.TIINGO_BASE_URL}/{symbol}/prices"
        f"?startDate={start.isoformat()}&endDate={end.isoformat()}&format=json"
    )


def fetch_prices(
    ticker: str, start: date, end: date, fetcher: CachedFetcher
) -> list[dict[str, Any]]:
    """Daily bars for one ticker. Empty list means Tiingo has no coverage."""
    raw = fetcher.get_text(prices_url(ticker, start, end), encoding="utf-8")
    if not raw.strip():
        return []
    # Belt and braces: the fetcher refuses to cache these, but an entry cached before that
    # check existed must still not be mistaken for absent data.
    if looks_like_quota_error(raw.encode("utf-8", errors="replace")):
        raise RateLimitExhaustedError(f"quota error in response for {ticker}")
    payload: object = json.loads(raw)
    if isinstance(payload, dict):
        # Tiingo reports errors as a JSON object rather than a list.
        raise RuntimeError(f"Tiingo error for {ticker}: {payload.get('detail', payload)}")
    if not isinstance(payload, list):
        raise RuntimeError(
            f"Tiingo returned {type(payload).__name__} for {ticker}, expected a list"
        )
    return [bar for bar in payload if isinstance(bar, dict)]


def _row_to_tuple(ticker: str, bar: dict[str, Any]) -> tuple[Any, ...]:
    day = datetime.fromisoformat(bar["date"].replace("Z", "+00:00")).date()
    return (
        ticker,
        day.isoformat(),
        bar.get("open"),
        bar.get("high"),
        bar.get("low"),
        bar.get("close"),
        bar.get("adjClose"),
        bar.get("volume"),
    )


def upsert_prices(conn: sqlite3.Connection, ticker: str, bars: list[dict[str, Any]]) -> int:
    rows = [_row_to_tuple(ticker, b) for b in bars if b.get("date")]
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO prices (ticker, date, {", ".join(_COLUMNS)})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


# How far stored data may fall short of a window edge and still count as covering it.
# Absorbs weekends, holidays and the gap between an index-membership date and the first
# actual trade, without being loose enough to accept a year of missing history.
_COVERAGE_TOLERANCE_DAYS = 21


def covered_tickers(conn: sqlite3.Connection, start: date, end: date) -> set[str]:
    """Tickers whose stored history actually *spans* the requested window.

    Emphatically not "has at least one bar in the window", which was the original test and
    was wrong in the case that matters most: extending a window. Having fetched 2018 for
    512 tickers, asking for 2010-2024 would report all 512 as covered, skip them, and
    silently leave fourteen years unfetched — while consuming a month of vendor quota
    fetching nothing.

    Window edges are clamped to index membership, because a company that joined in 2015 or
    was acquired in 2019 cannot have prices outside that span and must not be re-fetched
    forever chasing history that does not exist.
    """
    rows = conn.execute(
        """
        SELECT p.ticker,
               MIN(p.date) AS first_bar,
               MAX(p.date) AS last_bar,
               MIN(u.start_date) AS member_from,
               MAX(COALESCE(u.end_date, '9999-12-31')) AS member_to
          FROM prices p LEFT JOIN universe u ON u.ticker = p.ticker
         GROUP BY p.ticker
        """
    ).fetchall()

    tolerance = timedelta(days=_COVERAGE_TOLERANCE_DAYS)
    covered: set[str] = set()
    for row in rows:
        first = date.fromisoformat(row["first_bar"])
        last = date.fromisoformat(row["last_bar"])
        member_from = date.fromisoformat(row["member_from"]) if row["member_from"] else start
        member_to_raw = row["member_to"] or "9999-12-31"
        member_to = end if member_to_raw == "9999-12-31" else date.fromisoformat(member_to_raw)

        need_from = max(start, member_from)
        need_to = min(end, member_to)
        if need_from > need_to:
            # Never a member during this window; nothing to fetch.
            covered.add(row["ticker"])
            continue
        if first <= need_from + tolerance and last >= need_to - tolerance:
            covered.add(row["ticker"])
    return covered


def ingest_prices(
    conn: sqlite3.Connection,
    tickers: list[str],
    start: date,
    end: date,
    manifest: RunManifest,
    fetcher: CachedFetcher | None = None,
    skip_covered: bool = True,
) -> int:
    """Fetch daily bars for `tickers`, plus the benchmark. Resumable."""
    fetcher = fetcher or make_tiingo_fetcher()

    # The benchmark goes first, always. Returns are market-excess (§5), so a run that
    # exhausts its quota before reaching SPY produces a table that cannot be evaluated at
    # all — and alphabetical order buries SPY near the end of ~500 names.
    others = sorted({t.upper() for t in tickers} - {config.BENCHMARK_TICKER})
    wanted = [config.BENCHMARK_TICKER, *others]

    if skip_covered:
        already = covered_tickers(conn, start, end)
        skipped = [t for t in wanted if t in already]
        wanted = [t for t in wanted if t not in already]
        if skipped:
            manifest.count("tickers_already_covered", len(skipped))
            log.info("skipping %d tickers already covered", len(skipped))

    total_rows = 0
    for i, ticker in enumerate(wanted, 1):
        try:
            bars = fetch_prices(ticker, start, end, fetcher)
        except RateLimitExhaustedError:
            # The hourly allocation is spent. Stop cleanly: every remaining ticker is
            # simply unattempted, and calling them "no coverage" would fabricate a
            # survivorship signal. Progress so far is committed, and `skip_covered`
            # means the next run picks up exactly where this one stopped.
            remaining = len(wanted) - i + 1
            manifest.count("halted_on_rate_limit")
            manifest.count("tickers_unattempted", remaining)
            manifest.error(
                f"Tiingo hourly allocation exhausted after {i - 1} tickers; "
                f"{remaining} unattempted. Re-run to resume — nothing is lost."
            )
            log.warning("rate limit hit; stopping with %d tickers unattempted", remaining)
            break
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status == 404:
                # No coverage. Overwhelmingly a delisted or renamed ticker — the exact
                # population invariant 2 protects, so it is counted loudly, not skipped.
                manifest.exclude("tiingo_no_coverage", ticker)
            else:
                manifest.exclude(f"tiingo_http_{status}", ticker)
            continue
        except Exception as exc:  # noqa: BLE001
            manifest.exclude("tiingo_fetch_failed", f"{ticker}: {exc}")
            continue

        if not bars:
            manifest.exclude("tiingo_empty_response", ticker)
            continue

        n = upsert_prices(conn, ticker, bars)
        total_rows += n
        manifest.count("price_rows_written", n)
        manifest.count("tickers_fetched")
        if i % 50 == 0:
            log.info("prices: %d/%d tickers", i, len(wanted))

    return total_rows


def coverage_report(
    conn: sqlite3.Connection, start: date, end: date, sample: int = 10
) -> dict[str, Any]:
    """Compare stored bars against the NYSE session count — the sanity check for Phase 1."""
    expected = len(trading_calendar.trading_days(start, end))
    rows = list(
        conn.execute(
            """
            SELECT ticker, COUNT(*) AS n
              FROM prices
             WHERE date BETWEEN ? AND ?
             GROUP BY ticker
             ORDER BY n ASC
            """,
            (start.isoformat(), end.isoformat()),
        )
    )
    benchmark = next((r["n"] for r in rows if r["ticker"] == config.BENCHMARK_TICKER), 0)
    full = sum(1 for r in rows if r["n"] >= expected * 0.98)
    return {
        "expected_sessions": expected,
        "tickers_with_prices": len(rows),
        "tickers_near_full_coverage": full,
        "benchmark_sessions": benchmark,
        "benchmark_ticker": config.BENCHMARK_TICKER,
        "thinnest": [{"ticker": r["ticker"], "sessions": r["n"]} for r in rows[:sample]],
    }
