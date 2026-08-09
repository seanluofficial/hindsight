"""One command that advances the study as far as it can, then stops cleanly.

    python scripts/continue_study.py

Every stage underneath is resumable and commits as it goes, so this is safe to interrupt —
close the laptop, lose power, whatever. Re-running picks up exactly where it stopped and
never repeats paid work.

Stages, in dependency order:

1. **Prices** — Tiingo free tier, 50 symbols/hour, 500/month. Runs hourly until the
   monthly cap is spent.
2. **Filings** — EDGAR for any missing study year. Free, rate-limited, fully cached.
3. **Anonymize** — local, free, idempotent.
4. **Sample** — drawn once and frozen, only when filings span the study period.
5. **Score** — the only paid stage, and it is bounded by `--budget`.

Each stage reports what it did and whether it finished or hit a wall. Nothing here decides
anything about the study; it just sequences work whose rules were fixed elsewhere.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.ingest import prices as price_mod  # noqa: E402
from hindsight.score import anonymize as anon  # noqa: E402

SAMPLE_PATH = config.DATA_DIR / "study_sample.csv"


def log(message: str) -> None:
    print(f"[{datetime.now(UTC):%H:%M:%SZ}] {message}", flush=True)


def run(args: list[str], label: str) -> bool:
    """Run a stage, echoing only its interesting lines. True if it exited cleanly."""
    log(f"--- {label}")
    result = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True)
    keys = (
        "written",
        "scored",
        "fetched",
        "halted",
        "anonymized",
        "sampled",
        "unattempted",
        "leak rate",
        "cost",
        "population",
        "STOPPED",
        "COMPLETE",
    )
    for line in result.stdout.splitlines():
        if any(k in line for k in keys):
            log("    " + line.strip())
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        for line in tail:
            log("    ! " + line.strip())
    return result.returncode == 0


@dataclass(frozen=True)
class Progress:
    """A snapshot of how far the study has got, in the units that gate the next stage."""

    filings: int
    anonymized: int
    years_have: list[str]
    years_missing: list[str]
    prices_covered: int
    prices_needed: int

    @property
    def study_years(self) -> int:
        return len(self.years_have) + len(self.years_missing)

    @property
    def prices_complete(self) -> bool:
        return self.prices_covered >= self.prices_needed


def state() -> Progress:
    with db.session() as conn:
        years = {
            r[0] for r in conn.execute("SELECT DISTINCT substr(accepted_at_utc,1,4) FROM filings")
        }
        filings = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        anonymized = conn.execute(
            "SELECT COUNT(*) FROM filings WHERE anon_version = ?", (anon.ANON_VERSION,)
        ).fetchone()[0]
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
        covered = price_mod.covered_tickers(conn, config.STUDY_START, config.STUDY_END)
    wanted_years = {str(y) for y in range(config.STUDY_START.year, config.STUDY_END.year + 1)}
    return Progress(
        filings=filings,
        anonymized=anonymized,
        years_have=sorted(years),
        years_missing=sorted(wanted_years - years),
        prices_covered=len(covered & needed),
        prices_needed=len(needed),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=5.0, help="USD ceiling for scoring")
    parser.add_argument("--sample-size", type=int, default=5000)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-scoring", action="store_true")
    args = parser.parse_args(argv)

    before = state()
    log(
        f"start: {before.filings:,} filings, {before.anonymized:,} anonymized, "
        f"prices {before.prices_covered}/{before.prices_needed}"
    )

    # 1. Prices. Hourly batches until the monthly cap; safe to interrupt.
    if not args.skip_prices and not before.prices_complete:
        run(["scripts/backfill_prices.py"], "prices (free tier, hourly)")

    # 2. Filings for any missing study year.
    for year in before.years_missing:
        run(["scripts/run_ingest.py", "filings", "--year", year], f"filings {year}")

    # 3. Anonymize whatever is new. Local and free.
    run(["scripts/run_score.py", "anonymize"], "anonymize")

    # 4. Sample — only once the filings span the study period.
    after_ingest = state()
    if SAMPLE_PATH.exists():
        log("--- sample already frozen; leaving it alone")
    elif after_ingest.years_missing:
        log(f"--- sample deferred: {len(after_ingest.years_missing)} study years still missing")
    else:
        run(["scripts/draw_sample.py", "--size", str(args.sample_size)], "draw sample")

    # 5. Scoring — the only stage that spends money, and it is capped.
    if not args.skip_scoring:
        run(
            [
                "scripts/run_score.py",
                "llm",
                "--provider",
                args.provider,
                "--limit",
                str(args.sample_size),
                "--budget",
                str(args.budget),
            ],
            f"score (<= ${args.budget:.2f})",
        )

    end = state()
    log("")
    log("=" * 60)
    log(
        f"  filings      {end.filings:,}   ({len(end.years_have)} of {end.study_years} study years)"
    )
    log(f"  anonymized   {end.anonymized:,}")
    log(f"  prices       {end.prices_covered}/{end.prices_needed} tickers span 2010-2024")
    if end.years_missing:
        log(
            f"  still to ingest: {', '.join(end.years_missing[:8])}"
            + (" ..." if len(end.years_missing) > 8 else "")
        )
    log("  safe to stop. re-run this script to continue.")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
