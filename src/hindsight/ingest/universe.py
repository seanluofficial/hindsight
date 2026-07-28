"""Point-in-time S&P 500 membership.

Invariant 2 forbids survivorship bias: a company that left the index in 2016 must still
appear in 2014 samples. A current-constituents list cannot give you that, because the
companies that were dropped are exactly the ones that did badly.

Reconstruction walks Wikipedia's index-change history *backwards* from today's members:

    members := today's constituents
    for each change, newest to oldest:
        a ticker ADDED on date D  -> its current membership interval began on D; close it
        a ticker REMOVED on date D -> it was a member up to D; open an interval ending on D

The output is frozen to `data/sp500_membership.csv` and committed. Ingest reads only that
file, never the live page, because Wikipedia is edited continuously and invariant 4
requires that two runs of the same code produce the same numbers.

Known limitation, reported rather than hidden: the source table is titled *selected*
changes and thins out the further back you go. `membership_health()` measures the damage
by counting members per year — a real S&P 500 sits at ~500, so drift is the error bar.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from hindsight import config
from hindsight.ingest.http import CachedFetcher, RateLimiter
from hindsight.manifest import RunManifest

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Members with no recorded addition survive the whole backward walk. The index itself
# dates to 1957, so this sentinel means "a member since before our records begin".
EPOCH = date(1957, 3, 4)

# Wikipedia is fine with a normal crawl rate; it is not the SEC.
_wiki_limiter = RateLimiter(max_per_second=2.0)


@dataclass(frozen=True)
class Membership:
    """One continuous stretch of index membership. `end_date is None` means current."""

    ticker: str
    name: str
    cik: int | None
    start_date: date
    end_date: date | None

    def contains(self, day: date) -> bool:
        """Membership is inclusive of the start and exclusive of the removal date."""
        return self.start_date <= day and (self.end_date is None or day < self.end_date)


def _normalize_ticker(raw: object) -> str:
    """Wikipedia writes BRK.B, EDGAR and vendors write BRK-B."""
    return str(raw).strip().upper().replace(".", "-").replace("​", "")


def _parse_date(raw: object) -> date | None:
    try:
        parsed = pd.to_datetime(str(raw).strip(), errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


# --------------------------------------------------------------------------
# Source tables
# --------------------------------------------------------------------------
def fetch_wikipedia_tables(fetcher: CachedFetcher | None = None) -> list[pd.DataFrame]:
    fetcher = fetcher or CachedFetcher(user_agent=config.EDGAR_USER_AGENT, limiter=_wiki_limiter)
    html = fetcher.get_text(WIKIPEDIA_URL, encoding="utf-8")
    return pd.read_html(io.StringIO(html))


def _find_current_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for t in tables:
        cols = {str(c).strip().lower() for c in t.columns}
        if {"symbol", "security"} <= cols:
            return t
    raise RuntimeError(
        "Wikipedia layout changed: no constituents table with Symbol+Security columns found"
    )


def _find_changes_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for t in tables:
        flat = set(_flatten_columns(t).columns)
        if _date_column(flat) and any(c.startswith("added_") for c in flat):
            return t
    raise RuntimeError(
        "Wikipedia layout changed: no index-changes table with Date/Added columns found"
    )


def _date_column(columns: set[str]) -> str | None:
    """The heading has drifted between 'Date' and 'Effective Date' over the years."""
    candidates = [c for c in columns if "date" in c and not c.startswith(("added_", "removed_"))]
    return sorted(candidates, key=len)[0] if candidates else None


def _flatten_columns(table: pd.DataFrame) -> pd.DataFrame:
    """The changes table has two header rows: Added/Removed over Ticker/Security.

    Single-level headings are repeated across both rows ('Effective Date' over
    'Effective Date'), so identical parts are collapsed rather than doubled.
    """
    out = table.copy()
    if isinstance(out.columns, pd.MultiIndex):
        flattened: list[str] = []
        for col in out.columns:
            parts: list[str] = []
            for raw in col:
                part = str(raw).strip()
                if not part or part.startswith("Unnamed") or (parts and part == parts[-1]):
                    continue
                parts.append(part)
            flattened.append("_".join(parts))
        out.columns = flattened
    else:
        out.columns = [str(c).strip() for c in out.columns]
    out.columns = [c.strip().lower().replace(" ", "_") for c in out.columns]
    return out


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------
def reconstruct_membership(
    tables: list[pd.DataFrame], manifest: RunManifest | None = None
) -> list[Membership]:
    current_raw = _find_current_table(tables)
    changes_raw = _flatten_columns(_find_changes_table(tables))

    current = current_raw.copy()
    current.columns = [str(c).strip().lower().replace(" ", "_") for c in current.columns]

    names: dict[str, str] = {}
    ciks: dict[str, int | None] = {}
    open_intervals: dict[str, date | None] = {}

    for _, row in current.iterrows():
        ticker = _normalize_ticker(row["symbol"])
        if not ticker or ticker == "NAN":
            continue
        names[ticker] = str(row.get("security", "")).strip()
        raw_cik = row.get("cik")
        try:
            ciks[ticker] = int(raw_cik) if pd.notna(raw_cik) else None
        except (TypeError, ValueError):
            ciks[ticker] = None
        # Still a member today: open interval with no end.
        open_intervals[ticker] = None

    closed: list[Membership] = []

    def emit(ticker: str, start: date, end: date | None) -> None:
        if end is not None and start >= end:
            # A same-day add/remove pair, or a Wikipedia ordering artifact. Not a real interval.
            if manifest:
                manifest.exclude("universe_zero_length_interval", f"{ticker} {start}->{end}")
            return
        closed.append(
            Membership(
                ticker=ticker,
                name=names.get(ticker, ""),
                cik=ciks.get(ticker),
                start_date=start,
                end_date=end,
            )
        )

    # Sort oldest->newest, then consume in reverse so ties resolve deterministically.
    changes = changes_raw.copy()
    date_col = _date_column(set(changes.columns))
    if date_col is None:
        raise RuntimeError(f"changes table has no date column; saw {list(changes.columns)}")
    changes["_parsed_date"] = changes[date_col].map(_parse_date)
    bad_dates = int(changes["_parsed_date"].isna().sum())
    if bad_dates and manifest:
        manifest.exclude("universe_unparseable_change_date", f"{bad_dates} rows")
    changes = changes.dropna(subset=["_parsed_date"])
    changes = changes.sort_values("_parsed_date", kind="stable").reset_index(drop=True)

    added_col = next((c for c in changes.columns if c.startswith("added_") and "ticker" in c), None)
    removed_col = next(
        (c for c in changes.columns if c.startswith("removed_") and "ticker" in c), None
    )
    added_name_col = next(
        (c for c in changes.columns if c.startswith("added_") and "security" in c), None
    )
    removed_name_col = next(
        (c for c in changes.columns if c.startswith("removed_") and "security" in c), None
    )
    if added_col is None or removed_col is None:
        raise RuntimeError(f"changes table missing ticker columns; saw {list(changes.columns)}")

    for _, row in changes.iloc[::-1].iterrows():
        when: date = row["_parsed_date"]

        removed = _normalize_ticker(row[removed_col]) if pd.notna(row[removed_col]) else ""
        added = _normalize_ticker(row[added_col]) if pd.notna(row[added_col]) else ""

        # Process the addition first: it closes an interval and frees the ticker, which
        # matters when the same symbol is removed and re-added later in history.
        if added and added != "NAN":
            if added in open_intervals:
                emit(added, when, open_intervals.pop(added))
            elif manifest:
                # Added but not currently open: it was added and later removed, and the
                # removal row is missing from this "selected changes" table.
                manifest.exclude("universe_add_without_open_interval", f"{added} {when}")

        if removed and removed != "NAN":
            if removed_name_col and pd.notna(row.get(removed_name_col)):
                names.setdefault(removed, str(row[removed_name_col]).strip())
            if removed in open_intervals:
                # Removed while we already believe it is open: the add row is missing.
                if manifest:
                    manifest.exclude("universe_remove_while_open", f"{removed} {when}")
                emit(removed, when, open_intervals.pop(removed))
            open_intervals[removed] = when

        if added and added_name_col and pd.notna(row.get(added_name_col)):
            names.setdefault(added, str(row[added_name_col]).strip())

    # Whatever is still open was a member before the change history begins.
    for ticker, end in open_intervals.items():
        emit(ticker, EPOCH, end)

    closed.sort(key=lambda m: (m.ticker, m.start_date))
    return closed


# --------------------------------------------------------------------------
# CIK resolution
# --------------------------------------------------------------------------
def resolve_ciks(
    memberships: list[Membership],
    fetcher: CachedFetcher | None = None,
    manifest: RunManifest | None = None,
) -> list[Membership]:
    """Fill missing CIKs from SEC's ticker map.

    That map only covers *current* registrants, so delisted members often stay NULL.
    They are kept, not dropped — `edgar.py` falls back to matching on company name.
    """
    fetcher = fetcher or CachedFetcher()
    raw = fetcher.get_text(config.SEC_COMPANY_TICKERS_URL, encoding="utf-8")
    mapping: dict[str, int] = {}
    for entry in json.loads(raw).values():
        mapping[_normalize_ticker(entry["ticker"])] = int(entry["cik_str"])

    out: list[Membership] = []
    unresolved = 0
    for m in memberships:
        cik = m.cik if m.cik is not None else mapping.get(m.ticker)
        if cik is None:
            unresolved += 1
            if manifest:
                manifest.exclude("universe_cik_unresolved", m.ticker)
        out.append(Membership(m.ticker, m.name, cik, m.start_date, m.end_date))
    if manifest:
        manifest.count("universe_cik_resolved", len(out) - unresolved)
    return out


# --------------------------------------------------------------------------
# Freeze / load
# --------------------------------------------------------------------------
CSV_HEADER = ["ticker", "name", "cik", "start_date", "end_date"]


def write_frozen_csv(memberships: list[Membership], path: Path | None = None) -> Path:
    target = path or config.UNIVERSE_CSV_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for m in memberships:
            writer.writerow(
                [
                    m.ticker,
                    m.name,
                    "" if m.cik is None else m.cik,
                    m.start_date.isoformat(),
                    "" if m.end_date is None else m.end_date.isoformat(),
                ]
            )
    return target


def load_frozen_csv(path: Path | None = None) -> list[Membership]:
    source = path or config.UNIVERSE_CSV_PATH
    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found. Build it once with:\n"
            f"    python scripts/run_ingest.py universe --rebuild"
        )
    out: list[Membership] = []
    with source.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(
                Membership(
                    ticker=row["ticker"],
                    name=row["name"],
                    cik=int(row["cik"]) if row["cik"] else None,
                    start_date=datetime.strptime(row["start_date"], "%Y-%m-%d").date(),
                    end_date=(
                        datetime.strptime(row["end_date"], "%Y-%m-%d").date()
                        if row["end_date"]
                        else None
                    ),
                )
            )
    return out


def load_to_db(
    conn: sqlite3.Connection,
    memberships: list[Membership] | None = None,
    manifest: RunManifest | None = None,
) -> int:
    """Replace the `universe` table from the frozen CSV. Idempotent."""
    rows = memberships if memberships is not None else load_frozen_csv()
    conn.execute("DELETE FROM universe")
    conn.executemany(
        "INSERT INTO universe (ticker, cik, start_date, end_date) VALUES (?, ?, ?, ?)",
        [
            (
                m.ticker,
                m.cik,
                m.start_date.isoformat(),
                m.end_date.isoformat() if m.end_date else None,
            )
            for m in rows
        ],
    )
    if manifest:
        manifest.count("universe_rows_written", len(rows))
    return len(rows)


# --------------------------------------------------------------------------
# Queries and health
# --------------------------------------------------------------------------
def members_on(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    """Index members as of `day`. This is the only sanctioned way to ask."""
    return list(
        conn.execute(
            """
            SELECT ticker, cik, start_date, end_date
              FROM universe
             WHERE start_date <= ?
               AND (end_date IS NULL OR end_date > ?)
             ORDER BY ticker
            """,
            (day.isoformat(), day.isoformat()),
        )
    )


def membership_health(memberships: list[Membership]) -> dict[int, int]:
    """Members on the first trading-ish day of each study year.

    The index holds ~500 names. Any year far below that is measuring the gaps in
    Wikipedia's change history, and belongs in the limitations section.
    """
    out: dict[int, int] = {}
    for year in range(config.STUDY_START.year, config.STUDY_END.year + 1):
        probe = date(year, 6, 30)
        out[year] = sum(1 for m in memberships if m.contains(probe))
    return out
