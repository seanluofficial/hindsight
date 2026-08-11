"""Shared helpers for the no-LLM experiments (002, 004).

These experiments score *filings*, not model predictions, so they can't reuse
`returns.evaluate_prediction` directly. But they must obey the identical timing
and exclusion rules — next-open entry, market-excess vs. SPY, the $5 prior-close
screen, no silent drops. This module factors that logic out once so 002 and 004
cannot drift from the invariants.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime

from hindsight import config, trading_calendar
from hindsight.evaluate.returns import PriceLookup, window_return
from hindsight.manifest import RunManifest


@dataclass(frozen=True)
class FilingReturn:
    """A filing's market-excess return at one horizon, with entry timing applied."""

    accession_no: str
    ticker: str
    partition: str  # 'explore' | 'holdout' | 'other'
    entry_date: date
    horizon: int
    excess_return: float


def filing_excess_return(
    accession_no: str,
    ticker: str,
    accepted_at_utc: str,
    horizon: int,
    prices: PriceLookup,
    manifest: RunManifest | None = None,
) -> FilingReturn | None:
    """Market-excess return for one filing at one horizon, or None (with a counted reason).

    Mirrors `returns.evaluate_prediction`'s timing and exclusions exactly.
    """

    def drop(reason: str) -> None:
        if manifest:
            manifest.exclude(reason, f"{accession_no}:h{horizon}")

    accepted = datetime.fromisoformat(accepted_at_utc)
    entry = trading_calendar.entry_date_for(accepted)
    try:
        exit_day = trading_calendar.add_trading_days(entry, horizon)
    except ValueError:
        drop("exit_beyond_calendar")
        return None
    if not prices.has_ticker(ticker):
        drop("no_price_coverage_for_ticker")
        return None
    prior = prices.prior_close(ticker, entry)
    if prior is None:
        drop("no_prior_close")
        return None
    if prior < config.MIN_PRIOR_CLOSE_USD:
        drop("prior_close_below_5_usd")
        return None
    if prices.bar(ticker, entry) is None:
        drop("security_did_not_trade_on_entry")
        return None
    raw = window_return(prices, ticker, entry, exit_day)
    if raw is None:
        drop("missing_price_in_window")
        return None
    benchmark = window_return(prices, config.BENCHMARK_TICKER, entry, exit_day)
    if benchmark is None:
        drop("missing_benchmark_in_window")
        return None
    return FilingReturn(
        accession_no=accession_no,
        ticker=ticker,
        partition=config.partition_of(accepted_at_utc),
        entry_date=entry,
        horizon=horizon,
        excess_return=raw - benchmark,
    )


@dataclass(frozen=True)
class GroupStat:
    """Summary of one group of excess returns."""

    n: int
    mean: float
    stdev: float
    median: float

    def as_dict(self) -> dict[str, float | int]:
        return {"n": self.n, "mean": self.mean, "stdev": self.stdev, "median": self.median}


def summarize(values: list[float]) -> GroupStat:
    if not values:
        return GroupStat(0, 0.0, 0.0, 0.0)
    n = len(values)
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values) if n > 1 else 0.0
    return GroupStat(n=n, mean=mean, stdev=stdev, median=statistics.median(values))


def welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t-statistic and a two-sided normal-approx p-value for mean(a) - mean(b).

    Normal approximation is used for the p-value because both groups here run into the
    thousands; the t and normal tails are indistinguishable at that n. Reported, not the
    final word — the family-wise correction (PROTOCOL §3) is applied on top.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 1.0
    va = statistics.variance(a)
    vb = statistics.variance(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return 0.0, 1.0
    t = (statistics.fmean(a) - statistics.fmean(b)) / se
    # Two-sided p via the standard normal survival function.
    p = 2.0 * (1.0 - _normal_cdf(abs(t)))
    return t, p


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
