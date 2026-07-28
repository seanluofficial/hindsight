# Deviations from the pre-registration

Append-only. Each entry: date, what changed, why, and what it affects.

The pre-registration is LOCKED. Entries here are either (a) choices the pre-registration
left open, recorded so they are not silently made twice, or (b) genuine departures, which
require a reason. Nothing in this file overrides `PREREGISTRATION.md`.

---

## 2026-07-27 — Phase 1 foundation

### D1. Price vendor: Tiingo (open choice, not a departure)

§3 fixes the universe but names no price vendor. Chose Tiingo over yfinance because it
continues to serve history for delisted and acquired tickers. yfinance commonly returns
empty for those, which would silently reintroduce survivorship bias (invariant 2) in the
exact population that matters — the companies that did badly enough to leave the index.

Cost: Tiingo's free tier caps unique symbols per month, and the full 2010–2024 universe is
~886 membership intervals across ~800 distinct tickers. The full historical run in Phase 5
will need a paid tier or several months of free-tier quota. Price ingest is resumable so
this can be paid down incrementally.

### D2. Point-in-time universe: Wikipedia reconstruction, frozen to CSV (open choice)

§3 requires point-in-time membership and forbids current-constituent lists, but names no
source. Membership is reconstructed by walking Wikipedia's index-change table backwards
from today's constituents, then **frozen** to `data/sp500_membership.csv`, which is
committed. Ingest reads only the frozen file, never the live page — Wikipedia is edited
continuously and invariant 4 requires reruns to reproduce.

Known limitation, to be reported in the writeup: the source table is titled *selected*
changes and is not guaranteed complete. Measured health, members on 30 June of each study
year (a real S&P 500 carries ~503 securities including multiple share classes):

| 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 |
|------|------|------|------|------|------|------|------|
| 506  | 504  | 504  | 503  | 501  | 503  | 506  | 506  |

| 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|------|------|------|------|------|------|------|
| 506  | 506  | 506  | 506  | 504  | 504  | 504  |

Reconstruction also logged 19 additions with no matching removal and 5 removals of names
already believed open — both are gaps in the source table, counted in the run manifest
rather than hidden.

### D3. 8-K amendments (8-K/A) are excluded

§3 says "All 8-K filings". Ingest keeps form type exactly `8-K` and excludes `8-K/A`.
An amendment restates an event already ingested; treating it as a new event would
double-count the same news and put two correlated positions on one disclosure.

**Revisit if:** the amendment rate turns out to be material, or amendments carry
substantively new information rather than exhibit corrections.

### D4. CIK resolution is incomplete; company-name fallback added

Wikipedia supplies CIKs only for current constituents, and SEC's `company_tickers.json`
covers only current registrants. 228 of 886 membership intervals have no CIK — again
concentrated among delisted companies.

Rather than drop them, `UniverseMatcher` falls back to matching normalized company names
from `master.idx`, and only accepts a name match when it is unambiguous. Every match
records how it was made (`universe_match_by_cik` / `universe_match_by_name`), so the
reliance on the weaker key is measurable rather than assumed.

### D6. Duplicate index rows are collapsed, preferring the index member

`master.idx` lists one row per registrant, so a filing with co-registrants (typically an
operating company plus a financing subsidiary) appears more than once — 1,748 such rows in
2018. These are collapsed to one row per accession before ingest.

The collapse is **universe-aware, not first-wins**. Co-registrants are frequently a
non-member financing entity listed *ahead* of the member operating company, so taking the
first row silently discarded 79 in-universe filings in 2018. A row matching the universe
now always beats one that does not; among equals the first wins, and `master.idx` is
ordered, so the outcome is deterministic (invariant 4).

Verified for 2018: no accession resolves to two different in-universe tickers, so
preferring a member never overwrites another company's claim on the same event.

### D7. Eight 2018 filings have no acceptance timestamp and are excluded

EDGAR emits an empty `<ACCEPTANCE-DATETIME>` tag for 8 of 6,835 in-universe 2018 filings
(0.12%), among them Equifax `0000033185-18-000035`. Without an acceptance time there is no
defensible event timestamp under §4, so they are excluded and counted under
`header_fetch_or_parse_failed`.

The parser is anchored to the same line: with a permissive `\s*` the match would run past
the newline and adopt the *next* field's digits, inventing a timestamp that nothing
downstream would flag. Failing loudly is the correct behaviour.

**Recoverable if the rate grows:** the submissions API carries `acceptanceDateTime` for
these filings. Not worth a second metadata path for 8 records; revisit if the full
2010–2024 run shows a materially higher rate.

### D5. Files added beyond the CLAUDE.md tree

`src/hindsight/manifest.py` (run provenance and exclusion accounting, required by
invariant 5), `src/hindsight/trading_calendar.py` (NYSE session arithmetic), and
`src/hindsight/ingest/http.py` (rate limiting and the on-disk fetch cache). These are
supporting utilities, not new pipeline stages; the four stages remain separate and still
communicate only through SQLite.

Run manifests are written to `data/manifests/*.json` rather than a sixth table, because
CLAUDE.md fixes the schema at five tables.

---

## Open questions, not yet resolved

### Q1. §4 entry timing for the at/after-16:00 case — **blocks Phase 4, not Phase 1**

§4 states: "If acceptance is at or after 16:00 ET, or on a non-trading day, the position is
entered at the open of the next trading day following." CLAUDE.md's test spec sharpens it:
"at 16:01 ET it enters the open after that."

Read literally — entry is the first session strictly after the *calendar day following*
acceptance — this gives sensible answers for the cases CLAUDE.md calls out:

- Mon 16:01 → Wed open (Tuesday's open is skipped)
- Fri 16:01 → Mon open
- Sat, any time → Mon open

but an odd one it does not:

- **Sun, any time → Tue open**, skipping an available Monday open for no informational reason.

The alternative reading — entry is simply the next session after acceptance — makes Sunday
behave, but then Mon 16:01 enters Tuesday, contradicting "the open after that".

`trading_calendar.py` deliberately stops at session arithmetic and does **not** implement
`entry_date_for()`. The rule must be pinned down before Phase 4, since it moves every
entry price in the study. Resolution belongs here as a dated entry.
