# Experiment 004 — Information staleness / first-disclosure

> DRAFT. Not locked. A **diagnostic** experiment: it does not propose a tradeable signal. Its
> job is to explain *why* 001 is a coin flip and to tell 002+ and the future Reaction Gap
> branch *where the fresh information actually is*. Cheap — uses only prices already ingested.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** Median **staleness fraction** — the share of an 8-K's total abnormal
move that occurs *before* the filing is accepted — on HOLDOUT (2020-2024). Diagnostic, not a
trading endpoint; reported alongside the trading family but not claimed as a tradeable "edge."

---

## 1. Hypothesis
- **Plain-English claim.** By the time an 8-K hits EDGAR, the market has often *already* moved
  on the news, because the event (and usually a press release) predates the filing. If most of
  the reaction happens before the filing, there is little left for a model reading the filing
  to predict — which would explain Experiment 001's coin-flip result.
- **H0.** The move is concentrated *after* the filing: the median staleness fraction is ≤ 0.5
  (the 8-K is, on balance, the market's first look).
- **H1.** The move is concentrated *before* the filing: median staleness fraction > 0.5 — most
  of the abnormal move predates the filing, so the filing is frequently stale.
- **Prior.** Strong. 8-Ks must be filed within four business days of the event, and material
  news is typically released via press wire first; `period_of_report` (event date) usually
  precedes `accepted_at_utc` (filing time) by hours to days.

## 2. Signal / measure
For each 8-K, using **daily** prices already in the DB — no new data:
- **Pre-filing abnormal move** = market-excess return from the close *before* `period_of_report`
  (the event date the filer stamps on the form) up to the entry open (the next open after
  `accepted_at_utc`, per the existing timing rules). This is what already happened.
- **Post-filing abnormal move** = the existing 5-day market-excess return from the entry open.
- **Staleness fraction** = |pre| / (|pre| + |post|). 1.0 = the move was fully over before the
  filing; 0.0 = nothing happened until after the filing.
No LLM, no anonymization. Cost ≈ $0.

**Honest limits (stated up front).** Daily bars can't see the intraday reaction, so this is a
*coarse* first pass; it over- or under-counts within the event day. `period_of_report` is
sometimes missing or set to the filing date — those filings are **excluded and counted**, not
guessed. The precise, intraday, true-first-disclosure version is deliberately deferred to the
**Reaction Gap** branch (which needs news-wire timestamps and intraday prices we do not yet
have). 004 is the cheap test of whether that expensive branch is even worth building.

## 3. Dataset (point-in-time)
All 2010-2024 8-Ks with a usable `period_of_report`, price coverage over both windows, and a
prior-close ≥ $5. EXPLORE 2010-2019 to settle the window definitions; **HOLDOUT 2020-2024 for
the single confirmatory read.** Exclusions (missing event date, no price coverage, penny
stocks) pre-specified, each counted and reported.

## 4. Baseline
The full-sample post-filing signal from 001/002 is the reference: 004 asks whether that signal
is weak *because* the information is already priced. Secondary comparison: does the residual
post-filing drift survive **after** restricting to the freshest quartile (lowest staleness)?

## 5. Primary endpoint & kill criteria
- **Primary.** Median staleness fraction on HOLDOUT, with a one-sided test that it exceeds 0.5.
- **Kill criteria (of the *explanation*, not a trade).** Median staleness fraction ≤ 0.5 on
  HOLDOUT → staleness does **not** explain 001, and we look elsewhere (event type, novelty).
- **Secondary/exploratory.** Staleness fraction by item-code group (which events are freshest);
  whether the freshest quartile of filings shows any 5-day post-filing drift the full sample
  hides; the distribution, not just the median. Reported, not counted as trading discoveries.

## 6. Robustness battery
Time stability (per year; does staleness rise over 2010→2024 as machine filing-reading speeds
up?); sensitivity to the pre-window start (event-date close vs. one day earlier); sensitivity
to excluding vs. imputing missing event dates; item-type stability. Placebo: filings where
`period_of_report == filing date` should show a pre-filing window of ~0 by construction — a
sanity check the measure isn't manufacturing pre-moves.

## 7. Analysis plan
Compute both windows via the existing market-excess return code; form the fraction; report the
HOLDOUT median with a bootstrap CI and a one-sided sign/Wilcoxon test against 0.5. Because this
endpoint is diagnostic (a description of the world, not a portfolio), it is **listed** in the
family for transparency but does not assert a tradeable Sharpe; any drift claim in the
secondary analysis that *would* be tradeable is flagged as hypothesis-generating for a future
pre-registered experiment, never a result claimed here.

## 8–10. Results / Failure analysis / Decision _(filled after)_
