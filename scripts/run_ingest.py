"""Stage 1 entrypoint: universe, filings, prices.

    python scripts/run_ingest.py universe --rebuild
    python scripts/run_ingest.py filings --year 2018 --quarter 1
    python scripts/run_ingest.py prices  --year 2018
    python scripts/run_ingest.py status

Every subcommand writes a manifest to data/manifests/ recording the git SHA, the
parameters, row counts, and every exclusion with its reason.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hindsight import config, db, trading_calendar  # noqa: E402
from hindsight.ingest import edgar, prices, universe  # noqa: E402
from hindsight.ingest.http import CachedFetcher  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402


def setup_logging(verbose: bool) -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "ingest.log", encoding="utf-8"),
        ],
    )


# --------------------------------------------------------------------------
def cmd_universe(args: argparse.Namespace) -> int:
    with RunManifest("universe", rebuild=args.rebuild) as manifest, db.session() as conn:
        if args.rebuild or not config.UNIVERSE_CSV_PATH.exists():
            print("Reconstructing point-in-time membership from Wikipedia...")
            tables = universe.fetch_wikipedia_tables()
            memberships = universe.reconstruct_membership(tables, manifest)
            memberships = universe.resolve_ciks(memberships, manifest=manifest)
            path = universe.write_frozen_csv(memberships)
            manifest.count("membership_intervals", len(memberships))
            print(f"  froze {len(memberships):,} membership intervals -> {path}")
        else:
            memberships = universe.load_frozen_csv()
            print(f"  loaded {len(memberships):,} intervals from frozen CSV")

        universe.load_to_db(conn, memberships, manifest)

        health = universe.membership_health(memberships)
        print("\n  members on June 30 of each study year (a real index sits near 500):")
        for year, n in health.items():
            flag = "" if 480 <= n <= 520 else "   <-- off"
            print(f"    {year}: {n:3d}{flag}")
        manifest.params["membership_health"] = health
    return 0


def cmd_filings(args: argparse.Namespace) -> int:
    quarters = [args.quarter] if args.quarter else [1, 2, 3, 4]
    with (
        RunManifest("filings", year=args.year, quarters=quarters, limit=args.limit) as manifest,
        db.session() as conn,
    ):
        memberships = universe.load_frozen_csv()
        universe.load_to_db(conn, memberships)
        matcher = edgar.UniverseMatcher(memberships)
        fetcher = CachedFetcher()

        total = 0
        for q in quarters:
            print(f"\n  {args.year} Q{q}: crawling full index...")
            total += edgar.ingest_quarter(
                conn, args.year, q, matcher, fetcher, manifest, limit=args.limit
            )
            print(f"    running total: {total:,} filings")

        manifest.count("cache_hits", fetcher.hits)
        manifest.count("cache_misses", fetcher.misses)
    return 0


def cmd_prices(args: argparse.Namespace) -> int:
    start = date(args.year, 1, 1) if args.year else config.STUDY_START
    end = date(args.year, 12, 31) if args.year else config.STUDY_END
    # Pad so horizons that run past the window still have exit prices available.
    padded_end = min(date(end.year + 1, 3, 31), date.today())

    with (
        RunManifest("prices", start=start.isoformat(), end=padded_end.isoformat()) as manifest,
        db.session() as conn,
    ):
        if args.tickers_file:
            path = Path(args.tickers_file)
            tickers = [
                line.strip().upper()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            print(f"  loaded {len(tickers):,} tickers from {path}")
        elif args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            # Every ticker that filed something we ingested, plus everyone who was a
            # member during the window — including those who left partway through.
            rows = conn.execute(
                """
                SELECT DISTINCT ticker FROM universe
                 WHERE start_date <= ? AND (end_date IS NULL OR end_date > ?)
                """,
                (end.isoformat(), start.isoformat()),
            ).fetchall()
            tickers = [r[0] for r in rows]

        print(f"  fetching {len(tickers):,} tickers + benchmark, {start} .. {padded_end}")
        prices.ingest_prices(conn, tickers, start, padded_end, manifest)

        report = prices.coverage_report(conn, start, end)
        manifest.params["coverage"] = report
        print("\n  coverage:")
        for k, v in report.items():
            if k != "thinnest":
                print(f"    {k}: {v}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with db.session() as conn:
        counts = db.table_counts(conn)
        print("Table counts:")
        for table, n in counts.items():
            print(f"  {table:<12} {n:>10,}")

        row = conn.execute(
            "SELECT MIN(accepted_at_utc), MAX(accepted_at_utc) FROM filings"
        ).fetchone()
        if row and row[0]:
            print(f"\nFilings span: {row[0]}  ..  {row[1]}")

        by_year = conn.execute(
            """
            SELECT substr(accepted_at_utc, 1, 4) AS y, COUNT(*) AS n,
                   COUNT(DISTINCT ticker) AS tickers
              FROM filings GROUP BY y ORDER BY y
            """
        ).fetchall()
        if by_year:
            print("\n8-K filings by year:")
            for r in by_year:
                print(f"  {r['y']}: {r['n']:>7,} filings across {r['tickers']:>4} tickers")

        prow = conn.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
        if prow and prow[0]:
            sessions = len(
                trading_calendar.trading_days(
                    date.fromisoformat(prow[0]), date.fromisoformat(prow[1])
                )
            )
            print(f"\nPrices span: {prow[0]} .. {prow[1]}  ({sessions:,} NYSE sessions)")
    return 0


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_uni = sub.add_parser("universe", help="build/load point-in-time S&P 500 membership")
    p_uni.add_argument(
        "--rebuild", action="store_true", help="re-scrape Wikipedia and refreeze the CSV"
    )
    p_uni.set_defaults(func=cmd_universe)

    p_fil = sub.add_parser("filings", help="crawl EDGAR full index and ingest 8-Ks")
    p_fil.add_argument("--year", type=int, required=True)
    p_fil.add_argument("--quarter", type=int, choices=[1, 2, 3, 4])
    p_fil.add_argument("--limit", type=int, help="stop after N filings (for smoke tests)")
    p_fil.set_defaults(func=cmd_filings)

    p_pri = sub.add_parser("prices", help="fetch daily OHLC + benchmark from Tiingo")
    p_pri.add_argument("--year", type=int)
    p_pri.add_argument("--tickers", help="comma-separated override")
    p_pri.add_argument(
        "--tickers-file", help="path to a file with one ticker per line (for large universes)"
    )
    p_pri.set_defaults(func=cmd_prices)

    p_sta = sub.add_parser("status", help="row counts and coverage")
    p_sta.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
