"""Experiment 006 — insider cluster-buying (Form 4).

Signal: a *cluster buy* is when >= 2 distinct insiders (officers/directors) of the same
company make open-market purchases within a 30-calendar-day window. The information-available
date is the latest Form 4 filing date in the cluster; entry is the next open after it (the
filing timestamp is unknown, so we conservatively assume after-close -> next open, no
lookahead). We test whether these events precede positive market-excess returns.

Input is data/insider_purchases.csv (see scripts/ingest_insider.py), already filtered to
open-market purchases by officers/directors of point-in-time S&P 500 members.
"""

from __future__ import annotations

import csv
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from hindsight import config
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import filing_excess_return
from hindsight.manifest import RunManifest

INSIDER_CSV = config.DATA_DIR / "insider_purchases.csv"
INSIDER_HORIZONS: tuple[int, ...] = (5, 20, 60)
CLUSTER_WINDOW_DAYS = 30
MIN_CLUSTER_INSIDERS = 2
# After firing a cluster event for an issuer, wait this long before another can fire, so one
# burst of buying is one event rather than many overlapping ones.
COOLDOWN_DAYS = 30
# Entry timestamp: 23:00 UTC is after the US close year-round, so entry is the next open.
_ENTRY_SUFFIX = "T23:00:00+00:00"


@dataclass(frozen=True)
class Purchase:
    ticker: str
    filing_date: date
    owner_cik: str
    value: float


@dataclass(frozen=True)
class Event:
    ticker: str
    event_date: date
    partition: str
    n_insiders: int
    total_value: float


def load_purchases(csv_path: Path | None = None) -> list[Purchase]:
    out: list[Purchase] = []
    with (csv_path or INSIDER_CSV).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fd = row["filing_date"].strip()
            if not fd:
                continue
            out.append(
                Purchase(
                    ticker=row["ticker"].strip().upper(),
                    filing_date=date.fromisoformat(fd),
                    owner_cik=row["owner_cik"].strip(),
                    value=float(row["value"] or 0),
                )
            )
    return out


def build_events(
    purchases: list[Purchase], min_insiders: int = MIN_CLUSTER_INSIDERS
) -> list[Event]:
    """Collapse bursts of insider buying into distinct cluster-buy events per issuer."""
    by_ticker: dict[str, list[Purchase]] = defaultdict(list)
    for p in purchases:
        by_ticker[p.ticker].append(p)

    events: list[Event] = []
    window = timedelta(days=CLUSTER_WINDOW_DAYS)
    cooldown = timedelta(days=COOLDOWN_DAYS)
    for ticker, plist in by_ticker.items():
        plist.sort(key=lambda p: p.filing_date)
        last_event: date | None = None
        for i, anchor in enumerate(plist):
            # Purchases within the trailing window ending at this filing date.
            in_window = [
                p for p in plist[: i + 1] if anchor.filing_date - p.filing_date <= window
            ]
            insiders = {p.owner_cik for p in in_window}
            if len(insiders) < min_insiders:
                continue
            if last_event is not None and anchor.filing_date - last_event < cooldown:
                continue
            last_event = anchor.filing_date
            events.append(
                Event(
                    ticker=ticker,
                    event_date=anchor.filing_date,
                    partition=config.partition_of(anchor.filing_date.isoformat()),
                    n_insiders=len(insiders),
                    total_value=sum(p.value for p in in_window),
                )
            )
    return events


@dataclass(frozen=True)
class EventStudyResult:
    partition: str
    horizon: int
    n_events: int
    mean_excess_bps: float
    median_excess_bps: float
    t_statistic: float
    hit_rate: float

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "horizon": self.horizon,
            "n_events": self.n_events,
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


def event_study(
    events: list[Event],
    prices: PriceLookup,
    manifest: RunManifest,
    partitions: tuple[str, ...],
    horizons: tuple[int, ...] = INSIDER_HORIZONS,
) -> list[EventStudyResult]:
    results: list[EventStudyResult] = []
    for horizon in horizons:
        by_part: dict[str, list[float]] = {p: [] for p in partitions}
        for ev in events:
            if ev.partition not in by_part:
                continue
            fr = filing_excess_return(
                f"insider:{ev.ticker}:{ev.event_date}",
                ev.ticker,
                ev.event_date.isoformat() + _ENTRY_SUFFIX,
                horizon,
                prices,
                manifest,
            )
            if fr is None:
                continue
            by_part[ev.partition].append(fr.excess_return)
        for partition in partitions:
            vals = by_part[partition]
            if not vals:
                results.append(EventStudyResult(partition, horizon, 0, 0.0, 0.0, 0.0, 0.0))
                continue
            results.append(
                EventStudyResult(
                    partition=partition,
                    horizon=horizon,
                    n_events=len(vals),
                    mean_excess_bps=statistics.fmean(vals) * 1e4,
                    median_excess_bps=statistics.median(vals) * 1e4,
                    t_statistic=_one_sample_t(vals),
                    hit_rate=sum(1 for v in vals if v > 0) / len(vals),
                )
            )
    return results


def long_only_sharpe(
    events: list[Event],
    prices: PriceLookup,
    partition: str,
    horizon: int = 20,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> dict[str, float]:
    """Monthly equal-weight long-only book of cluster-buy names — the materiality check."""
    by_month: dict[str, list[float]] = defaultdict(list)
    for ev in events:
        if ev.partition != partition:
            continue
        fr = filing_excess_return(
            f"insider:{ev.ticker}:{ev.event_date}",
            ev.ticker,
            ev.event_date.isoformat() + _ENTRY_SUFFIX,
            horizon,
            prices,
            manifest=None,
        )
        if fr is None:
            continue
        by_month[fr.entry_date.strftime("%Y-%m")].append(fr.excess_return - cost_bps / 10_000.0)

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


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
    csv_path: Path | None = None,
) -> dict[str, object]:
    purchases = load_purchases(csv_path)
    manifest.count("purchases_loaded", len(purchases))
    events = build_events(purchases)
    manifest.count("cluster_events", len(events))
    single = build_events(purchases, min_insiders=1)  # baseline: any insider buy
    manifest.count("any_buy_events", len(single))

    prices = PriceLookup(conn)
    cluster = event_study(events, prices, manifest, partitions)
    baseline = event_study(single, prices, manifest, partitions, horizons=(20,))

    materiality = {p: long_only_sharpe(events, prices, p) for p in partitions}
    return {
        "cluster": [r.as_dict() for r in cluster],
        "baseline_any_buy": [r.as_dict() for r in baseline],
        "materiality_long_only": materiality,
        "n_cluster_events": len(events),
    }
