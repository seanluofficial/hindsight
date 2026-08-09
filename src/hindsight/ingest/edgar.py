"""EDGAR ingest: discover 8-K filings, resolve their acceptance timestamps, extract text.

Discovery uses the quarterly full index (`master.idx`) rather than the per-company
submissions API. The full index is a point-in-time artifact that lists what was actually
disseminated in that quarter, and it does not depend on a company still existing today —
which matters for exactly the delisted names invariant 2 is about.

The acceptance timestamp is the whole ballgame (PREREGISTRATION §4), and it is *not* in
master.idx. It comes from each filing's `-index-headers.html`, where it is recorded as
`<ACCEPTANCE-DATETIME>20180201163017`. That value is **America/New_York**, not UTC —
verified against the submissions API, which reports the same filing as 21:30:17Z. Reading
it as UTC would shift every event five hours and silently break the 16:00 cutoff, so the
conversion happens once, here, and everything downstream is UTC.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from hindsight import config
from hindsight.ingest.http import CachedFetcher
from hindsight.ingest.universe import Membership
from hindsight.manifest import RunManifest

log = logging.getLogger(__name__)

FORM_TYPE = "8-K"
EXTRACTED_DIR = config.RAW_DIR / "extracted"

# Exhibit types worth reading. EX-99 is where the press release lives; the 8-K body itself
# is often a two-line pointer to it.
_WANTED_DOC_TYPES = re.compile(r"^(8-K|EX-99(\.\d+)?)$", re.IGNORECASE)

# Anchored to the same line on purpose. EDGAR occasionally emits an empty
# <ACCEPTANCE-DATETIME> tag; with `\s*` the match would run past the newline and could
# pick up digits from the *next* field, silently inventing a timestamp. Failing loudly
# and counting the filing as an exclusion is the correct outcome.
_ACCEPTANCE_RE = re.compile(r"<ACCEPTANCE-DATETIME>[ \t]*(\d{14})")
_PERIOD_RE = re.compile(r"<PERIOD>\s*(\d{8})")
_ITEMS_RE = re.compile(r"<ITEMS>\s*([^\r\n<]+)")

# Older submissions spell items out instead of numbering them: the complete submission text
# carries `ITEM INFORMATION: Other Events` where recent filings carry `<ITEMS>8.01`. Without
# this mapping every pre-2014 filing collapses into the "other" bucket, which would corrupt
# both the §12 item-type robustness split and the sampling strata built on it.
_ITEM_INFORMATION_RE = re.compile(r"ITEM INFORMATION:\s*([^\r\n]+)")
_ITEM_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("results of operations", "2.02"),
    ("departure of directors", "5.02"),
    ("election of directors", "5.02"),
    ("appointment of certain officers", "5.02"),
    ("entry into a material definitive agreement", "1.01"),
    ("termination of a material definitive agreement", "1.02"),
    ("bankruptcy or receivership", "1.03"),
    ("completion of acquisition", "2.01"),
    ("creation of a direct financial obligation", "2.03"),
    ("triggering events", "2.04"),
    ("costs associated with exit", "2.05"),
    ("material impairments", "2.06"),
    ("notice of delisting", "3.01"),
    ("unregistered sales", "3.02"),
    ("material modification to rights", "3.03"),
    ("changes in registrant", "4.01"),
    ("non-reliance", "4.02"),
    ("changes in control", "5.01"),
    ("amendments to articles", "5.03"),
    ("temporary suspension of trading", "5.04"),
    ("amendment to registrant", "5.05"),
    ("submission of matters to a vote", "5.07"),
    ("shareholder director nominations", "5.08"),
    ("regulation fd", "7.01"),
    ("financial statements and exhibits", "9.01"),
    # Last: "other events" would otherwise shadow more specific phrases.
    ("other events", "8.01"),
)


def item_codes_from_descriptions(header: str) -> list[str]:
    """Map spelled-out `ITEM INFORMATION:` lines back to their numeric 8-K codes."""
    codes: set[str] = set()
    for description in _ITEM_INFORMATION_RE.findall(header):
        lowered = description.strip().lower()
        for phrase, code in _ITEM_DESCRIPTIONS:
            if phrase in lowered:
                codes.add(code)
                break
    return sorted(codes)


_DOCUMENT_RE = re.compile(r"<DOCUMENT>(.*?)(?=<DOCUMENT>|</SEC-DOCUMENT>|\Z)", re.S)
_FIELD_RE = re.compile(r"<(TYPE|SEQUENCE|FILENAME|DESCRIPTION)>([^\r\n<]*)")

_WS_RE = re.compile(r"[ \t ]+")
_BLANKLINE_RE = re.compile(r"\n{3,}")

# Corporate-form noise that carries no identifying signal, stripped before name matching.
_NAME_NOISE = re.compile(
    r"\b(INC|CORP|CORPORATION|COMPANY|CO|LTD|LIMITED|PLC|LP|LLC|HOLDINGS?|GROUP|"
    r"INTERNATIONAL|THE|NEW|CLASS\s+[A-C]|COM|SA|NV|AG)\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class IndexRow:
    """One line of master.idx."""

    cik: int
    company_name: str
    form_type: str
    date_filed: date
    filename: str

    @property
    def accession_no(self) -> str:
        return Path(self.filename).stem


@dataclass(frozen=True)
class FilingDocument:
    doc_type: str
    sequence: str
    filename: str
    description: str


@dataclass(frozen=True)
class FilingMetadata:
    accession_no: str
    cik: int
    accepted_at_et: datetime
    accepted_at_utc: datetime
    period_of_report: str | None
    item_codes: str
    documents: tuple[FilingDocument, ...]


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def quarter_index_url(year: int, quarter: int) -> str:
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    return f"{config.EDGAR_FULL_INDEX}/{year}/QTR{quarter}/master.idx"


def parse_master_index(text: str, form_type: str = FORM_TYPE) -> list[IndexRow]:
    """Parse master.idx, keeping only exact `form_type` matches.

    The filter is exact on purpose: '8-K/A' is an amendment of an already-ingested event,
    and treating it as a new event would double-count the same news.
    """
    rows: list[IndexRow] = []
    for line in text.splitlines():
        if line.count("|") != 4:
            continue
        cik_s, name, form, filed_s, filename = line.split("|")
        if form.strip() != form_type:
            continue
        try:
            cik = int(cik_s)
            filed = datetime.strptime(filed_s.strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        rows.append(IndexRow(cik, name.strip(), form.strip(), filed, filename.strip()))
    return rows


def crawl_quarter(
    year: int, quarter: int, fetcher: CachedFetcher, manifest: RunManifest | None = None
) -> list[IndexRow]:
    text = fetcher.get_text(quarter_index_url(year, quarter))
    rows = parse_master_index(text)
    if manifest:
        manifest.count("index_8k_rows", len(rows))
    return rows


def deduplicate_index_rows(
    rows: list[IndexRow], matcher: UniverseMatcher, manifest: RunManifest | None = None
) -> list[IndexRow]:
    """Collapse accessions that master.idx lists more than once, preferring index members.

    A filing with co-registrants (a parent and its financing subsidiary, say) gets one
    index row per registrant; 2018 has 1,748 such rows. Collapsing them stops the same 8-K
    being fetched and written repeatedly — harmless for the data, since accession_no is the
    primary key, but it inflates `filings_written` above the row count and burns
    rate-limit budget.

    **Order matters, so this cannot be a plain first-wins collapse.** Co-registrants are
    frequently a non-member financing entity listed ahead of the member operating company.
    Taking the first row would silently discard 79 in-universe filings in 2018 alone. So a
    row that matches the universe always beats one that does not; among equals, the first
    wins, and master.idx is ordered, so the result is deterministic.

    Verified for 2018: no accession resolves to two different tickers, so preferring a
    member never overwrites another company's claim on the same event.
    """
    chosen: dict[str, IndexRow] = {}
    chosen_is_member: dict[str, bool] = {}
    duplicates = 0

    for row in rows:
        is_member = matcher.match(row.cik, row.company_name, row.date_filed)[0] is not None
        previous = chosen.get(row.accession_no)
        if previous is None:
            chosen[row.accession_no] = row
            chosen_is_member[row.accession_no] = is_member
            continue
        duplicates += 1
        if is_member and not chosen_is_member[row.accession_no]:
            chosen[row.accession_no] = row
            chosen_is_member[row.accession_no] = True

    if manifest and duplicates:
        manifest.count("duplicate_index_rows_collapsed", duplicates)
    return list(chosen.values())


# --------------------------------------------------------------------------
# Universe matching
# --------------------------------------------------------------------------
def normalize_company_name(name: str) -> str:
    """Collapse a company name to a comparable key."""
    stripped = _NAME_NOISE.sub(" ", name.upper())
    return _NON_ALNUM.sub("", stripped)


class UniverseMatcher:
    """Maps a filing (CIK, name, date) to the ticker that was in the index that day.

    CIK is the reliable key. Name is a fallback for members whose CIK never resolved —
    those are disproportionately delisted companies, so dropping them would quietly
    reintroduce the survivorship bias the CIK lookup was meant to avoid.
    """

    def __init__(self, memberships: list[Membership]) -> None:
        self.by_cik: dict[int, list[Membership]] = {}
        self.by_name: dict[str, list[Membership]] = {}
        for m in memberships:
            if m.cik is not None:
                self.by_cik.setdefault(m.cik, []).append(m)
            if m.name:
                key = normalize_company_name(m.name)
                if key:
                    self.by_name.setdefault(key, []).append(m)

    def match(self, cik: int, company_name: str, day: date) -> tuple[str | None, str]:
        """Return (ticker, how) where `how` is 'cik', 'name', or 'none'."""
        for m in self.by_cik.get(cik, []):
            if m.contains(day):
                return m.ticker, "cik"
        key = normalize_company_name(company_name)
        candidates = self.by_name.get(key, [])
        # Only trust a name match when it is unambiguous.
        hits = [m for m in candidates if m.contains(day)]
        if len(hits) == 1:
            return hits[0].ticker, "name"
        return None, "none"


# --------------------------------------------------------------------------
# Per-filing metadata
# --------------------------------------------------------------------------
def filing_dir_url(cik: int, accession_no: str) -> str:
    return f"{config.EDGAR_ARCHIVES}/edgar/data/{cik}/{accession_no.replace('-', '')}"


def headers_url(cik: int, accession_no: str) -> str:
    return f"{filing_dir_url(cik, accession_no)}/{accession_no}-index-headers.html"


def parse_filing_headers(html: str, accession_no: str, cik: int) -> FilingMetadata:
    """Pull acceptance time, period, item codes, and the document list out of the header.

    The header is SGML embedded in HTML, so the angle brackets arrive escaped.
    """
    text = html.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    match = _ACCEPTANCE_RE.search(text)
    if not match:
        raise ValueError(f"no ACCEPTANCE-DATETIME in headers for {accession_no}")

    # EDGAR records this in Eastern time. Attaching the zone (rather than converting from
    # UTC) is what makes the §4 16:00 ET cutoff mean what it says, across DST.
    naive = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    accepted_et = naive.replace(tzinfo=config.MARKET_TZ)
    accepted_utc = accepted_et.astimezone(config.UTC)

    period_match = _PERIOD_RE.search(text)
    period = None
    if period_match:
        try:
            period = datetime.strptime(period_match.group(1), "%Y%m%d").date().isoformat()
        except ValueError:
            period = None

    items = sorted({i.strip() for i in _ITEMS_RE.findall(text) if i.strip()})
    if not items:
        # Older filings spell the items out rather than numbering them.
        items = item_codes_from_descriptions(text)

    documents: list[FilingDocument] = []
    for block in _DOCUMENT_RE.finditer(text):
        fields = dict(_FIELD_RE.findall(block.group(1)))
        doc_type = fields.get("TYPE", "").strip()
        filename = fields.get("FILENAME", "").strip()
        if doc_type and filename:
            documents.append(
                FilingDocument(
                    doc_type=doc_type,
                    sequence=fields.get("SEQUENCE", "").strip(),
                    filename=filename,
                    description=fields.get("DESCRIPTION", "").strip(),
                )
            )

    return FilingMetadata(
        accession_no=accession_no,
        cik=cik,
        accepted_at_et=accepted_et,
        accepted_at_utc=accepted_utc,
        period_of_report=period,
        item_codes=",".join(items),
        documents=tuple(documents),
    )


_RE_CONFORMED_NAME = re.compile(r"COMPANY CONFORMED NAME:\s*([^\r\n<]+)", re.I)
_RE_FORMER_NAME = re.compile(r"FORMER CONFORMED NAME:\s*([^\r\n<]+)", re.I)


def parse_company_names(html: str) -> tuple[str, list[str]]:
    """(current name, former names) from a filing header.

    Former names matter as much as current ones for anonymization: "Apple Computer Inc"
    identifies the issuer exactly as well as "Apple Inc" does, and §6 requires both to go.
    """
    text = html.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    current = _RE_CONFORMED_NAME.search(text)
    formers = [m.strip() for m in _RE_FORMER_NAME.findall(text) if m.strip()]
    return (current.group(1).strip() if current else ""), sorted(set(formers))


def fetch_company_names(
    cik: int, accession_no: str, fetcher: CachedFetcher
) -> tuple[str, list[str]]:
    """Names for one filing, from whichever metadata source exists.

    Prefers the complete submission, which exists for every filing. `-index-headers.html`
    is only generated for recent ones and 404s across 2010-2013, so relying on it alone
    left older filings with no company name and therefore nothing to redact.
    """
    try:
        return parse_company_names(fetcher.get_text(submission_url(cik, accession_no)))
    except Exception:  # noqa: BLE001
        return parse_company_names(fetcher.get_text(headers_url(cik, accession_no)))


def submission_url(cik: int, accession_no: str) -> str:
    """The complete submission text file: SGML header plus every document, inline."""
    return f"{filing_dir_url(cik, accession_no)}/{accession_no}.txt"


# Inside the full submission each document is delimited and carries its text inline.
_SUBMISSION_DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
_DOC_TEXT_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.S)


def parse_submission(
    raw: str, accession_no: str, cik: int
) -> tuple[FilingMetadata, dict[str, str]]:
    """Parse a complete submission into (metadata, {filename: document text}).

    Preferred over `-index-headers.html`, which EDGAR only generates for recent filings —
    it 404s across 2010-2013 even though the directory listing claims it exists, which
    silently cost every filing in those years. The full submission has existed for every
    filing since EDGAR began, and carries the header and the documents together, so one
    request replaces the header fetch plus one fetch per exhibit.
    """
    meta = parse_filing_headers(raw, accession_no, cik)

    bodies: dict[str, str] = {}
    for block in _SUBMISSION_DOC_RE.finditer(raw):
        chunk = block.group(1)
        fields = dict(_FIELD_RE.findall(chunk))
        filename = fields.get("FILENAME", "").strip()
        text_match = _DOC_TEXT_RE.search(chunk)
        if filename and text_match:
            bodies[filename] = text_match.group(1)
    return meta, bodies


def fetch_submission(
    cik: int, accession_no: str, fetcher: CachedFetcher
) -> tuple[FilingMetadata, dict[str, str]]:
    return parse_submission(fetcher.get_text(submission_url(cik, accession_no)), accession_no, cik)


def fetch_filing_metadata(cik: int, accession_no: str, fetcher: CachedFetcher) -> FilingMetadata:
    html = fetcher.get_text(headers_url(cik, accession_no))
    return parse_filing_headers(html, accession_no, cik)


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------
def html_to_text(raw: str) -> str:
    """Flatten an EDGAR document to readable text.

    EDGAR HTML is machine-generated and table-heavy; `separator=' '` keeps words from
    fusing across tags ("NetSales" for "Net</td><td>Sales").
    """
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKLINE_RE.sub("\n\n", text).strip()


def extract_from_submission(meta: FilingMetadata, bodies: dict[str, str]) -> str:
    """Concatenate the 8-K body and its EX-99 exhibits from an already-parsed submission.

    Same selection rules as the per-document fetch path, but the text is already in hand,
    so this costs no requests.
    """
    parts: list[str] = []
    for doc in sorted(meta.documents, key=lambda d: d.sequence or "999"):
        if not _WANTED_DOC_TYPES.match(doc.doc_type):
            continue
        raw = bodies.get(doc.filename)
        if not raw:
            continue
        looks_like_markup = "<" in raw[:2000] and doc.filename.lower().endswith((".htm", ".html"))
        body = html_to_text(raw) if looks_like_markup else raw
        if body.strip():
            parts.append(f"[{doc.doc_type}]\n{body.strip()}")
    return "\n\n".join(parts)


def extract_filing_text(
    meta: FilingMetadata, fetcher: CachedFetcher, manifest: RunManifest | None = None
) -> str:
    """Concatenate the 8-K body and its EX-99 exhibits, in filing order."""
    parts: list[str] = []
    for doc in sorted(meta.documents, key=lambda d: d.sequence or "999"):
        if not _WANTED_DOC_TYPES.match(doc.doc_type):
            continue
        if doc.filename.lower().endswith((".jpg", ".png", ".gif", ".pdf", ".xlsx", ".zip")):
            continue
        url = f"{filing_dir_url(meta.cik, meta.accession_no)}/{doc.filename}"
        try:
            raw = fetcher.get_text(url)
        except Exception as exc:  # noqa: BLE001 - one bad exhibit must not kill the crawl
            log.warning("could not fetch %s: %s", url, exc)
            if manifest:
                manifest.exclude("document_fetch_failed", f"{meta.accession_no}:{doc.filename}")
            continue
        body = html_to_text(raw) if doc.filename.lower().endswith((".htm", ".html")) else raw
        if body.strip():
            parts.append(f"[{doc.doc_type}]\n{body.strip()}")
    return "\n\n".join(parts)


def write_extracted_text(accession_no: str, text: str) -> Path:
    """Persist extracted text and return the path stored in `filings.raw_path`."""
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    path = EXTRACTED_DIR / f"{accession_no}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def relative_raw_path(path: Path) -> str:
    """Store paths relative to the repo root so the database is portable."""
    try:
        return path.resolve().relative_to(config.ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def in_acceptance_window(accepted_et: datetime) -> bool:
    """PREREGISTRATION §3: acceptance must fall in 04:00-20:00 ET."""
    low, high = config.ACCEPTANCE_WINDOW_ET
    return low <= accepted_et.timetz().replace(tzinfo=None) <= high


def ingest_quarter(
    conn: sqlite3.Connection,
    year: int,
    quarter: int,
    matcher: UniverseMatcher,
    fetcher: CachedFetcher,
    manifest: RunManifest,
    limit: int | None = None,
) -> int:
    """Ingest every in-universe 8-K for one quarter. Safe to re-run: skips stored filings."""
    rows = deduplicate_index_rows(
        crawl_quarter(year, quarter, fetcher, manifest), matcher, manifest
    )

    already = {r[0] for r in conn.execute("SELECT accession_no FROM filings")}

    written = 0
    for row in rows:
        if limit is not None and written >= limit:
            manifest.count("stopped_early_at_limit")
            break

        ticker, how = matcher.match(row.cik, row.company_name, row.date_filed)
        if ticker is None:
            manifest.exclude("not_in_universe_on_filing_date", f"{row.cik} {row.company_name}")
            continue
        manifest.count(f"universe_match_by_{how}")

        if row.accession_no in already:
            manifest.count("already_ingested_skipped")
            continue

        try:
            meta, bodies = fetch_submission(row.cik, row.accession_no, fetcher)
        except Exception as exc:  # noqa: BLE001 - record and continue; never silently drop
            manifest.exclude("submission_fetch_or_parse_failed", f"{row.accession_no}: {exc}")
            continue

        if not in_acceptance_window(meta.accepted_at_et):
            manifest.exclude(
                "acceptance_outside_0400_2000_et",
                f"{row.accession_no} @ {meta.accepted_at_et.isoformat()}",
            )
            continue

        text = extract_from_submission(meta, bodies)
        if not text.strip():
            manifest.exclude("no_extractable_text", row.accession_no)
            continue

        path = write_extracted_text(row.accession_no, text)
        conn.execute(
            """
            INSERT OR REPLACE INTO filings
                (accession_no, cik, ticker, accepted_at_utc, period_of_report,
                 item_codes, raw_path, anonymized_text, anon_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                row.accession_no,
                row.cik,
                ticker,
                meta.accepted_at_utc.isoformat(),
                meta.period_of_report,
                meta.item_codes,
                relative_raw_path(path),
            ),
        )
        written += 1
        manifest.count("filings_written")
        if written % 100 == 0:
            log.info("%d-Q%d: %d filings written", year, quarter, written)

    return written
