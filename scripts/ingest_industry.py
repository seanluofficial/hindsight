"""Ingest SIC industry codes for Experiment 008 (peer / lead-lag diffusion).

008 needs a peer map: which universe members are in the same industry. The SEC submissions
API (https://data.sec.gov/submissions/CIK##########.json) reports each issuer's SIC code and
description. We fetch one JSON per distinct universe CIK (cached under data/raw/ like every
other fetch, ~600 small requests) and write data/industry.csv: one row per (cik, ticker) with
its SIC.

The SIC code is a stable property of the issuer, not a point-in-time series, so a single
current value is the honest best available here; the classification does not look ahead to any
return. Peer *membership* on any given date is still enforced point-in-time from the frozen
`universe` table by the experiment itself.

    uv run python scripts/ingest_industry.py
"""

from __future__ import annotations

import csv
import json

from hindsight import config, db
from hindsight.ingest.http import CachedFetcher
from hindsight.manifest import RunManifest

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
OUTPUT_CSV = config.DATA_DIR / "industry.csv"
FIELDS = ["cik", "ticker", "sic", "sic_description"]


def main() -> None:
    with RunManifest("ingest_industry") as manifest:
        with db.session() as conn:
            # (cik, ticker) pairs to resolve, and the ciks to look up.
            pairs = [
                (int(r["cik"]), r["ticker"].upper())
                for r in conn.execute(
                    "SELECT DISTINCT cik, ticker FROM universe "
                    "WHERE cik IS NOT NULL AND ticker IS NOT NULL"
                )
            ]
        ciks = sorted({cik for cik, _ in pairs})
        manifest.count("distinct_ciks", len(ciks))

        fetcher = CachedFetcher()
        sic_by_cik: dict[int, tuple[str, str]] = {}
        for cik in ciks:
            url = SUBMISSIONS_URL.format(cik=cik)
            try:
                raw = fetcher.get(url)
            except Exception as exc:  # noqa: BLE001 - a missing issuer is logged, not fatal
                manifest.exclude("submissions_fetch_failed", f"{cik}: {exc}")
                continue
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                manifest.exclude("submissions_unparseable", str(cik))
                continue
            sic = str(doc.get("sic") or "").strip()
            desc = str(doc.get("sicDescription") or "").strip()
            if not sic:
                manifest.exclude("no_sic_code", str(cik))
                continue
            sic_by_cik[cik] = (sic, desc)
            manifest.count("sic_resolved")

        rows = [
            {"cik": cik, "ticker": ticker, "sic": sic_by_cik[cik][0],
             "sic_description": sic_by_cik[cik][1]}
            for cik, ticker in pairs
            if cik in sic_by_cik
        ]
        rows.sort(key=lambda d: (str(d["sic"]), str(d["ticker"])))
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        manifest.count("rows_written", len(rows))
        print(f"\nwrote {OUTPUT_CSV} ({len(rows):,} ticker rows, {len(sic_by_cik):,} issuers)")


if __name__ == "__main__":
    main()
