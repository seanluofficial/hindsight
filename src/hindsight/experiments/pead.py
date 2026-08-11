"""Experiment 005 — post-earnings-announcement drift (PEAD).

The first experiment built *after* diagnosing why 001-004 were nulls: they all
predicted the announcement reaction itself, at the next open, over 1-20 days — the
part the market prices fastest. 005 instead rides the drift that classically
*continues* after an earnings surprise.

    surprise = market-excess return, close before the earnings date -> entry open
               (exactly Experiment 004's pre-filing window; observable at entry, no lookahead)
    drift    = market-excess return, entry open -> exit (H trading days), via the shared harness

Each calendar month, earnings 8-Ks (item 2.02) are sorted into quintiles by surprise;
we long the top quintile (biggest positive surprise) and short the bottom, hold H days,
and net out costs. H1 (PEAD): drift continues in the surprise direction, so the long/short
earns a positive Sharpe. Kill criteria and the 0.30 economic floor live in
experiments/005-post-earnings-drift/HYPOTHESIS.md.

No LLM, no anonymization, ~$0. Timing and exclusions reuse the shared harness so 005
cannot drift from the invariants.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from hindsight import config, trading_calendar
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import filing_excess_return
from hindsight.manifest import RunManifest

EARNINGS_ITEM = "2.02"
# PEAD is classically a multi-week drift. 20d (~1 month) is primary — minimal overlap with
# monthly rebalancing; 40/60d are secondary and their t-stats are optimistic under overlap.
PEAD_HORIZONS: tuple[int, ...] = (20, 40, 60)


def is_earnings(item_codes: str | None) -> bool:
    return EARNINGS_ITEM in {c.strip() for c in (item_codes or "").split(",") if c.strip()}


def _close_to_open_excess(
    prices: PriceLookup, ticker: str, close_day: date, open_day: date
) -> float | None:
    """Market-excess return from one session's close to a later session's open (stock - SPY)."""
    s_from = prices.bar(ticker, close_day)
    s_to = prices.bar(ticker, open_day)
    b_from = prices.bar(config.BENCHMARK_TICKER, close_day)
    b_to = prices.bar(config.BENCHMARK_TICKER, open_day)
    if not (s_from and s_to and b_from and b_to) or s_from.adj_close <= 0 or b_from.adj_close <= 0:
        return None
    stock = s_to.adj_open / s_from.adj_close - 1.0
    bench = b_to.adj_open / b_from.adj_close - 1.0
    return stock - bench


def surprise_for(
    ticker: str,
    accepted_at_utc: str,
    period_of_report: str | None,
    prices: PriceLookup,
    accession_no: str,
    manifest: RunManifest | None = None,
) -> float | None:
    """The pre-filing market-excess move (the surprise proxy), or None with a counted reason.

    Mirrors the pre-window guards of Experiment 004's `staleness_for` exactly, so the surprise
    and the staleness diagnostic describe the same window.
    """

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
    except ValueError:
        drop("calendar_edge")
        return None

    if pre_start >= entry:  # need a real pre-window
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
    return pre


@dataclass(frozen=True)
class Scored:
    accession_no: str
    ticker: str
    accepted_at_utc: str
    partition: str
    surprise: float


def compute_surprises(conn: sqlite3.Connection, manifest: RunManifest) -> list[Scored]:
    """Surprise proxy for every earnings 8-K with a usable pre-window."""
    rows = list(
        conn.execute(
            "SELECT accession_no, ticker, accepted_at_utc, period_of_report, item_codes "
            "FROM filings ORDER BY accepted_at_utc, accession_no"
        )
    )
    manifest.count("filings_considered", len(rows))
    prices = PriceLookup(conn)

    scored: list[Scored] = []
    earnings = 0
    for r in rows:
        if not is_earnings(r["item_codes"]):
            continue
        earnings += 1
        s = surprise_for(
            r["ticker"],
            r["accepted_at_utc"],
            r["period_of_report"],
            prices,
            r["accession_no"],
            manifest,
        )
        if s is None:
            continue
        scored.append(
            Scored(
                accession_no=r["accession_no"],
                ticker=r["ticker"],
                accepted_at_utc=r["accepted_at_utc"],
                partition=config.partition_of(r["accepted_at_utc"]),
                surprise=s,
            )
        )
    manifest.count("earnings_filings", earnings)
    manifest.count("scored", len(scored))
    return scored


@dataclass(frozen=True)
class PeadResult:
    partition: str
    horizon: int
    cost_bps: float
    n_months: int
    n_positions: int
    mean_monthly: float
    sharpe_annualized: float
    t_statistic: float
    max_drawdown: float

    @property
    def is_meaningful(self) -> bool:
        return self.n_months >= MONTHS_PER_YEAR

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "horizon": self.horizon,
            "cost_bps": self.cost_bps,
            "n_months": self.n_months,
            "n_positions": self.n_positions,
            "mean_monthly": self.mean_monthly,
            "sharpe_annualized": self.sharpe_annualized,
            "t_statistic": self.t_statistic,
            "max_drawdown": self.max_drawdown,
            "is_meaningful": self.is_meaningful,
        }


def _by_month(
    scored_with_return: list[tuple[Scored, float, str]],
) -> list[tuple[str, list[tuple[Scored, float]]]]:
    """Group (scored, return, month) into sorted (month, [(scored, return), ...]) buckets."""
    buckets: dict[str, list[tuple[Scored, float]]] = defaultdict(list)
    for s, ret, month in scored_with_return:
        buckets[month].append((s, ret))
    return sorted(buckets.items())


def _quintile_long_short_monthly(
    scored_with_return: list[tuple[Scored, float, str]], cost_bps: float
) -> list[tuple[str, float]]:
    """Monthly long-high-surprise / short-low-surprise returns, labeled by month.

    Within a month, sort by surprise; long the top quintile (biggest positive surprise), short
    the bottom quintile. If PEAD holds, both legs earn positive drift, so the series is positive.
    """
    series: list[tuple[str, float]] = []
    for month, group in _by_month(scored_with_return):
        if len(group) < 5:
            continue
        ordered = sorted(group, key=lambda sr: sr[0].surprise)
        size = len(ordered) // 5
        if size == 0:
            continue
        low_surprise = ordered[:size]  # short these
        high_surprise = ordered[-size:]  # long these
        long_leg = statistics.fmean(ret - cost_bps / 10_000.0 for _, ret in high_surprise)
        short_leg = statistics.fmean(-ret - cost_bps / 10_000.0 for _, ret in low_surprise)
        series.append((month, (long_leg + short_leg) / 2.0))
    return series


def _long_only_monthly(
    scored_with_return: list[tuple[Scored, float, str]], cost_bps: float
) -> list[tuple[str, float]]:
    """Monthly long-only top-surprise-quintile market-excess returns, labeled by month.

    PEAD is classically stronger on the long side; this is the pre-registered variant that
    drops the short leg (where borrow cost and the post-2000 decay bite hardest).
    """
    series: list[tuple[str, float]] = []
    for month, group in _by_month(scored_with_return):
        if len(group) < 5:
            continue
        ordered = sorted(group, key=lambda sr: sr[0].surprise)
        size = len(ordered) // 5
        if size == 0:
            continue
        top = ordered[-size:]  # long the biggest positive surprises
        series.append((month, statistics.fmean(ret - cost_bps / 10_000.0 for _, ret in top)))
    return series


def _series_stats(values: list[float]) -> dict[str, object]:
    """Annualized Sharpe, t-stat and drawdown of a monthly return series."""
    n = len(values)
    mean = statistics.fmean(values) if values else 0.0
    stdev = statistics.stdev(values) if n > 1 else 0.0
    sharpe = (mean / stdev) * math.sqrt(MONTHS_PER_YEAR) if stdev > 0 else 0.0
    t = mean / (stdev / math.sqrt(n)) if n > 1 and stdev > 0 else 0.0
    return {
        "months": n,
        "mean_monthly": mean,
        "sharpe_annualized": sharpe,
        "t_statistic": t,
        "max_drawdown": max_drawdown(values),
    }


def evaluate(
    conn: sqlite3.Connection,
    scored: list[Scored],
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
    horizons: tuple[int, ...] = PEAD_HORIZONS,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> list[PeadResult]:
    prices = PriceLookup(conn)
    results: list[PeadResult] = []
    for horizon in horizons:
        rows_by_part: dict[str, list[tuple[Scored, float, str]]] = {p: [] for p in partitions}
        for s in scored:
            if s.partition not in rows_by_part:
                continue
            fr = filing_excess_return(
                s.accession_no, s.ticker, s.accepted_at_utc, horizon, prices, manifest
            )
            if fr is None:
                continue
            rows_by_part[s.partition].append(
                (s, fr.excess_return, fr.entry_date.strftime("%Y-%m"))
            )

        for partition in partitions:
            data = rows_by_part[partition]
            series = [v for _, v in _quintile_long_short_monthly(data, cost_bps)]
            n = len(series)
            mean = statistics.fmean(series) if series else 0.0
            stdev = statistics.stdev(series) if n > 1 else 0.0
            sharpe = (mean / stdev) * math.sqrt(MONTHS_PER_YEAR) if stdev > 0 else 0.0
            t = mean / (stdev / math.sqrt(n)) if n > 1 and stdev > 0 else 0.0
            results.append(
                PeadResult(
                    partition=partition,
                    horizon=horizon,
                    cost_bps=cost_bps,
                    n_months=n,
                    n_positions=len(data),
                    mean_monthly=mean,
                    sharpe_annualized=sharpe,
                    t_statistic=t,
                    max_drawdown=max_drawdown(series),
                )
            )
    return results


def _drift_data(
    conn: sqlite3.Connection, scored: list[Scored], horizon: int, partition: str
) -> list[tuple[Scored, float, str]]:
    """(scored, drift excess return, entry month) for one horizon and partition."""
    prices = PriceLookup(conn)
    out: list[tuple[Scored, float, str]] = []
    for s in scored:
        if s.partition != partition:
            continue
        fr = filing_excess_return(s.accession_no, s.ticker, s.accepted_at_utc, horizon, prices)
        if fr is None:
            continue
        out.append((s, fr.excess_return, fr.entry_date.strftime("%Y-%m")))
    return out


def _by_year(labeled: list[tuple[str, float]]) -> list[dict[str, object]]:
    """Per-calendar-year Sharpe of a labeled monthly series (decay check)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for month, val in labeled:
        buckets[month[:4]].append(val)
    out: list[dict[str, object]] = []
    for year, vals in sorted(buckets.items()):
        stats = _series_stats(vals)
        out.append({"year": year, "months": stats["months"], "sharpe": stats["sharpe_annualized"]})
    return out


def robustness(
    conn: sqlite3.Connection,
    scored: list[Scored],
    partition: str = "explore",
    horizons: tuple[int, ...] = PEAD_HORIZONS,
    costs: tuple[int, ...] = config.COST_LEVELS_BPS,
    primary_horizon: int = 20,
) -> dict[str, object]:
    """EXPLORE-legal robustness battery: long-only variant, per-year decay, cost sensitivity.

    Computed on EXPLORE only so the single HOLDOUT shot stays reserved (PROTOCOL §4: subgroup
    and variant cuts are robustness, not new experiments).
    """
    data_by_h = {h: _drift_data(conn, scored, h, partition) for h in horizons}

    # Long/short vs long-only at each horizon (base cost).
    base_cost = config.BASE_CASE_COST_BPS
    book_comparison: list[dict[str, object]] = []
    for h in horizons:
        ls = _series_stats([v for _, v in _quintile_long_short_monthly(data_by_h[h], base_cost)])
        lo = _series_stats([v for _, v in _long_only_monthly(data_by_h[h], base_cost)])
        book_comparison.append({"horizon": h, "long_short": ls, "long_only": lo})

    # Cost sensitivity at the primary horizon, both books.
    base = data_by_h[primary_horizon]
    cost_sensitivity: list[dict[str, object]] = []
    for c in costs:
        ls = _series_stats([v for _, v in _quintile_long_short_monthly(base, c)])
        lo = _series_stats([v for _, v in _long_only_monthly(base, c)])
        cost_sensitivity.append(
            {
                "cost_bps": c,
                "long_short_sharpe": ls["sharpe_annualized"],
                "long_only_sharpe": lo["sharpe_annualized"],
            }
        )

    # Per-year decay at the primary horizon (long-only — the variant we care most about).
    by_year_long_only = _by_year(_long_only_monthly(base, config.BASE_CASE_COST_BPS))

    return {
        "partition": partition,
        "primary_horizon": primary_horizon,
        "book_comparison": book_comparison,
        "cost_sensitivity": cost_sensitivity,
        "by_year_long_only": by_year_long_only,
    }


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
) -> list[PeadResult]:
    scored = compute_surprises(conn, manifest)
    return evaluate(conn, scored, manifest, partitions=partitions)
