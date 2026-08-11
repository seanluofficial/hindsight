"""Run a no-LLM experiment (002 / 003 / 004) and write its result bundle for the dashboard.

    uv run python scripts/run_experiment.py --experiment 003
    uv run python scripts/run_experiment.py --experiment 003 --partition explore

`--partition explore` computes ONLY the development years, so a future experiment's HOLDOUT
is not spent by the act of building it (see DEVIATIONS D-EXP1). The default runs both and
the dashboard labels HOLDOUT as confirmatory and EXPLORE as development. Locking and the
single-shot discipline are a human decision recorded in the HYPOTHESIS.md files.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hindsight import config, db
from hindsight.experiments import event_type, novelty, staleness
from hindsight.manifest import RunManifest

RESULTS_DIR = config.DATA_DIR / "results"


def run_002(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_002_event_type", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            results = event_type.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "002",
            "title": "Event-type conditional returns",
            "primary": "5-day, 10bps high-impact minus routine mean market-excess (HOLDOUT)",
            "groups": list(event_type.GROUPS),
            "results": [r.as_dict() for r in results],
            "manifest": manifest.to_dict(),
        }


def run_003(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_003_novelty", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            results = novelty.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "003",
            "title": "Filing novelty / linguistic change ('Lazy Prices')",
            "primary": "20-day, 10bps quintile long/short Sharpe on the change score (HOLDOUT)",
            "cost_bps": config.BASE_CASE_COST_BPS,
            "results": [r.as_dict() for r in results],
            "manifest": manifest.to_dict(),
        }


def run_004(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_004_staleness", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            results = staleness.run(conn, manifest, partitions=partitions)
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
    ap.add_argument("--experiment", required=True, choices=["002", "003", "004"])
    ap.add_argument(
        "--partition",
        choices=["both", "explore", "holdout"],
        default="both",
        help="which partitions to compute (default both). Use 'explore' before locking.",
    )
    args = ap.parse_args()

    partitions = ("explore", "holdout") if args.partition == "both" else (args.partition,)
    runners = {"002": run_002, "003": run_003, "004": run_004}
    bundle = runners[args.experiment](partitions)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"experiment_{args.experiment}.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
