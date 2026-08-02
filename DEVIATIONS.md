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

## 2026-08-02 — scoring: model choice and a text cap

### D12. Scoring text is capped at 12,000 characters, for both scorers

8-K length is extremely skewed: median ~10k characters, mean ~27k, maximum ~450k. Provider
request limits reject the long tail outright (Groq returns HTTP 413), and **46% of the
pilot exceeds 12k characters**.

The alternative to truncating is excluding those filings, which would drop nearly half the
sample *non-randomly* — long filings are disproportionately earnings releases with full
financial statements attached, exactly the disclosures most likely to carry signal. That
would be a worse distortion than truncation.

So `config.MAX_SCORING_CHARS = 12_000`, applied through a single function
(`anonymize.scoring_text`) used by the lexicon, the LLM, and the contamination audit.
§8 requires the baseline to run on identical text to the model; truncating only the LLM
would turn H3 into a comparison between two different *inputs* rather than two different
*readers*. The cut lands on a whitespace boundary so the final token is a whole word.

The lexicon was re-versioned **lm-v1 → lm-v2** to mark the input change, and the result is
materially unchanged: 5-day Sharpe after 10bps moved from −1.28 (full text) to −1.42
(capped), hit rate 48.5% → 50.2%. The null is robust to the cap.

**Reported as a limitation:** 3,056 of 6,720 filings (45.5%) were truncated. Content after
12,000 characters was never seen by any scorer.

### D13. Model: `llama-3.3-70b-versatile` via Groq (open choice)

The pre-registration fixes the protocol — one pinned model, temperature 0, strict JSON —
not the vendor. Groq was chosen because its free tier allows ~1,000 requests/day, enough
to score the pilot in one run.

Rejected alternatives, with reasons, since "we used a free tier" is itself a limitation
worth disclosing:

- **Anthropic** — no free tier.
- **Gemini `gemini-2.0-flash`** — free-tier allocation of *zero* for this key.
- **Gemini `gemini-2.5-flash`** — 20 requests/day. A 500-filing pilot would take 25 days.
- **Gemini `gemini-3.5-flash`** — workable, but throughput was still the binding constraint.

Backends for Gemini and Anthropic remain implemented and selectable via `--provider`, so
the study can be re-run against a frontier model without touching the pipeline.

**Limitation to state in the writeup:** a 70B open-weights model is weaker than a frontier
model at financial reasoning, so a null result for H3 is *weaker evidence* than the same
null from a frontier model would be. It bounds what the LLM can do here, not what LLMs can
do in general.

### D14. Prompt re-versioned p1 → p1.1 for a generation-config change

The prompt text is identical. Under p1 the output budget was 300 tokens with no response
schema, which truncated the model mid-rationale; the strict parser then correctly rejected
the response, producing null predictions that looked like model failures but were a harness
bug. Those p1 rows are retained — predictions are immutable — and p1.1 re-scores under the
corrected configuration so the §7 failure rate describes the model rather than my buffer
size.

---

## 2026-07-29 — price coverage: a cache-poisoning bug and a vendor limitation

### D9. Tiingo reports quota exhaustion as HTTP 200, and it was being cached

Tiingo signals both of its free-tier caps with a **200 response carrying a plain-text
body**, not a 429:

    You have run over your 500 symbol look up for this month.

Because the status code was fine, `CachedFetcher` wrote that text to `data/raw/` as though
it were price data. The consequence was worse than the failed run: every later attempt read
the *cached error* instead of retrying, so those tickers could never recover — not even
after the cap reset. Silent, permanent data loss, presenting as missing coverage, which is
precisely the statistic that reveals survivorship bias.

Fixed three ways:

* `CachedFetcher` takes a `body_validator` that runs **before** anything is written, so a
  rejected body leaves no trace on disk.
* `_reject_quota_bodies` recognises both cap messages and raises `RateLimitExhaustedError`,
  not a generic failure.
* `fetch_prices` re-checks bodies read from cache, so entries written before the validator
  existed cannot be mistaken for absent data.

25 already-poisoned entries were found and purged. Covered by 10 tests, including one
asserting a valid body is still cached — the fix must not disable caching.

### D10. The free tier caps unique symbols per month at 500, so 2018 coverage is 488/530

The hourly limit was known (D1). The **monthly 500-unique-symbol cap** was not, and it is
the binding constraint. Current 2018 state:

| | Tickers | Filings affected |
|---|---|---|
| Covered, incl. SPY at all 251 sessions | 488 | — |
| Quota-blocked, recoverable when the cap resets 1 Aug | 25 | 468 (7.0%) |
| Renamed or acquired, ticker no longer resolves | 17 | 152 (2.3%) |

### D11. Tiingo's delisted-ticker retention is weaker than D1 assumed

D1 chose Tiingo over yfinance specifically because it "keeps serving history for tickers
that have since been delisted or acquired." That is only partly true. 17 tickers return an
empty array: ADS, APC, ARNC, BCR, CA, DISCA, FBHS, GPS, HFC, INFO, MON, NFX, PSKY, RE, STI,
SW, VTRS — Monsanto, Anadarko, SunTrust, C.R. Bard, CA Inc and similar. Tiingo appears to
serve history under the *successor* symbol rather than the historical one.

This does not invalidate D1 — Tiingo did serve the acquired names ANDV, COL and AET with
correct partial-year history, which yfinance would likely have dropped. But the coverage is
not complete, and the gap is concentrated in exactly the survivorship-relevant population,
so it cannot be treated as random missingness.

**Open follow-up:** these are recoverable by mapping historical tickers to successor
symbols, which needs a point-in-time symbol-change table. Until then the 2.3% of filings
they account for must be reported as an excluded, non-random subset — not quietly dropped.
Decide before Phase 5, since the full 2010–2024 universe will contain far more of them.

---

## 2026-07-28 — §4 entry timing resolved

### D8. Weekend and holiday filings skip an open, exactly as after-close filings do

**Resolves Q1**, raised 2026-07-27 and now closed. `entry_date_for()` is implemented in
`trading_calendar.py` with the rule:

> Filings that arrive while the market is open enter at the next open. Everything else
> skips one open.

| Accepted | Entry |
|---|---|
| Mon 15:59 | Tue |
| Mon 16:00 or 16:01 | Wed |
| Fri 16:01 | Tue |
| Saturday or Sunday | Tue |
| Wed 16:01 before Thanksgiving | the following Mon |

**Why the skipped open.** A filing accepted after the close is first tradeable at the next
morning's open, and that open frequently *gaps* on the news. Claiming it invites the
obvious objection that the fill was never realistically available. Surrendering it costs a
day of signal and buys a result that is harder to argue with — the right trade for a study
whose deliverable is an honest measurement. If the edge lives only in the gap, that is a
finding, not a loss.

**Why weekends are grouped with after-close.** §4 puts them in the same clause, and
separating them would let a Saturday filing enter *earlier* than a Friday-evening one
despite being newer. A test asserts entry dates are monotonic in acceptance time, so no
later filing can ever receive an earlier entry.

The Q1 write-up previously described Saturday → Monday but Sunday → Tuesday as an anomaly
inherent to the rule. That inversion was an artifact of the formulation used there
("next calendar day, then next session"), not of §4. Expressed as "skip one open" the
weekend cases agree with each other and no inversion arises.

**Note on placement.** `entry_date_for()` lives in `trading_calendar.py` rather than
`evaluate/returns.py` as the CLAUDE.md tree suggests, because it is pure date arithmetic —
no prices, no returns. Phase 4 builds return computation on top of it.

Covered by 30 tests: both sides of the cutoff to the minute, Friday evening, both weekend
days, Thanksgiving, Good Friday, the 2018-12-05 national day of mourning, DST in both
directions, rejection of naive datetimes, and the invariants that entry is always a
trading day, always strictly after acceptance, and monotonic in acceptance time.
