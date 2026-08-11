"""Run a no-LLM experiment (002 or 004) and write its result bundle for the dashboard.

    uv run python scripts/run_experiment.py --experiment 002
    uv run python scripts/run_experiment.py --experiment 004

By default only the EXPLORE and HOLDOUT partitions are computed and BOTH are written, but
the dashboard labels HOLDOUT as confirmatory and EXPLORE as development. Locking and the
single-shot discipline are a human decision recorded in the HYPOTHESIS.md files — this
script just computes the numbers.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hindsight import config, db
from hindsight.experiments import event_type, staleness
from hindsight.manifest import RunManifest

RESULTS_DIR = config.DATA_DIR / "results"


def run_002() -> dict[str, Any]:
    with RunManifest("experiment_002_event_type") as manifest:
        with db.session() as conn:
            results = event_type.run(conn, manifest)
        return {
            "experiment": "002",
            "title": "Event-type conditional returns",
            "primary": "5-day, 10bps high-impact minus routine mean market-excess (HOLDOUT)",
            "groups": list(event_type.GROUPS),
            "results": [r.as_dict() for r in results],
            "manifest": manifest.to_dict(),
        }


def run_004() -> dict[str, Any]:
    with RunManifest("experiment_004_staleness") as manifest:
        with db.session() as conn:
            results = staleness.run(conn, manifest)
        return {
            "experiment": "004",
            "title": "Information staleness / first-disclosure",
            "primary": "Median staleness fraction > 0.5 on HOLDOUT (diagnostic)",
            "horizon": staleness.STALENESS_HORIZON,
            "results": [r.as_dict() for r in results],
            "manifest": manifest.to_dict(),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True, choices=["002", "004"])
    args = ap.parse_args()

    bundle = run_002() if args.experiment == "002" else run_004()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"experiment_{args.experiment}.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
