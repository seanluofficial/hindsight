"""Experiment 010 — cross-sectional (12-1) momentum, whole-market / small-cap.

At the end of each month, rank every stock by its return over the past ~12 months excluding
the most recent month (`adj_close[t-21] / adj_close[t-252] - 1`), buy the top quintile and
short the bottom, enter at the next open, hold ~20 trading days, market-excess vs. SPY, costs
mandatory. All signal prices are >= 21 trading days before formation, so it is point-in-time.

Reuses the whole-market prices ingested for 009 (survivorship-safe: delisted names are retained
by the vendor). No new data. The long-only leg is reported because small-cap shorts carry borrow
constraints the flat bps model ignores.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date

from hindsight import config, trading_calendar
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import filing_excess_return
from hindsight.manifest import RunManifest

LOOKBACK_DAYS = 252
SKIP_DAYS = 21
HOLD_DAYS = 20
_ENTRY_SUFFIX = "T23:00:00+00:00"


@dataclass(frozen=True)
class Ranked:
    ticker: str
    momentum: float
    excess_return: float


def _month_end_indices(days: list[date]) -> list[int]:
    """Indices of the last trading day of each month."""
    out = []
    for i in range(len(days) - 1):
        if days[i].month != days[i + 1].month:
            out.append(i)
    return out


def _tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM prices WHERE ticker != ?", (config.BENCHMARK_TICKER,)
    ).fetchall()
    return [r[0] for r in rows]


def _quintiles(ranked: list[Ranked]) -> tuple[list[Ranked], list[Ranked]]:
    if len(ranked) < 10:
        return [], []
    ordered = sorted(ranked, key=lambda r: r.momentum)
    size = len(ordered) // 5
    return ordered[-size:], ordered[:size]  # winners, losers


@dataclass(frozen=True)
class MomentumResult:
    partition: str
    cost_bps: float
    n_months: int
    ls_mean_monthly: float
    ls_sharpe: float
    long_only_sharpe: float
    ls_max_drawdown: float

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "cost_bps": self.cost_bps,
            "n_months": self.n_months,
            "ls_mean_monthly": self.ls_mean_monthly,
            "ls_sharpe": self.ls_sharpe,
            "long_only_sharpe": self.long_only_sharpe,
            "ls_max_drawdown": self.ls_max_drawdown,
        }


def _sharpe(series: list[float]) -> tuple[float, float, float]:
    n = len(series)
    if n < 2:
        return 0.0, 0.0, 0.0
    mean = statistics.fmean(series)
    sd = statistics.stdev(series)
    sharpe = (mean / sd) * math.sqrt(MONTHS_PER_YEAR) if sd > 0 else 0.0
    return mean, sharpe, max_drawdown(series)


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout", "forward"),
    cost_levels: tuple[float, ...] = (10.0, 25.0),
    hold_days: int = HOLD_DAYS,
) -> dict[str, object]:
    prices = PriceLookup(conn)
    tickers = _tickers(conn)
    manifest.count("tickers", len(tickers))
    days = trading_calendar.trading_days(config.EXPLORE_START, date(2026, 12, 31))
    formations = [
        i
        for i in _month_end_indices(days)
        if i - LOOKBACK_DAYS >= 0 and i + hold_days + 2 < len(days)
    ]

    # partition -> cost -> list of monthly L/S returns; and long-only.
    ls: dict[str, dict[float, list[float]]] = {p: {c: [] for c in cost_levels} for p in partitions}
    lo: dict[str, dict[float, list[float]]] = {p: {c: [] for c in cost_levels} for p in partitions}

    for i in formations:
        f = days[i]
        partition = config.partition_of(f.isoformat())
        if partition not in ls:
            continue
        skip_bar_day = days[i - SKIP_DAYS]
        look_bar_day = days[i - LOOKBACK_DAYS]
        ranked: list[Ranked] = []
        for t in tickers:
            p1 = prices.bar(t, skip_bar_day)
            p0 = prices.bar(t, look_bar_day)
            if p0 is None or p1 is None or p0.adj_close <= 0:
                continue
            fr = filing_excess_return(
                f"mom:{t}:{f}", t, f.isoformat() + _ENTRY_SUFFIX, hold_days, prices
            )
            if fr is None:
                continue
            ranked.append(Ranked(t, p1.adj_close / p0.adj_close - 1.0, fr.excess_return))

        winners, losers = _quintiles(ranked)
        if not winners or not losers:
            continue
        manifest.count(f"{partition}_formations")
        for c in cost_levels:
            long_leg = statistics.fmean(r.excess_return - c / 10_000.0 for r in winners)
            short_leg = statistics.fmean(-r.excess_return - c / 10_000.0 for r in losers)
            ls[partition][c].append((long_leg + short_leg) / 2.0)
            lo[partition][c].append(long_leg)

    results: list[MomentumResult] = []
    for p in partitions:
        for c in cost_levels:
            mean, sharpe, mdd = _sharpe(ls[p][c])
            _, lo_sharpe, _ = _sharpe(lo[p][c])
            results.append(
                MomentumResult(
                    partition=p,
                    cost_bps=c,
                    n_months=len(ls[p][c]),
                    ls_mean_monthly=mean,
                    ls_sharpe=sharpe,
                    long_only_sharpe=lo_sharpe,
                    ls_max_drawdown=mdd,
                )
            )
    return {"results": [r.as_dict() for r in results], "hold_days": HOLD_DAYS}
