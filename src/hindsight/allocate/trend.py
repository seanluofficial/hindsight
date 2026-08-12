"""Diversified absolute-momentum (trend-following) allocation on liquid ETFs.

Rules, fixed in advance (no parameters tuned on the data):

* Basket of six risk sleeves: US equity (SPY), developed-ex-US equity (VEA), long Treasuries
  (TLT), intermediate Treasuries (IEF), gold (GLD), broad commodities (DBC). Cash = T-bills (BIL).
* Monthly, on the last trading day: for each sleeve, if the asset's trailing 12-month total
  return is positive (absolute momentum), hold it next month; otherwise hold cash for that sleeve.
* Equal weight across the six sleeves. Rebalance monthly. Turnover is charged `cost_bps` per leg.

Point-in-time and lookahead-free: the 12-month signal at each month-end uses only prices up to
that day, and returns accrue over the *following* month. Compared against buy-and-hold SPY and a
static monthly-rebalanced 60/40 (SPY/IEF).
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date

from hindsight import config, trading_calendar
from hindsight.evaluate.portfolio import max_drawdown
from hindsight.evaluate.returns import PriceLookup

RISK_ASSETS = ("SPY", "VEA", "TLT", "IEF", "GLD", "DBC")
CASH = "BIL"
LOOKBACK_DAYS = 252
MONTHS_PER_YEAR = 12


def _month_ends(days: list[date]) -> list[date]:
    return [days[i] for i in range(len(days) - 1) if days[i].month != days[i + 1].month]


def _ret(prices: PriceLookup, ticker: str, start: date, end: date) -> float | None:
    a, b = prices.bar(ticker, start), prices.bar(ticker, end)
    if a is None or b is None or a.adj_close <= 0:
        return None
    return b.adj_close / a.adj_close - 1.0


@dataclass(frozen=True)
class Stats:
    label: str
    partition: str
    n_months: int
    cagr: float
    vol_annual: float
    sharpe: float
    max_drawdown: float

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "partition": self.partition,
            "n_months": self.n_months,
            "cagr": self.cagr,
            "vol_annual": self.vol_annual,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
        }


def _stats(label: str, partition: str, monthly: list[float]) -> Stats:
    n = len(monthly)
    if n < 2:
        return Stats(label, partition, n, 0.0, 0.0, 0.0, 0.0)
    equity = 1.0
    for r in monthly:
        equity *= 1.0 + r
    cagr = equity ** (MONTHS_PER_YEAR / n) - 1.0
    vol = statistics.stdev(monthly) * math.sqrt(MONTHS_PER_YEAR)
    mean = statistics.fmean(monthly)
    sharpe = (mean / statistics.stdev(monthly)) * math.sqrt(MONTHS_PER_YEAR) if n > 1 else 0.0
    return Stats(label, partition, n, cagr, vol, sharpe, max_drawdown(monthly))


def run(
    conn: sqlite3.Connection,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> dict[str, object]:
    prices = PriceLookup(conn)
    days = trading_calendar.trading_days(config.EXPLORE_START, date(2026, 12, 31))
    idx = {d: i for i, d in enumerate(days)}
    month_ends = [m for m in _month_ends(days) if idx[m] - LOOKBACK_DAYS >= 0]

    # partition -> label -> list of monthly returns
    strat: dict[str, list[float]] = {}
    spy: dict[str, list[float]] = {}
    p6040: dict[str, list[float]] = {}
    prev_holdings: dict[str, str] = {}

    for f, f_next in zip(month_ends, month_ends[1:], strict=False):
        part = config.partition_of(f_next.isoformat())
        look = days[idx[f] - LOOKBACK_DAYS]

        holdings: dict[str, str] = {}
        sleeve_returns: list[float] = []
        for asset in RISK_ASSETS:
            mom = _ret(prices, asset, look, f)
            held = asset if (mom is not None and mom > 0) else CASH
            holdings[asset] = held
            r = _ret(prices, held, f, f_next)
            if r is not None:
                sleeve_returns.append(r)
        if len(sleeve_returns) < len(RISK_ASSETS):
            continue  # missing price this month; skip (counted implicitly by absence)

        gross = statistics.fmean(sleeve_returns)
        changed = sum(1 for a in RISK_ASSETS if prev_holdings.get(a) != holdings[a])
        turnover_cost = (changed / len(RISK_ASSETS)) * 2 * (cost_bps / 10_000.0)
        prev_holdings = holdings

        spy_r = _ret(prices, "SPY", f, f_next)
        spy_i = _ret(prices, "IEF", f, f_next)
        if spy_r is None or spy_i is None:
            continue
        strat.setdefault(part, []).append(gross - turnover_cost)
        spy.setdefault(part, []).append(spy_r)
        p6040.setdefault(part, []).append(0.6 * spy_r + 0.4 * spy_i)

    results: list[Stats] = []
    # Backtest = explore+holdout pooled (the rule is fixed, nothing is tuned); forward separate.
    for label, series_map in (
        ("Trend allocation", strat),
        ("Buy & hold SPY", spy),
        ("Static 60/40", p6040),
    ):
        backtest = [r for p in ("explore", "holdout") for r in series_map.get(p, [])]
        results.append(_stats(label, "backtest 2011-2024", backtest))
        results.append(_stats(label, "forward 2025+", series_map.get("forward", [])))
    return {"cost_bps": cost_bps, "results": [r.as_dict() for r in results]}
