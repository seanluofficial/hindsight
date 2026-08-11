"""Experiment 007 — "bury bad news" filing timing.

No new data, no LLM. The issuer chooses *when* to file. A filing is **buried** if its
acceptance timestamp lands in a low-attention window:

    weekend dump    -- Friday at/after 16:00 ET, or any time Saturday / Sunday
    pre-holiday dump-- at/after 16:00 ET on a trading day with a market holiday before
                       the next session (real NYSE calendar, not a weekday guess)

Everything else is the control group. We test whether buried 8-Ks drift *down* over the
following days relative to filings released in full view — the market under-reacting to news
that was deliberately timed to be missed.

Entry timing (PREREGISTRATION §4) is applied identically to both groups via the shared
harness, so the test isolates the attention channel, not the entry mechanic. The timestamp
exists at filing time, so there is no lookahead.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from hindsight import config, trading_calendar
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import filing_excess_return, welch_t
from hindsight.manifest import RunManifest

TIMING_HORIZONS: tuple[int, ...] = (5, 20, 60)
_FRIDAY = 4  # date.weekday(): Mon=0 .. Sun=6
_SATURDAY = 5
_SUNDAY = 6


def _holiday_before_next_session(day: date) -> bool:
    """True if a weekday market holiday falls between `day` and the next trading session.

    `day` must itself be a trading day. Distinguishes a real pre-holiday evening from an
    ordinary Friday: a weekday that is not a session, sitting before the next session, is a
    market holiday (e.g. the Wednesday before Thanksgiving, or a Friday before a Monday close).
    """
    nxt = trading_calendar.next_trading_day(day)
    cur = day + timedelta(days=1)
    while cur < nxt:
        if cur.weekday() < _SATURDAY:  # a Mon-Fri gap day that is not a session -> holiday
            return True
        cur += timedelta(days=1)
    return False


def classify(accepted_at_utc: str) -> str:
    """Bucket a filing by its acceptance timing: 'weekend', 'preholiday', or 'control'.

    'weekend' and 'preholiday' are the two buried categories; anything else is 'control'.
    """
    eastern = datetime.fromisoformat(accepted_at_utc).astimezone(config.MARKET_TZ)
    d = eastern.date()
    after_close = eastern.time() >= config.ENTRY_CUTOFF_ET
    weekday = d.weekday()

    if weekday in (_SATURDAY, _SUNDAY):
        return "weekend"
    if weekday == _FRIDAY and after_close and trading_calendar.is_trading_day(d):
        return "weekend"
    if after_close and trading_calendar.is_trading_day(d) and _holiday_before_next_session(d):
        return "preholiday"
    return "control"


def is_buried(bucket: str) -> bool:
    return bucket in ("weekend", "preholiday")


def _after_hours(accepted_at_utc: str) -> bool:
    """True if accepted at/after the 16:00 ET close on a trading day (Mon-Thu incl.)."""
    eastern = datetime.fromisoformat(accepted_at_utc).astimezone(config.MARKET_TZ)
    return eastern.time() >= config.ENTRY_CUTOFF_ET and trading_calendar.is_trading_day(
        eastern.date()
    )


@dataclass(frozen=True)
class Filing:
    accession_no: str
    ticker: str
    accepted_at_utc: str
    partition: str
    bucket: str


def load_filings(conn: sqlite3.Connection) -> list[Filing]:
    rows = conn.execute(
        "SELECT accession_no, ticker, accepted_at_utc FROM filings "
        "ORDER BY accepted_at_utc, accession_no"
    )
    out: list[Filing] = []
    for row in rows:
        accepted = row["accepted_at_utc"]
        out.append(
            Filing(
                accession_no=row["accession_no"],
                ticker=row["ticker"],
                accepted_at_utc=accepted,
                partition=config.partition_of(accepted),
                bucket=classify(accepted),
            )
        )
    return out


@dataclass(frozen=True)
class GroupResult:
    partition: str
    group: str
    horizon: int
    n: int
    mean_excess_bps: float
    median_excess_bps: float
    t_statistic: float
    hit_rate: float

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "group": self.group,
            "horizon": self.horizon,
            "n": self.n,
            "mean_excess_bps": self.mean_excess_bps,
            "median_excess_bps": self.median_excess_bps,
            "t_statistic": self.t_statistic,
            "hit_rate": self.hit_rate,
        }


def _one_sample_t(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    sd = statistics.stdev(values)
    if sd == 0:
        return 0.0
    return statistics.fmean(values) / (sd / math.sqrt(n))


def _summarize(partition: str, group: str, horizon: int, vals: list[float]) -> GroupResult:
    if not vals:
        return GroupResult(partition, group, horizon, 0, 0.0, 0.0, 0.0, 0.0)
    return GroupResult(
        partition=partition,
        group=group,
        horizon=horizon,
        n=len(vals),
        mean_excess_bps=statistics.fmean(vals) * 1e4,
        median_excess_bps=statistics.median(vals) * 1e4,
        t_statistic=_one_sample_t(vals),
        hit_rate=sum(1 for v in vals if v > 0) / len(vals),
    )


def _returns_by_group(
    filings: list[Filing],
    prices: PriceLookup,
    manifest: RunManifest | None,
    horizon: int,
    partition: str,
) -> dict[str, list[float]]:
    """Market-excess returns at one horizon, split into buried vs control, for one partition."""
    out: dict[str, list[float]] = {"buried": [], "control": []}
    for fil in filings:
        if fil.partition != partition:
            continue
        fr = filing_excess_return(
            fil.accession_no, fil.ticker, fil.accepted_at_utc, horizon, prices, manifest
        )
        if fr is None:
            continue
        out["buried" if is_buried(fil.bucket) else "control"].append(fr.excess_return)
    return out


def event_study(
    filings: list[Filing],
    prices: PriceLookup,
    manifest: RunManifest,
    partitions: tuple[str, ...],
    horizons: tuple[int, ...] = TIMING_HORIZONS,
) -> tuple[list[GroupResult], list[dict[str, object]]]:
    """Per-group summaries plus the buried-minus-control difference test at each horizon."""
    results: list[GroupResult] = []
    diffs: list[dict[str, object]] = []
    for partition in partitions:
        for horizon in horizons:
            # manifest exclusions are counted once, on the primary horizon, to avoid
            # multiplying the same filing's exclusion across three horizons.
            m = manifest if horizon == 20 else None
            groups = _returns_by_group(filings, prices, m, horizon, partition)
            buried, control = groups["buried"], groups["control"]
            results.append(_summarize(partition, "buried", horizon, buried))
            results.append(_summarize(partition, "control", horizon, control))
            t, p = welch_t(buried, control)
            diffs.append(
                {
                    "partition": partition,
                    "horizon": horizon,
                    "n_buried": len(buried),
                    "n_control": len(control),
                    "diff_bps": (
                        (statistics.fmean(buried) - statistics.fmean(control)) * 1e4
                        if buried and control
                        else 0.0
                    ),
                    "welch_t": t,
                    "p_two_sided": p,
                }
            )
    return results, diffs


def short_buried_sharpe(
    filings: list[Filing],
    prices: PriceLookup,
    partition: str,
    horizon: int = 20,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> dict[str, float]:
    """Monthly equal-weight SHORT book of buried names — the materiality check.

    The tradeable side of a "buried filings drift down" signal is a short, so the monthly
    return is -(market-excess) minus cost. Unlike 006's long-only book this carries borrow
    cost; the 0.30 floor is applied to the after-cost series.
    """
    by_month: dict[str, list[float]] = defaultdict(list)
    for fil in filings:
        if fil.partition != partition or not is_buried(fil.bucket):
            continue
        fr = filing_excess_return(
            fil.accession_no, fil.ticker, fil.accepted_at_utc, horizon, prices, manifest=None
        )
        if fr is None:
            continue
        # Short: profit is the negative of the name's excess return, then pay cost.
        by_month[fr.entry_date.strftime("%Y-%m")].append(-fr.excess_return - cost_bps / 10_000.0)

    series = [statistics.fmean(v) for _, v in sorted(by_month.items()) if v]
    n = len(series)
    if n < 2:
        return {"n_months": n, "mean_monthly": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
    mean = statistics.fmean(series)
    sd = statistics.stdev(series)
    sharpe = (mean / sd) * math.sqrt(MONTHS_PER_YEAR) if sd > 0 else 0.0
    return {
        "n_months": n,
        "mean_monthly": mean,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(series),
    }


def by_bucket(
    filings: list[Filing], prices: PriceLookup, partition: str, horizon: int = 20
) -> list[dict[str, object]]:
    """20-day mean market-excess for each timing bucket (weekend / preholiday / control),
    plus an after-hours-matched control — descriptive robustness (PROTOCOL §4)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for fil in filings:
        if fil.partition != partition:
            continue
        fr = filing_excess_return(
            fil.accession_no, fil.ticker, fil.accepted_at_utc, horizon, prices, manifest=None
        )
        if fr is None:
            continue
        buckets[fil.bucket].append(fr.excess_return)
        # An after-hours Mon-Thu control isolates attention from the skipped-open gap.
        if fil.bucket == "control" and _after_hours(fil.accepted_at_utc):
            buckets["control_after_hours"].append(fr.excess_return)

    out: list[dict[str, object]] = []
    for name, vals in sorted(buckets.items()):
        if not vals:
            continue
        out.append(
            {
                "bucket": name,
                "n": len(vals),
                "mean_excess_bps": statistics.fmean(vals) * 1e4,
                "median_excess_bps": statistics.median(vals) * 1e4,
                "t_statistic": _one_sample_t(vals),
            }
        )
    return out


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
) -> dict[str, object]:
    filings = load_filings(conn)
    manifest.count("filings_loaded", len(filings))
    manifest.count("buried", sum(1 for f in filings if is_buried(f.bucket)))
    manifest.count("weekend", sum(1 for f in filings if f.bucket == "weekend"))
    manifest.count("preholiday", sum(1 for f in filings if f.bucket == "preholiday"))

    prices = PriceLookup(conn)
    groups, diffs = event_study(filings, prices, manifest, partitions)
    materiality = {p: short_buried_sharpe(filings, prices, p) for p in partitions}
    buckets = {p: by_bucket(filings, prices, p) for p in partitions}

    return {
        "groups": [g.as_dict() for g in groups],
        "diff_buried_vs_control": diffs,
        "materiality_short_buried": materiality,
        "by_bucket": buckets,
        "n_buried": sum(1 for f in filings if is_buried(f.bucket)),
        "n_filings": len(filings),
    }
