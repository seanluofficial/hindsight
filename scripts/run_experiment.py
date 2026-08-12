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
from hindsight.experiments import (
    diffusion,
    event_type,
    insider,
    momentum,
    novelty,
    pead,
    staleness,
    timing,
)
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
            by_event = staleness.by_event_type(conn, manifest)
        return {
            "experiment": "004",
            "title": "Information staleness / first-disclosure",
            "primary": "Median staleness fraction > 0.5 on HOLDOUT (diagnostic)",
            "horizon": staleness.STALENESS_HORIZON,
            "results": [r.as_dict() for r in results],
            "by_event_type": by_event,
            "manifest": manifest.to_dict(),
        }


def run_005(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_005_pead", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            scored = pead.compute_surprises(conn, manifest)
            results = pead.evaluate(conn, scored, manifest, partitions=partitions)
            # Robustness is always EXPLORE-only so the single HOLDOUT shot stays reserved.
            robustness = pead.robustness(conn, scored, partition="explore")
            # The single confirmatory read: the frozen long-only construction on 2020-2024,
            # computed only when the caller explicitly asks for the holdout partition.
            holdout_shot = (
                pead.robustness(conn, scored, partition="holdout")
                if "holdout" in partitions
                else None
            )
        bundle: dict[str, Any] = {
            "experiment": "005",
            "title": "Post-earnings-announcement drift (PEAD)",
            "primary": "20-day, 10bps quintile long/short Sharpe on the surprise signal (HOLDOUT)",
            "cost_bps": config.BASE_CASE_COST_BPS,
            "horizons": list(pead.PEAD_HORIZONS),
            "results": [r.as_dict() for r in results],
            "robustness": robustness,
            "manifest": manifest.to_dict(),
        }
        if holdout_shot is not None:
            bundle["holdout_shot"] = holdout_shot
        return bundle


def run_006(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_006_insider", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            payload = insider.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "006",
            "title": "Insider cluster-buying (Form 4)",
            "primary": "20-day, 10bps mean market-excess of cluster-buy events (HOLDOUT)",
            "horizons": list(insider.INSIDER_HORIZONS),
            **payload,
            "manifest": manifest.to_dict(),
        }


def run_007(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_007_timing", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            payload = timing.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "007",
            "title": "'Bury bad news' filing timing",
            "primary": "20-day, 10bps mean market-excess of buried 8-Ks (HOLDOUT); H1 negative",
            "horizons": list(timing.TIMING_HORIZONS),
            "cost_bps": config.BASE_CASE_COST_BPS,
            **payload,
            "manifest": manifest.to_dict(),
        }


def run_008(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_008_diffusion", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            payload = diffusion.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "008",
            "title": "Peer / lead-lag information diffusion",
            "primary": "20-day, 10bps mean signed peer market-excess (sign of filer reaction), "
            "3-digit SIC peers (HOLDOUT); H1 positive",
            "horizons": list(diffusion.DIFFUSION_HORIZONS),
            "cost_bps": config.BASE_CASE_COST_BPS,
            **payload,
            "manifest": manifest.to_dict(),
        }


def run_009(partitions: tuple[str, ...]) -> dict[str, Any]:
    """Experiment 009 — insider cluster-buying on the whole-market (small-cap) universe.

    Reuses the 006 signal code against the broadened purchases file (all Form-4 issuers with a
    ticker, not just S&P 500). Requires prices for the small-cap tickers; see
    scripts/ingest_insider.py --scope all and the ticker list from build_smallcap_ticker_list.
    """
    all_csv = config.DATA_DIR / "insider_purchases_all.csv"
    with RunManifest("experiment_009_insider_smallcap", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            payload = insider.run(conn, manifest, partitions=partitions, csv_path=all_csv)
        return {
            "experiment": "009",
            "title": "Insider cluster-buying, whole-market / small-cap (Form 4)",
            "primary": "20-day, 10bps mean market-excess of cluster-buy events, whole-market "
            "universe (HOLDOUT); H1 positive",
            "horizons": list(insider.INSIDER_HORIZONS),
            **payload,
            "manifest": manifest.to_dict(),
        }


def run_010(partitions: tuple[str, ...]) -> dict[str, Any]:
    with RunManifest("experiment_010_momentum", partitions=list(partitions)) as manifest:
        with db.session() as conn:
            payload = momentum.run(conn, manifest, partitions=partitions)
        return {
            "experiment": "010",
            "title": "Cross-sectional momentum (12-1), whole-market / small-cap",
            "primary": "20-day, 10bps quintile L/S Sharpe on 12-1 momentum (HOLDOUT); H1 positive",
            **payload,
            "manifest": manifest.to_dict(),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--experiment",
        required=True,
        choices=["002", "003", "004", "005", "006", "007", "008", "009", "010"],
    )
    ap.add_argument(
        "--partition",
        choices=["both", "explore", "holdout", "forward", "all"],
        default="both",
        help="partitions to compute. 'both'=explore+holdout; 'all' adds forward (2025+, "
        "uncontaminable); a single name computes only that one. Use 'explore' before locking.",
    )
    args = ap.parse_args()

    partition_sets: dict[str, tuple[str, ...]] = {
        "both": ("explore", "holdout"),
        "all": ("explore", "holdout", "forward"),
    }
    partitions = partition_sets.get(args.partition, (args.partition,))
    runners = {
        "002": run_002,
        "003": run_003,
        "004": run_004,
        "005": run_005,
        "006": run_006,
        "007": run_007,
        "008": run_008,
        "009": run_009,
        "010": run_010,
    }
    bundle = runners[args.experiment](partitions)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"experiment_{args.experiment}.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
