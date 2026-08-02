"""Identifier stripping, and the verification that makes it enforceable.

This module is the experiment. The whole question is whether a model can read a filing it
cannot attribute, so anything that leaks the issuer's identity converts the study from
"can it forecast?" into "does it remember?". PREREGISTRATION §6 lists what must go:
company and former names, tickers, executives, addresses, CIK and file numbers, explicit
dates, auditors, exchanges, transfer agents.

Two ideas hold the design together.

**Redaction and verification are separate.** `anonymize()` removes what it can find;
`find_leaks()` then re-reads the output hunting for identifiers it knows should be gone.
A redactor that silently misses something is indistinguishable from one that works, so
the check has to be independent of the removal.

**Refusal is structural, not procedural.** `assert_anonymized()` raises unless the text
carries the current `ANON_VERSION` and survives a leak scan. Invariant 3 says the scorer
refuses un-anonymized text; a comment saying "remember to anonymize" is not a refusal.

Dates get special handling. §6 replaces them with relative language rather than deleting
them, because "the quarter ended [DATE]" still reads as a sentence while a hole does not —
and a model that sees the date can date the filing, which is most of the way to
identifying it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ANON_VERSION = "anon-v1"

# Placeholders are bracketed and uppercase so they are unmistakable in the output and easy
# to assert on in tests.
COMPANY = "[COMPANY]"
TICKER = "[TICKER]"
PERSON = "[PERSON]"
DATE = "[DATE]"
ADDRESS = "[ADDRESS]"
PHONE = "[PHONE]"
EXCHANGE = "[EXCHANGE]"
AUDITOR = "[AUDITOR]"
IDNUM = "[ID]"
STATE = "[STATE]"
MONEY_DATE = "[PERIOD]"

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
# Stripped when building name variants: they carry no identifying signal on their own and
# blocking them would redact ordinary prose ("the company said").
_CORPORATE_SUFFIXES = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "COMPANIES",
    "LTD",
    "LIMITED",
    "PLC",
    "LP",
    "LLP",
    "LLC",
    "HOLDING",
    "HOLDINGS",
    "GROUP",
    "THE",
    "AND",
    "OF",
    "TRUST",
    "PARTNERS",
    "PARTNERSHIP",
    "SA",
    "NV",
    "AG",
    "CLASS",
    "COM",
    "NEW",
    "INTERNATIONAL",
    "INDUSTRIES",
    "ENTERPRISES",
}

# Tokens too generic to redact even when they appear in a company name. Blanking "GENERAL"
# out of General Electric filings would also blank "general and administrative expenses".
_UNSAFE_TO_REDACT = {
    "GENERAL",
    "AMERICAN",
    "NATIONAL",
    "UNITED",
    "FIRST",
    "GLOBAL",
    "PACIFIC",
    "ATLANTIC",
    "STANDARD",
    "UNIVERSAL",
    "CENTRAL",
    "SOUTHERN",
    "NORTHERN",
    "EASTERN",
    "WESTERN",
    "PUBLIC",
    "SERVICE",
    "SERVICES",
    "SYSTEMS",
    "TECHNOLOGIES",
    "TECHNOLOGY",
    "PRODUCTS",
    "RESOURCES",
    "ENERGY",
    "FINANCIAL",
    "CAPITAL",
    "BANK",
    "HEALTH",
    "MEDICAL",
    "STORES",
    "MOTORS",
    "ELECTRIC",
    "AIR",
    "STATES",
    "STATE",
    "MATERIALS",
    "SCIENTIFIC",
    "COMMUNICATIONS",
    "MANAGEMENT",
    "PROPERTIES",
    "REALTY",
}

_EXCHANGES = [
    "New York Stock Exchange",
    "NYSE American",
    "NYSE Arca",
    "NYSE",
    "NASDAQ Global Select Market",
    "NASDAQ Global Market",
    "NASDAQ Capital Market",
    "The NASDAQ Stock Market",
    "NASDAQ",
    "Nasdaq",
    "Chicago Board Options Exchange",
    "Cboe",
    "BATS",
    "OTC Markets",
    "Toronto Stock Exchange",
]

_AUDITORS = [
    "PricewaterhouseCoopers",
    "PwC",
    "Deloitte & Touche",
    "Deloitte",
    "Ernst & Young",
    "EY LLP",
    "KPMG",
    "Grant Thornton",
    "BDO USA",
    "BDO Seidman",
    "RSM US",
    "Crowe LLP",
    "Moss Adams",
    "Marcum LLP",
]

_TRANSFER_AGENTS = [
    "Computershare",
    "American Stock Transfer",
    "Equiniti",
    "Broadridge",
    "Continental Stock Transfer",
    "Wells Fargo Shareowner Services",
    "EQ Shareowner",
]

_US_STATES = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
    "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------
_RE_DATE_LONG = re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I)
_RE_DATE_MONTH_YEAR = re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{4}}\b", re.I)
_RE_DATE_DMY = re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+\d{{4}}\b", re.I)
_RE_DATE_NUMERIC = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_RE_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_RE_YEAR = re.compile(r"\b(?:19[5-9]\d|20[0-4]\d)\b")
_RE_QUARTER = re.compile(
    r"\b(?:Q[1-4]|first|second|third|fourth)\s+quarter\s+(?:of\s+)?\d{4}\b", re.I
)
_RE_FISCAL = re.compile(r"\b(?:fiscal|calendar)\s+(?:year\s+)?\d{4}\b", re.I)

_RE_PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
_RE_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_RE_CIK = re.compile(r"\b(?:CIK|Central Index Key)[\s:#]*0*\d{4,10}\b", re.I)
_RE_FILE_NO = re.compile(
    r"\b(?:Commission File(?:\s+Number)?|File No\.?|IRS Employer)[\s:#]*[\w\-]+", re.I
)
_RE_IRS = re.compile(r"\b\d{2}-\d{7}\b")
# Street numbers are sometimes spelled out — Apple's "One Apple Park Way", Netflix's
# "100 Winchester Circle". Both forms must go: a headquarters address names the issuer
# as surely as the issuer's name does.
_STREET_NUMBER = r"(?:\d{1,6}|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)"
_STREET_TYPE = (
    r"Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Plaza|Parkway|Pkwy"
    r"|Court|Ct|Circle|Cir|Square|Sq|Center|Centre|Highway|Hwy|Terrace|Place|Pl"
)
_RE_STREET = re.compile(
    rf"\b{_STREET_NUMBER}\s+(?:[A-Z][\w.'-]+\s+){{0,4}}(?:{_STREET_TYPE})\b\.?", re.I
)
# Two-letter state codes. Only matched after a comma ("Voorhees, NJ"), never bare: IN, OR,
# ME, OK, HI, AS, MS and DE are all ordinary English words or abbreviations, and redacting
# them everywhere would shred the prose.
_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|"
    "NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
# "Los Gatos, California" and "Voorhees, NJ" both identify the issuer as surely as its
# name does. Runs after full state names are replaced, so it anchors on either form.
_RE_CITY_STATE = re.compile(
    rf"\b[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){{0,2}},\s*(?:{re.escape(STATE)}|(?:{_STATE_CODES})\b\.?)"
)
_RE_DC = re.compile(r"\bD\.?\s?C\.?(?=[\s,.]|$)")

# Document filenames leak badly: EDGAR primary documents are routinely named
# "aapl-20180201.htm", carrying both the ticker and the date in one token.
_RE_FILENAME = re.compile(
    r"\b[\w][\w.\-]{2,}\.(?:htm|html|txt|pdf|jpe?g|png|gif|xlsx?|zip)\b", re.I
)
_RE_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+", re.I)
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

# Signature blocks: "/s/ Jane Q. Smith"
_RE_SIGNATURE = re.compile(r"/s/\s*[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3}")
# Honorific + name
_RE_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2}"
)
# "Jane Smith, Chief Executive Officer" / "Jane Smith, our President"
_TITLES = (
    r"Chief\s+\w+\s+Officer|President|Chairman|Chairwoman|Chairperson|Chair|"
    r"Vice\s+President|Executive\s+Vice\s+President|Senior\s+Vice\s+President|"
    r"Chief\s+Executive|Chief\s+Financial|Chief\s+Operating|CEO|CFO|COO|CTO|"
    r"Treasurer|Secretary|General\s+Counsel|Controller|Director|Trustee"
)
_RE_NAME_THEN_TITLE = re.compile(
    rf"\b[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z'\-]+){{1,2}}\s*,\s*(?:our\s+|the\s+)?(?:{_TITLES})\b"
)
_RE_TITLE_THEN_NAME = re.compile(
    rf"\b(?:{_TITLES})\s*,?\s+[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z'\-]+){{1,2}}\b"
)

_RE_WS = re.compile(r"[ \t]{2,}")
_RE_PLACEHOLDER_RUN = re.compile(r"(?:\[(?:COMPANY|PERSON|DATE|ADDRESS|ID)\][\s,]*){2,}")


@dataclass
class AnonymizationResult:
    """Anonymized text plus everything needed to audit the redaction."""

    text: str
    version: str = ANON_VERSION
    replacements: dict[str, int] = field(default_factory=dict)
    leaks: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.leaks

    @property
    def total_replacements(self) -> int:
        return sum(self.replacements.values())


# --------------------------------------------------------------------------
# Identifier expansion
# --------------------------------------------------------------------------
def name_variants(company_name: str) -> list[str]:
    """Surface forms of a company name worth redacting, longest first.

    "Wells Fargo & Company" yields the full string, "Wells Fargo", and "Wells" — but not
    "Company". Generic tokens are dropped so redaction cannot eat ordinary prose.
    """
    cleaned = re.sub(r"[^\w\s&/-]", " ", company_name or "").strip()
    if not cleaned:
        return []

    variants: set[str] = {cleaned}

    tokens = [t for t in re.split(r"\s+", cleaned) if t]
    meaningful = [t for t in tokens if t.upper().strip(".,&") not in _CORPORATE_SUFFIXES]
    if meaningful:
        variants.add(" ".join(meaningful))
        # Leading bigram catches "Wells Fargo" inside "Wells Fargo Bank, N.A."
        if len(meaningful) >= 2:
            variants.add(" ".join(meaningful[:2]))
        head = meaningful[0]
        if len(head) >= 4 and head.upper() not in _UNSAFE_TO_REDACT:
            variants.add(head)

    return sorted({v.strip() for v in variants if len(v.strip()) >= 3}, key=len, reverse=True)


def _sub_count(
    pattern: re.Pattern[str], repl: str, text: str, counter: dict[str, int], key: str
) -> str:
    out, n = pattern.subn(repl, text)
    if n:
        counter[key] = counter.get(key, 0) + n
    return out


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------
def anonymize(
    text: str,
    company_name: str = "",
    ticker: str = "",
    cik: int | None = None,
    former_names: list[str] | None = None,
) -> AnonymizationResult:
    """Strip identifiers per §6 and verify the result."""
    counts: dict[str, int] = {}
    out = text

    # Order matters. Structured identifiers (URLs, emails, addresses) go first, because
    # they often *contain* the company name and would otherwise be left half-redacted.
    out = _sub_count(_RE_URL, IDNUM, out, counts, "url")
    out = _sub_count(_RE_EMAIL, IDNUM, out, counts, "email")
    out = _sub_count(_RE_FILENAME, IDNUM, out, counts, "filename")
    out = _sub_count(_RE_CIK, IDNUM, out, counts, "cik_label")
    out = _sub_count(_RE_FILE_NO, IDNUM, out, counts, "file_number")
    out = _sub_count(_RE_IRS, IDNUM, out, counts, "irs_number")
    out = _sub_count(_RE_STREET, ADDRESS, out, counts, "street")
    out = _sub_count(_RE_PHONE, PHONE, out, counts, "phone")

    # Names, longest variant first so "Wells Fargo & Company" is consumed before "Wells".
    all_names = list(former_names or []) + ([company_name] if company_name else [])
    variants: list[str] = []
    for name in all_names:
        variants.extend(name_variants(name))
    for variant in sorted(set(variants), key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(variant)}\b", re.I)
        out = _sub_count(pattern, COMPANY, out, counts, "company_name")

    if ticker:
        # Bare symbol, and the common "(NYSE: XYZ)" construction.
        out = _sub_count(
            re.compile(rf"\b(?:NYSE|NASDAQ|Nasdaq|AMEX)\s*:\s*{re.escape(ticker)}\b"),
            TICKER,
            out,
            counts,
            "ticker_with_exchange",
        )
        out = _sub_count(re.compile(rf"\b{re.escape(ticker)}\b"), TICKER, out, counts, "ticker")

    if cik is not None:
        out = _sub_count(re.compile(rf"\b0*{cik}\b"), IDNUM, out, counts, "cik_number")

    # People
    out = _sub_count(_RE_SIGNATURE, f"/s/ {PERSON}", out, counts, "signature")
    out = _sub_count(_RE_HONORIFIC, PERSON, out, counts, "honorific_name")
    out = _sub_count(_RE_NAME_THEN_TITLE, f"{PERSON}, [TITLE]", out, counts, "name_then_title")
    out = _sub_count(_RE_TITLE_THEN_NAME, f"[TITLE] {PERSON}", out, counts, "title_then_name")

    # Institutions
    for phrase in _EXCHANGES:
        out = _sub_count(re.compile(rf"\b{re.escape(phrase)}\b"), EXCHANGE, out, counts, "exchange")
    for phrase in _AUDITORS + _TRANSFER_AGENTS:
        out = _sub_count(
            re.compile(rf"\b{re.escape(phrase)}\b", re.I), AUDITOR, out, counts, "auditor"
        )
    for state in _US_STATES:
        out = _sub_count(re.compile(rf"\b{re.escape(state)}\b"), STATE, out, counts, "state")
    # D.C. first: the city pass anchors on a state placeholder or code, and "D.C." with
    # its dots matches neither. Leaving it until afterwards stranded the SEC's own
    # "WASHINGTON, D.C." boilerplate as a permanent false-positive leak on every filing.
    out = _sub_count(_RE_DC, STATE, out, counts, "dc")
    # Cities anchor on the state that follows them, so this must run after state names.
    out = _sub_count(_RE_CITY_STATE, f"{ADDRESS}, {STATE}", out, counts, "city_state")

    # Dates last: earlier passes may have already removed the text around them, and
    # replacing dates first would leave placeholders that confuse the address patterns.
    out = _sub_count(_RE_QUARTER, "the relevant quarter", out, counts, "quarter")
    out = _sub_count(_RE_FISCAL, "the relevant fiscal year", out, counts, "fiscal_year")
    out = _sub_count(_RE_DATE_LONG, DATE, out, counts, "date_long")
    out = _sub_count(_RE_DATE_DMY, DATE, out, counts, "date_dmy")
    out = _sub_count(_RE_DATE_MONTH_YEAR, MONEY_DATE, out, counts, "date_month_year")
    out = _sub_count(_RE_DATE_NUMERIC, DATE, out, counts, "date_numeric")
    out = _sub_count(_RE_DATE_ISO, DATE, out, counts, "date_iso")
    out = _sub_count(_RE_ZIP, IDNUM, out, counts, "zip")
    # Bare years go last so they cannot eat the year out of a full date first.
    out = _sub_count(_RE_YEAR, MONEY_DATE, out, counts, "bare_year")

    out = _RE_PLACEHOLDER_RUN.sub(lambda m: m.group(0).split("]")[0] + "] ", out)
    out = _RE_WS.sub(" ", out)

    result = AnonymizationResult(text=out.strip(), replacements=counts)
    result.leaks = find_leaks(result.text, company_name, ticker, cik, former_names)
    return result


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
def find_leaks(
    text: str,
    company_name: str = "",
    ticker: str = "",
    cik: int | None = None,
    former_names: list[str] | None = None,
) -> list[str]:
    """Identifiers still present after redaction.

    Deliberately independent of `anonymize()`: it re-derives what should be gone rather
    than trusting the redactor's own bookkeeping. A redactor that quietly misses a name
    would otherwise look identical to one that works.
    """
    leaks: list[str] = []
    haystack = text.lower()

    for name in list(former_names or []) + ([company_name] if company_name else []):
        for variant in name_variants(name):
            if re.search(rf"\b{re.escape(variant.lower())}\b", haystack):
                leaks.append(f"company_name:{variant}")

    if ticker and re.search(rf"\b{re.escape(ticker)}\b", text):
        leaks.append(f"ticker:{ticker}")

    if cik is not None and re.search(rf"\b0*{cik}\b", text):
        leaks.append(f"cik:{cik}")

    for pattern, label in (
        (_RE_DATE_LONG, "date"),
        (_RE_DATE_DMY, "date"),
        (_RE_DATE_NUMERIC, "date"),
        (_RE_DATE_ISO, "date"),
        (_RE_YEAR, "year"),
        (_RE_EMAIL, "email"),
        (_RE_URL, "url"),
        # Added after a hand inspection found all three surviving in real filings —
        # "Voorhees, NJ" and "form8-kxearningsguidance.htm" both name the issuer.
        (_RE_CITY_STATE, "city_state"),
        (_RE_FILENAME, "filename"),
        (_RE_STREET, "street"),
    ):
        found = pattern.search(text)
        if found:
            leaks.append(f"{label}:{found.group(0)[:40]}")

    return sorted(set(leaks))


class NotAnonymizedError(RuntimeError):
    """Raised when text would reach the model without passing anonymization."""


def assert_anonymized(text: str, anon_version: str | None) -> None:
    """Gate every outbound call. Invariant 3: the scorer *refuses*, it does not warn.

    Checks the stamped version and re-runs the identifier-shaped leak scan, so text that
    was anonymized by an older, weaker version is rejected rather than trusted.
    """
    if anon_version != ANON_VERSION:
        raise NotAnonymizedError(
            f"text carries anon_version={anon_version!r}, expected {ANON_VERSION!r}. "
            "Re-run the anonymizer before scoring."
        )
    residual = find_leaks(text)
    if residual:
        raise NotAnonymizedError(
            f"anonymized text still contains identifier-shaped content: {residual[:5]}"
        )
