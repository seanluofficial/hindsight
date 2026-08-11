"""Experiment 004 — information staleness / first-disclosure (diagnostic).

For each 8-K, split the abnormal move into what happened *before* the filing reached
EDGAR and what happened *after*, using daily prices only:

    pre-move  = market-excess return, close before the event date -> entry open
    post-move = market-excess return, entry open -> exit (5 trading days)
    staleness = |pre| / (|pre| + |post|)   in [0, 1]

staleness ~ 1.0 means the reaction was essentially over before the filing (stale);
~ 0.0 means the filing was the market's first look. The event date is the filing's
`period_of_report` ("Date of earliest event reported"); filings lacking it are excluded
and counted (invariant 5). Daily bars can't see the intraday reaction, so this is a
coarse first pass — the precise version lives in the future Reaction Gap branch.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, datetime

from hindsight import config, trading_calendar
from hindsight.evaluate.returns import PriceLookup, window_return
from hindsight.manifest import RunManifest

STALENESS_HORIZON = 5  # trading days for the post-filing window


def _excess(prices: PriceLookup, ticker: str, entry: date, exit_day: date) -> float | None:
    """Market-excess open-to-close return, ticker minus SPY, over the same window."""
    stock = window_return(prices, ticker, entry, exit_day)
    if stock is None:
        return None
    bench = window_return(prices, config.BENCHMARK_TICKER, entry, exit_day)
    if bench is None:
        return None
    return stock - bench


def _close_to_open_excess(
    prices: PriceLookup, ticker: str, close_day: date, open_day: date
) -> float | None:
    """Market-excess return from one session's close to a later session's open."""
    s_from = prices.bar(ticker, close_day)
    s_to = prices.bar(ticker, open_day)
    b_from = prices.bar(config.BENCHMARK_TICKER, close_day)
    b_to = prices.bar(config.BENCHMARK_TICKER, open_day)
    if not (s_from and s_to and b_from and b_to) or s_from.adj_close <= 0 or b_from.adj_close <= 0:
        return None
    stock = s_to.adj_open / s_from.adj_close - 1.0
    bench = b_to.adj_open / b_from.adj_close - 1.0
    return stock - bench


@dataclass(frozen=True)
class Staleness:
    accession_no: str
    partition: str
    pre_excess: float
    post_excess: float

    @property
    def fraction(self) -> float:
        denom = abs(self.pre_excess) + abs(self.post_excess)
        return abs(self.pre_excess) / denom if denom > 0 else 0.0


def staleness_for(
    accession_no: str,
    ticker: str,
    accepted_at_utc: str,
    period_of_report: str | None,
    prices: PriceLookup,
    manifest: RunManifest | None = None,
) -> Staleness | None:
    def drop(reason: str) -> None:
        if manifest:
            manifest.exclude(reason, accession_no)

    if not period_of_report:
        drop("no_event_date")
        return None
    try:
        event_date = date.fromisoformat(period_of_report[:10])
    except ValueError:
        drop("unparseable_event_date")
        return None

    entry = trading_calendar.entry_date_for(datetime.fromisoformat(accepted_at_utc))
    try:
        event_session = trading_calendar.trading_day_on_or_after(event_date)
        pre_start = trading_calendar.previous_trading_day(event_session)
        exit_day = trading_calendar.add_trading_days(entry, STALENESS_HORIZON)
    except ValueError:
        drop("calendar_edge")
        return None

    # The event must precede entry for a pre-window to exist; if not, it isn't stale.
    if pre_start >= entry:
        drop("event_not_before_entry")
        return None
    if not prices.has_ticker(ticker):
        drop("no_price_coverage_for_ticker")
        return None
    prior = prices.prior_close(ticker, entry)
    if prior is None or prior < config.MIN_PRIOR_CLOSE_USD:
        drop("no_prior_close_or_penny")
        return None

    pre = _close_to_open_excess(prices, ticker, pre_start, entry)
    if pre is None:
        drop("missing_pre_window_price")
        return None
    post = _excess(prices, ticker, entry, exit_day)
    if post is None:
        drop("missing_post_window_price")
        return None

    return Staleness(
        accession_no=accession_no,
        partition=config.partition_of(accepted_at_utc),
        pre_excess=pre,
        post_excess=post,
    )


@dataclass(frozen=True)
class StalenessResult:
    partition: str
    n: int
    median_fraction: float
    mean_fraction: float
    share_mostly_stale: float  # fraction of filings with staleness > 0.5

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "n": self.n,
            "median_fraction": self.median_fraction,
            "mean_fraction": self.mean_fraction,
            "share_mostly_stale": self.share_mostly_stale,
        }


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
) -> list[StalenessResult]:
    rows = list(
        conn.execute(
            "SELECT accession_no, ticker, accepted_at_utc, period_of_report FROM filings "
            "ORDER BY accepted_at_utc, accession_no"
        )
    )
    prices = PriceLookup(conn)
    manifest.count("filings_considered", len(rows))

    fractions: dict[str, list[float]] = {p: [] for p in partitions}
    for row in rows:
        s = staleness_for(
            row["accession_no"],
            row["ticker"],
            row["accepted_at_utc"],
            row["period_of_report"],
            prices,
            manifest,
        )
        if s is None or s.partition not in fractions:
            continue
        fractions[s.partition].append(s.fraction)

    results: list[StalenessResult] = []
    for partition in partitions:
        vals = fractions[partition]
        manifest.count(f"{partition}_evaluated", len(vals))
        if not vals:
            results.append(StalenessResult(partition, 0, 0.0, 0.0, 0.0))
            continue
        results.append(
            StalenessResult(
                partition=partition,
                n=len(vals),
                median_fraction=statistics.median(vals),
                mean_fraction=statistics.fmean(vals),
                share_mostly_stale=sum(1 for v in vals if v > 0.5) / len(vals),
            )
        )
    return results
