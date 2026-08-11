"""Ingest SEC Form 4 insider open-market purchases for Experiment 006.

Source: SEC's structured **Form 345 quarterly data sets** (one ~15 MB zip per quarter),
cached under data/raw/ like every other fetch. We keep only what the cluster-buy signal
needs: non-derivative **open-market purchases** (TRANS_CODE='P', acquired) by officers or
directors of **point-in-time S&P 500 members**, written to data/insider_purchases.csv.

No lookahead: the point-in-time signal date is the Form 4 FILING_DATE (filed within two
business days of the trade), and universe membership is checked at that date against the
frozen `universe` table (no survivorship).

    uv run python scripts/ingest_insider.py [--start-year 2010] [--end-year 2024]
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import zipfile
from datetime import date, datetime
from pathlib import Path

from hindsight import config, db
from hindsight.ingest.http import CachedFetcher
from hindsight.manifest import RunManifest

DATASET_URL = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
    "{year}q{quarter}_form345.zip"
)
OUTPUT_CSV = config.DATA_DIR / "insider_purchases.csv"
ALL_OUTPUT_CSV = config.DATA_DIR / "insider_purchases_all.csv"
FIELDS = [
    "issuer_cik",
    "ticker",
    "accession",
    "filing_date",
    "trans_date",
    "owner_cik",
    "role",
    "shares",
    "price",
    "value",
]


# Exchange codes that appear glued to the symbol in the raw Form 4 field
# (e.g. "OTCBB:BDCG", "NYSE: DM", "VZX:TSXV"). They are not tickers.
_EXCHANGE_CODES = frozenset(
    {
        "NYSE", "NASDAQ", "NASD", "OTCBB", "OTC", "OTCMKTS", "OTCQB", "OTCQX",
        "TSX", "TSXV", "AMEX", "ARCA", "BATS", "PINK", "OB", "NYSEAMERICAN",
        "NYSEMKT", "CBOE", "NYSEARCA",
    }
)
_NON_TICKERS = frozenset({"NA", "NONE", "N", "A", "NULL", "TBD"})
_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")


def clean_ticker(raw: str) -> str | None:
    """Recover a plausible US ticker from the messy Form 4 ISSUERTRADINGSYMBOL field.

    The field is free text: symbols arrive wrapped in brackets/quotes, prefixed with an
    exchange ("NYSE: DM"), doubled up ("ISCA, ISCB"), or replaced by a company name. We split
    on anything that is not ticker-ish and take the first token that looks like a symbol and is
    not a known exchange code. Returns None when nothing usable is found (counted, never
    silently coerced).
    """
    for token in re.split(r"[^A-Z0-9.\-]+", raw.upper()):
        token = token.strip(".-")
        if not token or token in _EXCHANGE_CODES or token in _NON_TICKERS:
            continue
        if _TICKER_RE.fullmatch(token):
            return token
    return None


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d-%b-%Y").date()
    except ValueError:
        return None


class UniverseIndex:
    """Point-in-time S&P 500 membership, indexed by CIK and by ticker."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.by_cik: dict[int, list[tuple[date, date, str]]] = {}
        self.by_ticker: dict[str, list[tuple[date, date, int]]] = {}
        for row in conn.execute("SELECT ticker, cik, start_date, end_date FROM universe"):
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"]) if row["end_date"] else date(9999, 12, 31)
            cik = int(row["cik"]) if row["cik"] is not None else 0
            if cik:
                self.by_cik.setdefault(cik, []).append((start, end, row["ticker"]))
            if row["ticker"]:
                self.by_ticker.setdefault(row["ticker"].upper(), []).append((start, end, cik))

    def member_ticker(self, cik: int, ticker: str, on: date) -> str | None:
        """Return the universe ticker if (cik or ticker) was a member on `on`, else None."""
        for start, end, tk in self.by_cik.get(cik, []):
            if start <= on <= end:
                return tk
        for start, end, _ in self.by_ticker.get(ticker.upper(), []):
            if start <= on <= end:
                return ticker.upper()
        return None


def _read_tsv(zf: zipfile.ZipFile, name: str) -> tuple[list[str], list[list[str]]]:
    with zf.open(name) as f:
        text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        reader = csv.reader(text, delimiter="\t")
        header = next(reader)
        return header, [r for r in reader]


def _process_quarter(
    raw: bytes, universe: UniverseIndex, manifest: RunManifest, scope: str = "sp500"
) -> list[dict[str, object]]:
    zf = zipfile.ZipFile(io.BytesIO(raw))

    # SUBMISSION: accession -> (issuer_cik, ticker, filing_date), Form 4 only.
    sub_hdr, sub_rows = _read_tsv(zf, "SUBMISSION.tsv")
    si = {c: i for i, c in enumerate(sub_hdr)}
    submissions: dict[str, tuple[int, str, date]] = {}
    for r in sub_rows:
        if r[si["DOCUMENT_TYPE"]].strip() != "4":
            continue
        filed = _parse_date(r[si["FILING_DATE"]])
        cik_s = r[si["ISSUERCIK"]].strip()
        ticker = r[si["ISSUERTRADINGSYMBOL"]].strip()
        if filed is None or not cik_s:
            continue
        submissions[r[si["ACCESSION_NUMBER"]]] = (int(cik_s), ticker, filed)

    # REPORTINGOWNER: accession -> list of (owner_cik, relationship). Officer/Director only.
    own_hdr, own_rows = _read_tsv(zf, "REPORTINGOWNER.tsv")
    oi = {c: i for i, c in enumerate(own_hdr)}
    owners: dict[str, list[tuple[str, str]]] = {}
    for r in own_rows:
        rel = r[oi["RPTOWNER_RELATIONSHIP"]]
        low = rel.lower()
        if "officer" not in low and "director" not in low:
            continue
        role = "officer" if "officer" in low else "director"
        owners.setdefault(r[oi["ACCESSION_NUMBER"]], []).append(
            (r[oi["RPTOWNERCIK"]].strip(), role)
        )

    # NONDERIV_TRANS: open-market purchases (P, acquired) only.
    tr_hdr, tr_rows = _read_tsv(zf, "NONDERIV_TRANS.tsv")
    ti = {c: i for i, c in enumerate(tr_hdr)}
    out: list[dict[str, object]] = []
    for r in tr_rows:
        if r[ti["TRANS_CODE"]].strip() != "P":
            continue
        if r[ti["TRANS_ACQUIRED_DISP_CD"]].strip() != "A":
            continue
        acc = r[ti["ACCESSION_NUMBER"]]
        sub = submissions.get(acc)
        owner_list = owners.get(acc)
        if sub is None or not owner_list:
            continue
        issuer_cik, ticker, filed = sub
        if scope == "all":
            # Whole-market scope (experiment 009): keep any issuer with a usable ticker;
            # point-in-time membership is enforced later by price coverage at the event date.
            cleaned = clean_ticker(ticker)
            if cleaned is None:
                manifest.exclude("issuer_no_usable_ticker")
                continue
            ticker_pit = cleaned
        else:
            member = universe.member_ticker(issuer_cik, ticker, filed)
            if member is None:
                manifest.exclude("issuer_not_universe_member_at_filing")
                continue
            ticker_pit = member
        trans_date = _parse_date(r[ti["TRANS_DATE"]])
        try:
            shares = float(r[ti["TRANS_SHARES"]] or 0)
            price = float(r[ti["TRANS_PRICEPERSHARE"]] or 0)
        except ValueError:
            manifest.exclude("unparseable_shares_or_price")
            continue
        owner_cik, role = owner_list[0]
        manifest.count("purchases_kept")
        out.append(
            {
                "issuer_cik": issuer_cik,
                "ticker": ticker_pit,
                "accession": acc,
                "filing_date": filed.isoformat(),
                "trans_date": trans_date.isoformat() if trans_date else "",
                "owner_cik": owner_cik,
                "role": role,
                "shares": round(shares, 2),
                "price": round(price, 4),
                "value": round(shares * price, 2),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2024)
    ap.add_argument(
        "--scope",
        choices=["sp500", "all"],
        default="sp500",
        help="'sp500' (default, experiment 006) keeps only S&P 500 members; 'all' keeps every "
        "Form-4 issuer with a ticker (experiment 009, whole-market/small-cap).",
    )
    ap.add_argument(
        "--output",
        help="output CSV path (default depends on scope)",
    )
    args = ap.parse_args()

    default_csv = OUTPUT_CSV if args.scope == "sp500" else ALL_OUTPUT_CSV
    output_csv = Path(args.output) if args.output else default_csv

    with RunManifest(
        "ingest_insider", start=args.start_year, end=args.end_year, scope=args.scope
    ) as manifest:
        fetcher = CachedFetcher()
        with db.session() as conn:
            universe = UniverseIndex(conn)

        rows: list[dict[str, object]] = []
        for year in range(args.start_year, args.end_year + 1):
            for quarter in range(1, 5):
                url = DATASET_URL.format(year=year, quarter=quarter)
                try:
                    raw = fetcher.get(url)
                except Exception as exc:  # noqa: BLE001 - a missing quarter is logged, not fatal
                    manifest.exclude("quarter_fetch_failed", f"{year}q{quarter}: {exc}")
                    continue
                quarter_rows = _process_quarter(raw, universe, manifest, scope=args.scope)
                rows.extend(quarter_rows)
                manifest.count("quarters_processed")
                print(f"  {year}Q{quarter}: {len(quarter_rows):,} universe purchases")

        rows.sort(key=lambda d: (str(d["filing_date"]), str(d["ticker"])))
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        manifest.count("rows_written", len(rows))
        print(f"\nwrote {output_csv} ({len(rows):,} rows)")


if __name__ == "__main__":
    main()
