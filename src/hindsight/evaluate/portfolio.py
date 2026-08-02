"""Quintile long/short portfolios and cost application (PREREGISTRATION §9, §10).

Construction, fixed in advance and not tuned:

* Sort filings by predicted probability, signed by direction, **within each calendar
  month**. Sorting across the whole sample would let a later month's distribution decide
  an earlier month's quintile — lookahead through the back door.
* Long the top quintile, short the bottom. Equal weight, no leverage, no optimisation.
* Hold for the full horizon; overlapping positions are permitted and accounted for.

Every function returning a performance number takes `cost_bps` with **no default**
(invariant 6). A Sharpe ratio without a stated cost is not a result, it is an advert.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

from hindsight.evaluate.returns import Trade

TRADING_DAYS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# Below this many monthly observations, an annualized Sharpe is arithmetic, not evidence.
# The 500-filing pilot spans about two months, which is nowhere near enough — results are
# still computed, but flagged, so nobody quotes a headline number the sample cannot carry.
MIN_PERIODS_FOR_INFERENCE = 12


@dataclass(frozen=True)
class PortfolioResult:
    """Performance of one long/short book at one horizon and one cost level."""

    horizon: int
    cost_bps: float
    n_periods: int
    n_positions: int
    mean_return: float
    t_statistic: float
    sharpe_annualized: float
    max_drawdown: float
    hit_rate: float
    period_returns: list[float]

    @property
    def is_statistically_meaningful(self) -> bool:
        """Whether the series is long enough for the Sharpe and t-stat to mean anything."""
        return self.n_periods >= MIN_PERIODS_FOR_INFERENCE

    @property
    def caveat(self) -> str:
        if self.is_statistically_meaningful:
            return ""
        return f"only {self.n_periods} month(s) — not interpretable"

    def as_row(self) -> dict[str, float | int]:
        return {
            "horizon": self.horizon,
            "cost_bps": self.cost_bps,
            "months": self.n_periods,
            "positions": self.n_positions,
            "mean_return": self.mean_return,
            "t_stat": self.t_statistic,
            "sharpe": self.sharpe_annualized,
            "max_drawdown": self.max_drawdown,
            "hit_rate": self.hit_rate,
        }


def signed_score(trade: Trade) -> float:
    """Probability signed by direction: +0.8 for confident up, −0.8 for confident down.

    This is the sort key. It maps direction and confidence onto one axis so a single
    quintile split expresses both.
    """
    return trade.probability if trade.direction == "up" else -trade.probability


def month_key(trade: Trade) -> str:
    return trade.entry_date.strftime("%Y-%m")


def quintile_split(trades: list[Trade]) -> tuple[list[Trade], list[Trade]]:
    """(top quintile, bottom quintile) by signed score.

    Fewer than 5 trades cannot form quintiles; the caller skips those months rather than
    inventing a split, and the skip is counted.
    """
    if len(trades) < 5:
        return [], []
    ordered = sorted(trades, key=signed_score)
    size = len(ordered) // 5
    if size == 0:
        return [], []
    return ordered[-size:], ordered[:size]


def monthly_returns(trades: list[Trade], cost_bps: float) -> dict[str, float]:
    """Equal-weighted long/short return per month, after costs.

    Costs are charged on both legs, because both are round-trip trades.
    """
    by_month: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        by_month[month_key(trade)].append(trade)

    out: dict[str, float] = {}
    for month, group in sorted(by_month.items()):
        top, bottom = quintile_split(group)
        if not top or not bottom:
            continue
        # `signed_excess` already points each leg the way it was predicted, so the book
        # is the average of both legs' realised returns, each charged its own cost.
        long_leg = statistics.fmean(t.excess_return - cost_bps / 10_000.0 for t in top)
        short_leg = statistics.fmean(-t.excess_return - cost_bps / 10_000.0 for t in bottom)
        out[month] = (long_leg + short_leg) / 2.0
    return out


def max_drawdown(period_returns: list[float]) -> float:
    """Largest peak-to-trough decline of the compounded equity curve. Non-negative."""
    if not period_returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for r in period_returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return abs(worst)


def build(trades: list[Trade], horizon: int, cost_bps: float) -> PortfolioResult:
    """Evaluate the long/short book. `cost_bps` is required (invariant 6)."""
    at_horizon = [t for t in trades if t.horizon == horizon]
    months = monthly_returns(at_horizon, cost_bps)
    series = [months[m] for m in sorted(months)]

    n = len(series)
    mean = statistics.fmean(series) if series else 0.0
    stdev = statistics.stdev(series) if n > 1 else 0.0

    t_stat = mean / (stdev / math.sqrt(n)) if n > 1 and stdev > 0 else 0.0
    # The series is one observation per calendar month, because §9 rebalances monthly.
    # Annualise by the frequency of the *series*, not by the holding period: scaling by
    # sqrt(252/horizon) treats each monthly observation as a `horizon`-day period and
    # inflates the 1-day Sharpe by sqrt(252)/sqrt(12) ~ 4.6x.
    sharpe = (mean / stdev) * math.sqrt(MONTHS_PER_YEAR) if stdev > 0 else 0.0

    return PortfolioResult(
        horizon=horizon,
        cost_bps=cost_bps,
        n_periods=n,
        n_positions=len(at_horizon),
        mean_return=mean,
        t_statistic=t_stat,
        sharpe_annualized=sharpe,
        max_drawdown=max_drawdown(series),
        hit_rate=(sum(1 for r in series if r > 0) / n) if n else 0.0,
        period_returns=series,
    )


def directional_hit_rate(trades: list[Trade], horizon: int) -> float:
    """Share of individual calls whose signed excess return was positive.

    Distinct from `PortfolioResult.hit_rate`, which is the share of profitable *months*.
    """
    at_horizon = [t for t in trades if t.horizon == horizon]
    if not at_horizon:
        return 0.0
    return sum(1 for t in at_horizon if t.signed_excess() > 0) / len(at_horizon)
