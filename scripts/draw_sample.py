"""Draw the frozen study sample (DEVIATIONS D16).

    python scripts/draw_sample.py --size 5000

Scoring every 8-K from 2010-2024 means ~100,000 LLM calls. A stratified random sample of
~5,000 answers every pre-registered hypothesis with essentially the same statistical power,
because detecting a 2-point edge over a coin flip at 80% power needs ~4,900 observations.

The sample is drawn **once**, with a fixed seed, and written to a committed CSV. Scoring
reads only that file. This matters more than it looks: a sample redrawn per run, or drawn
after glancing at results, is indistinguishable afterwards from one chosen to flatter them.
Freezing it makes the selection auditable and the run reproducible (invariant 4).

Strata are year x item-type group, with allocation proportional to each stratum's share of
the population, so the sample keeps the real mix of earnings, management changes and the
rest rather than over-weighting whichever is rarest.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hindsight import config, db  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402

SAMPLE_PATH = config.DATA_DIR / "study_sample.csv"

# §12 already requires reporting by item type, so the strata match the split that has to be
# reported anyway. A filing carries several item codes; it is assigned to the first group
# below that it matches, so every filing lands in exactly one stratum.
ITEM_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("earnings", ("2.02",)),
    ("management", ("5.02",)),
    ("agreement", ("1.01", "1.02")),
    ("other", ()),
]


def item_group(item_codes: str) -> str:
    codes = {c.strip() for c in (item_codes or "").split(",") if c.strip()}
    for name, wanted in ITEM_GROUPS:
        if wanted and codes & set(wanted):
            return name
    return "other"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=config.RANDOM_SEED)
    parser.add_argument("--force", action="store_true", help="redraw an existing sample")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="permit drawing before the full study period is ingested (pilots only)",
    )
    args = parser.parse_args(argv)

    if SAMPLE_PATH.exists() and not args.force:
        raise SystemExit(
            f"{SAMPLE_PATH} already exists. The sample is frozen on purpose — redrawing it "
            "after seeing results would invalidate the study. Pass --force only if nothing "
            "has been scored against it yet."
        )

    with (
        RunManifest("draw_sample", size=args.size, seed=args.seed) as manifest,
        db.session() as conn,
    ):
        rows = list(
            conn.execute(
                """
                SELECT accession_no, ticker, accepted_at_utc, item_codes
                  FROM filings
                 ORDER BY accepted_at_utc, accession_no
                """
            )
        )
        if not rows:
            raise SystemExit("No filings ingested yet.")

        # Refuse to freeze a sample that cannot represent the study period. Drawing before
        # the filings are ingested silently produces a single-year sample wearing a
        # fifteen-year label, and because the sample is frozen the error would survive
        # every later run.
        years_present = {row["accepted_at_utc"][:4] for row in rows}
        years_wanted = {str(y) for y in range(config.STUDY_START.year, config.STUDY_END.year + 1)}
        missing = years_wanted - years_present
        if missing and not args.allow_partial:
            raise SystemExit(
                f"Filings cover only {sorted(years_present)}, but the study period is "
                f"{config.STUDY_START.year}-{config.STUDY_END.year} "
                f"({len(missing)} years missing).\n"
                "Ingest the full period first:\n"
                "    python scripts/run_ingest.py filings --year YYYY   (per year)\n"
                "Pass --allow-partial only for a deliberately scoped pilot."
            )

        strata: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            year = row["accepted_at_utc"][:4]
            strata[(year, item_group(row["item_codes"]))].append(
                {
                    "accession_no": row["accession_no"],
                    "ticker": row["ticker"],
                    "accepted_at_utc": row["accepted_at_utc"],
                    "item_group": item_group(row["item_codes"]),
                    "year": year,
                }
            )

        population = len(rows)
        target = min(args.size, population)
        rng = random.Random(args.seed)

        # Proportional allocation, largest-remainder so the parts sum to the target exactly.
        exact = {key: len(members) * target / population for key, members in strata.items()}
        allocation = {key: int(value) for key, value in exact.items()}
        shortfall = target - sum(allocation.values())
        for key, _ in sorted(exact.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True):
            if shortfall <= 0:
                break
            if allocation[key] < len(strata[key]):
                allocation[key] += 1
                shortfall -= 1

        selected: list[dict[str, str]] = []
        for key in sorted(strata):
            members = sorted(strata[key], key=lambda m: m["accession_no"])
            take = min(allocation[key], len(members))
            selected.extend(rng.sample(members, take))
        selected.sort(key=lambda m: (m["accepted_at_utc"], m["accession_no"]))

        SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SAMPLE_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["accession_no", "ticker", "accepted_at_utc", "item_group", "year"]
            )
            writer.writeheader()
            writer.writerows(selected)

        manifest.count("population", population)
        manifest.count("sampled", len(selected))
        by_group = Counter(m["item_group"] for m in selected)
        by_year = Counter(m["year"] for m in selected)
        manifest.params["by_item_group"] = dict(by_group)
        manifest.params["by_year"] = dict(sorted(by_year.items()))

        print(f"\n  population {population:,} -> sampled {len(selected):,}  (seed {args.seed})")
        print(f"  frozen to {SAMPLE_PATH}")
        print("\n  by item type:")
        for group, count in by_group.most_common():
            share = 100 * count / len(selected)
            print(f"    {group:<12} {count:>6,}  ({share:4.1f}%)")
        print("\n  by year:")
        for year, count in sorted(by_year.items()):
            print(f"    {year}: {count:>5,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
