"""Export a compact results bundle for the deployed dashboard.

    python scripts/export_results.py

The working database is ~95MB and the raw filing cache is ~2.8GB, so neither can be
committed or shipped to a hosting tier. The dashboard needs only evaluated trades, which
compress to a couple of megabytes, so this writes `data/results/` and the dashboard reads
that whenever the database is absent.

The bundle is derived, never authoritative: it is regenerated from the database, and the
manifest records the git SHA it was built at so a published chart can be traced back to
the code and data that produced it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from hindsight import config, db  # noqa: E402
from hindsight.evaluate import returns  # noqa: E402
from hindsight.manifest import RunManifest, git_sha  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results"


def export(model_id: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RunManifest("export", model_id=model_id) as manifest, db.session() as conn:
        trades = returns.evaluate_all(conn, model_id, manifest)
        if not trades:
            raise SystemExit(f"No evaluable trades for {model_id}.")

        frame = pd.DataFrame(
            [
                {
                    "prediction_id": t.prediction_id,
                    "accession_no": t.accession_no,
                    "ticker": t.ticker,
                    "direction": t.direction,
                    "probability": t.probability,
                    "horizon": t.horizon,
                    "entry_date": t.entry_date.isoformat(),
                    "exit_date": t.exit_date.isoformat(),
                    "raw_return": t.raw_return,
                    "benchmark_return": t.benchmark_return,
                    "excess_return": t.excess_return,
                }
                for t in trades
            ]
        )
        safe = model_id.replace("/", "_")
        path = RESULTS_DIR / f"trades_{safe}.csv.gz"
        frame.to_csv(path, index=False, compression="gzip")

        counts = db.table_counts(conn)
        anonymized = conn.execute(
            "SELECT COUNT(*) FROM filings WHERE anon_version IS NOT NULL"
        ).fetchone()[0]
        span = conn.execute(
            "SELECT MIN(accepted_at_utc), MAX(accepted_at_utc) FROM filings"
        ).fetchone()

        summary = {
            "model_id": model_id,
            "git_sha": git_sha(),
            "exported_at_utc": datetime.now(UTC).isoformat(),
            "table_counts": counts,
            "anonymized_filings": anonymized,
            "filing_span": {"first": span[0], "last": span[1]},
            "trades": len(trades),
            "exclusions": dict(manifest.exclusions),
        }
        (RESULTS_DIR / f"summary_{safe}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

        manifest.count("trades_exported", len(trades))
        size_kb = path.stat().st_size / 1024
        print(f"  wrote {path.name} ({size_kb:,.0f} KB, {len(frame):,} rows)")
        print(f"  wrote summary_{safe}.json")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="model_id to export; omit to export all")
    args = parser.parse_args(argv)

    with db.session() as conn:
        models = (
            [args.model]
            if args.model
            else [r[0] for r in conn.execute("SELECT DISTINCT model_id FROM predictions")]
        )
    if not models:
        print("No predictions stored.")
        return 1
    for model_id in models:
        export(model_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
