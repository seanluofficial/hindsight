"""Experiment 002 — event-type conditional returns.

Signal: the 8-K's SEC item codes (already parsed, always present). Pre-registered
buckets, fixed in experiments/002-event-type-conditional/HYPOTHESIS.md:

    high-impact : 1.03, 2.06, 4.02, 5.02
    earnings    : 2.02
    routine     : everything else

A filing with several codes is assigned to the highest-impact bucket present. The
primary endpoint is the 5-day, 10bps difference in mean market-excess return between
the high-impact and routine groups. No LLM, no anonymization, ~$0.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hindsight import config
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import (
    GroupStat,
    filing_excess_return,
    summarize,
    welch_t,
)
from hindsight.manifest import RunManifest

HIGH_IMPACT = frozenset({"1.03", "2.06", "4.02", "5.02"})
EARNINGS = frozenset({"2.02"})
GROUPS = ("high-impact", "earnings", "routine")


def bucket_for(item_codes: str | None) -> str:
    """Highest-impact bucket present among a filing's comma-separated item codes."""
    codes = {c.strip() for c in (item_codes or "").split(",") if c.strip()}
    if codes & HIGH_IMPACT:
        return "high-impact"
    if codes & EARNINGS:
        return "earnings"
    return "routine"


@dataclass(frozen=True)
class EventTypeResult:
    """One partition × horizon read of the event-type signal."""

    partition: str
    horizon: int
    groups: dict[str, GroupStat]
    high_minus_routine_bps: float
    t_statistic: float
    p_value: float

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "horizon": self.horizon,
            "groups": {g: s.as_dict() for g, s in self.groups.items()},
            "high_minus_routine_bps": self.high_minus_routine_bps,
            "t_statistic": self.t_statistic,
            "p_value": self.p_value,
        }


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
    horizons: tuple[int, ...] = config.HORIZONS_TRADING_DAYS,
) -> list[EventTypeResult]:
    """Compute the event-type contrast for each partition and horizon."""
    rows = list(
        conn.execute(
            "SELECT accession_no, ticker, accepted_at_utc, item_codes FROM filings "
            "ORDER BY accepted_at_utc, accession_no"
        )
    )
    prices = PriceLookup(conn)
    manifest.count("filings_considered", len(rows))

    results: list[EventTypeResult] = []
    for horizon in horizons:
        # partition -> bucket -> list of excess returns
        collected: dict[str, dict[str, list[float]]] = {
            p: {g: [] for g in GROUPS} for p in partitions
        }
        for row in rows:
            fr = filing_excess_return(
                row["accession_no"],
                row["ticker"],
                row["accepted_at_utc"],
                horizon,
                prices,
                manifest,
            )
            if fr is None or fr.partition not in collected:
                continue
            collected[fr.partition][bucket_for(row["item_codes"])].append(fr.excess_return)

        for partition in partitions:
            buckets = collected[partition]
            stats = {g: summarize(buckets[g]) for g in GROUPS}
            t, p = welch_t(buckets["high-impact"], buckets["routine"])
            diff_bps = (stats["high-impact"].mean - stats["routine"].mean) * 10_000.0
            results.append(
                EventTypeResult(
                    partition=partition,
                    horizon=horizon,
                    groups=stats,
                    high_minus_routine_bps=diff_bps,
                    t_statistic=t,
                    p_value=p,
                )
            )
            manifest.count(f"{partition}_h{horizon}_positions", sum(s.n for s in stats.values()))
    return results
