"""Unattended price backfill against Tiingo's free tier.

    python scripts/backfill_prices.py

The free tier allows 50 requests/hour and 500 unique symbols/month, while one request
returns a symbol's entire history. The 2010-2024 universe needs ~790 symbols, so the whole
study's price data is free — it just takes two calendar months and a job that waits.

This runs `run_ingest.py prices` once an hour until either coverage is complete or the
monthly symbol cap is reached, then reports where it stopped. Everything it fetches is
committed as it goes, so stopping early loses nothing and re-running resumes.

Paying Tiingo $30/month would compress this to an afternoon. It buys speed, not data.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.ingest import prices  # noqa: E402

# Free tier: 50 requests/hour. Wait slightly over the hour so the window has rolled.
SLEEP_SECONDS = 3660


def log(message: str) -> None:
    print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M:%SZ}] {message}", flush=True)


def coverage() -> tuple[int, int]:
    """(covered, needed) tickers for the full study window."""
    with db.session() as conn:
        needed = {
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT ticker FROM universe
                 WHERE start_date <= ? AND (end_date IS NULL OR end_date > ?)
                """,
                (config.STUDY_END.isoformat(), config.STUDY_START.isoformat()),
            )
        } | {config.BENCHMARK_TICKER}
        covered = prices.covered_tickers(conn, config.STUDY_START, config.STUDY_END)
    return len(covered & needed), len(needed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-batches", type=int, default=24)
    args = parser.parse_args(argv)

    for batch in range(1, args.max_batches + 1):
        covered, needed = coverage()
        log(f"batch {batch}/{args.max_batches}: {covered}/{needed} tickers span the window")
        if covered >= needed:
            log("COMPLETE — every ticker spans the study window")
            return 0

        result = subprocess.run(
            [sys.executable, "scripts/run_ingest.py", "prices"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if any(
                k in line
                for k in ("tickers_fetched", "price_rows_written", "halted", "no_coverage")
            ):
                log("  " + line.strip())

        after, _ = coverage()
        gained = after - covered
        log(f"  gained {gained} tickers this batch")

        if gained == 0:
            # Either the monthly symbol cap is spent or every remaining ticker has no
            # data at the vendor. Neither clears within the hour, so stop rather than
            # spin — the monthly cap resets on the 1st.
            log("no progress this batch; monthly symbol cap is likely spent")
            log(f"STOPPED at {after}/{needed}. Re-run once the month rolls over.")
            return 0

        if batch < args.max_batches:
            log(f"  sleeping {SLEEP_SECONDS}s for the hourly window to roll")
            time.sleep(SLEEP_SECONDS)

    covered, needed = coverage()
    log(f"STOPPED after {args.max_batches} batches at {covered}/{needed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
