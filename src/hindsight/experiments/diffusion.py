"""Experiment 008 — peer / lead-lag information diffusion.

Hypothesis: when a firm files an 8-K, the news is partly about its industry, and that
information diffuses *slowly* to economically related peers (Moskowitz & Grinblatt 1999
industry momentum; Hou 2007 industry lead-lag; Cohen & Frazzini 2008 economic links). So a
peer basket should drift in the *same direction* as the filer's own reaction over the
following days.

Construction (no lookahead):
  * filer reaction = the filer's market-excess return from the prior close to its entry-day
    close (E), the reaction to the filing, fully observable at E's close;
  * peers = other point-in-time universe members sharing the filer's 3-digit SIC, entered the
    NEXT open after E (so the filer's reaction is already public), held H days;
  * signal = sign(filer_reaction) x peer market-excess return. If news diffuses, this is
    positive: peers follow the filer.

Caveat, stated up front: peers overlap heavily (every filing in an industry trades the same
names), so event-level t-stats are anticonservative. The materiality read is a *monthly*
long/short peer book, which collapses the within-month overlap into one observation.
"""

from __future__ import annotations

import csv
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from hindsight import config, trading_calendar
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup, window_return
from hindsight.manifest import RunManifest

INDUSTRY_CSV = config.DATA_DIR / "industry.csv"
DIFFUSION_HORIZONS: tuple[int, ...] = (5, 20, 60)
SIC_PREFIX = 3  # 3-digit SIC industry groups (primary); 2-digit is a robustness widening.


@dataclass(frozen=True)
class Interval:
    start: date
    end: date


class PeerMap:
    """Industry peers by SIC prefix, with point-in-time universe membership."""

    def __init__(self, conn: sqlite3.Connection, sic_prefix: int = SIC_PREFIX) -> None:
        self.sic_of: dict[str, str] = {}
        with INDUSTRY_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sic = row["sic"].strip()
                if sic:
                    self.sic_of[row["ticker"].strip().upper()] = sic[:sic_prefix]

        self.group: dict[str, list[str]] = defaultdict(list)
        for ticker, sic in self.sic_of.items():
            self.group[sic].append(ticker)

        # Point-in-time membership intervals per ticker (no survivorship).
        self.intervals: dict[str, list[Interval]] = defaultdict(list)
        for row in conn.execute("SELECT ticker, start_date, end_date FROM universe"):
            if not row["ticker"]:
                continue
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"]) if row["end_date"] else date(9999, 12, 31)
            self.intervals[row["ticker"].upper()].append(Interval(start, end))

    def _is_member(self, ticker: str, on: date) -> bool:
        return any(iv.start <= on <= iv.end for iv in self.intervals.get(ticker, ()))

    def peers(self, filer: str, on: date) -> list[str]:
        """Same-SIC universe members (excluding the filer) that were members on `on`."""
        sic = self.sic_of.get(filer.upper())
        if sic is None:
            return []
        return [
            p for p in self.group[sic] if p != filer.upper() and self._is_member(p, on)
        ]


@dataclass(frozen=True)
class DiffusionResult:
    partition: str
    horizon: int
    n_pairs: int
    n_events: int
    mean_signed_bps: float
    t_statistic: float
    hit_rate: float

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "horizon": self.horizon,
            "n_pairs": self.n_pairs,
            "n_events": self.n_events,
            "mean_signed_bps": self.mean_signed_bps,
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


class _ExcessCache:
    """Memoized market-excess window return, keyed by (ticker, entry, exit)."""

    def __init__(self, prices: PriceLookup) -> None:
        self.prices = prices
        self._memo: dict[tuple[str, date, date], float | None] = {}

    def excess(self, ticker: str, entry: date, exit_day: date) -> float | None:
        key = (ticker, entry, exit_day)
        if key in self._memo:
            return self._memo[key]
        stock = window_return(self.prices, ticker, entry, exit_day)
        bench = window_return(self.prices, config.BENCHMARK_TICKER, entry, exit_day)
        val = None if (stock is None or bench is None) else stock - bench
        self._memo[key] = val
        return val


@dataclass(frozen=True)
class _Event:
    filer: str
    entry: date  # filer entry day E
    peer_entry: date  # next open after E
    partition: str
    reaction_sign: float  # +1 / -1 from the filer's own reaction at E


def _filer_reaction(prices: PriceLookup, ticker: str, entry: date) -> float | None:
    """Filer market-excess return, prior close -> entry-day close (the filing reaction)."""
    prior = prices.prior_close(ticker, entry)
    bar = prices.bar(ticker, entry)
    b_prior = prices.prior_close(config.BENCHMARK_TICKER, entry)
    b_bar = prices.bar(config.BENCHMARK_TICKER, entry)
    if not (bar and b_bar) or prior is None or b_prior is None or prior <= 0 or b_prior <= 0:
        return None
    return (bar.adj_close / prior - 1.0) - (b_bar.adj_close / b_prior - 1.0)


def _build_events(
    conn: sqlite3.Connection,
    prices: PriceLookup,
    manifest: RunManifest,
    partitions: tuple[str, ...],
) -> list[_Event]:
    rows = conn.execute(
        "SELECT ticker, accepted_at_utc FROM filings ORDER BY accepted_at_utc, accession_no"
    )
    events: list[_Event] = []
    for row in rows:
        accepted = row["accepted_at_utc"]
        partition = config.partition_of(accepted)
        if partition not in partitions:
            continue
        ticker = (row["ticker"] or "").upper()
        if not prices.has_ticker(ticker):
            manifest.exclude("filer_no_price_coverage")
            continue
        entry = trading_calendar.entry_date_for(datetime.fromisoformat(accepted))
        prior = prices.prior_close(ticker, entry)
        if prior is None or prior < config.MIN_PRIOR_CLOSE_USD:
            manifest.exclude("filer_no_prior_close_or_penny")
            continue
        reaction = _filer_reaction(prices, ticker, entry)
        if reaction is None or reaction == 0.0:
            manifest.exclude("filer_reaction_unavailable_or_flat")
            continue
        try:
            peer_entry = trading_calendar.next_trading_day(entry)
        except ValueError:
            manifest.exclude("calendar_edge")
            continue
        events.append(
            _Event(
                filer=ticker,
                entry=entry,
                peer_entry=peer_entry,
                partition=partition,
                reaction_sign=math.copysign(1.0, reaction),
            )
        )
    return events


def event_study(
    events: list[_Event],
    peers: PeerMap,
    cache: _ExcessCache,
    partitions: tuple[str, ...],
    horizons: tuple[int, ...] = DIFFUSION_HORIZONS,
) -> list[DiffusionResult]:
    results: list[DiffusionResult] = []
    for horizon in horizons:
        signed: dict[str, list[float]] = {p: [] for p in partitions}
        events_used: dict[str, int] = {p: 0 for p in partitions}
        for ev in events:
            if ev.partition not in signed:
                continue
            try:
                exit_day = trading_calendar.add_trading_days(ev.peer_entry, horizon)
            except ValueError:
                continue
            peer_list = peers.peers(ev.filer, ev.entry)
            used = False
            for p in peer_list:
                px = cache.excess(p, ev.peer_entry, exit_day)
                if px is None:
                    continue
                signed[ev.partition].append(ev.reaction_sign * px)
                used = True
            if used:
                events_used[ev.partition] += 1
        for partition in partitions:
            vals = signed[partition]
            if not vals:
                results.append(DiffusionResult(partition, horizon, 0, 0, 0.0, 0.0, 0.0))
                continue
            results.append(
                DiffusionResult(
                    partition=partition,
                    horizon=horizon,
                    n_pairs=len(vals),
                    n_events=events_used[partition],
                    mean_signed_bps=statistics.fmean(vals) * 1e4,
                    t_statistic=_one_sample_t(vals),
                    hit_rate=sum(1 for v in vals if v > 0) / len(vals),
                )
            )
    return results


def monthly_longshort_sharpe(
    events: list[_Event],
    peers: PeerMap,
    cache: _ExcessCache,
    partition: str,
    horizon: int = 20,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> dict[str, float]:
    """Monthly long/short peer book — the materiality check.

    Each month, average the signed peer returns (long peers of up-filers, short peers of
    down-filers), net of cost on each position. Collapsing to a monthly series absorbs the
    heavy within-month overlap between events that share the same peers.
    """
    by_month: dict[str, list[float]] = defaultdict(list)
    for ev in events:
        if ev.partition != partition:
            continue
        try:
            exit_day = trading_calendar.add_trading_days(ev.peer_entry, horizon)
        except ValueError:
            continue
        for p in peers.peers(ev.filer, ev.entry):
            px = cache.excess(p, ev.peer_entry, exit_day)
            if px is None:
                continue
            by_month[ev.peer_entry.strftime("%Y-%m")].append(
                ev.reaction_sign * px - cost_bps / 10_000.0
            )

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
) -> dict[str, object]:
    prices = PriceLookup(conn)
    peers = PeerMap(conn)
    cache = _ExcessCache(prices)
    manifest.count("sic_groups", len(peers.group))

    events = _build_events(conn, prices, manifest, partitions)
    manifest.count("events_built", len(events))

    results = event_study(events, peers, cache, partitions)
    materiality = {p: monthly_longshort_sharpe(events, peers, cache, p) for p in partitions}
    return {
        "diffusion": [r.as_dict() for r in results],
        "materiality_long_short": materiality,
        "n_events": len(events),
        "sic_prefix": SIC_PREFIX,
    }
