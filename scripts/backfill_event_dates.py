"""Backfill filings.period_of_report from the cached raw filings.

The event date ("Date of earliest event reported") was only extracted for part of the
corpus during ingest, leaving every HOLDOUT year empty — which blocks Experiment 004.
The date is present in each cached filing's cover page, so this reparses the local cache
(no network, invariant on caching preserved) and fills the blank rows only.

Runs safely alongside a live scorer: small batched commits and a long busy_timeout so the
two writers never collide. Idempotent — only rows that are currently blank are touched.

    uv run python scripts/backfill_event_dates.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from hindsight import db
from hindsight.manifest import RunManifest

# "Date of Report (Date of earliest event reported): February 4, 2021"
_EVENT_RE = re.compile(
    r"earliest\s+event\s+reported\)?\s*:?\s*"
    r"([A-Z][a-z]+\.?\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)


def parse_event_date(text: str) -> str | None:
    """Return an ISO date parsed from the cover page, or None."""
    m = _EVENT_RE.search(text)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).replace(".", "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap rows processed (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="parse but do not write")
    args = ap.parse_args()

    with RunManifest("backfill_event_dates", limit=args.limit, dry_run=args.dry_run) as manifest:
        conn = db.connect()
        conn.execute("PRAGMA busy_timeout = 60000")  # coexist with a live writer
        rows = conn.execute(
            "SELECT accession_no, raw_path FROM filings "
            "WHERE period_of_report IS NULL OR period_of_report = '' "
            "ORDER BY accepted_at_utc"
        ).fetchall()
        if args.limit:
            rows = rows[: args.limit]
        manifest.count("blank_rows", len(rows))

        batch: list[tuple[str, str]] = []
        for row in rows:
            path = Path(row["raw_path"])
            if not path.exists():
                manifest.exclude("raw_file_missing", row["accession_no"])
                continue
            iso = parse_event_date(path.read_text(errors="ignore"))
            if iso is None:
                manifest.exclude("no_event_date_in_text", row["accession_no"])
                continue
            manifest.count("parsed")
            batch.append((iso, row["accession_no"]))
            if not args.dry_run and len(batch) >= 500:
                conn.executemany(
                    "UPDATE filings SET period_of_report = ? WHERE accession_no = ?", batch
                )
                conn.commit()
                manifest.count("written", len(batch))
                batch = []
        if not args.dry_run and batch:
            conn.executemany(
                "UPDATE filings SET period_of_report = ? WHERE accession_no = ?", batch
            )
            conn.commit()
            manifest.count("written", len(batch))
        conn.close()


if __name__ == "__main__":
    main()
