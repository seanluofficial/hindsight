# Experiment 003 — Filing novelty / linguistic change vs. prior filings

> DRAFT. Not locked. This is the platform's flagship second experiment: grounded in published
> literature, computable without an LLM, and a fair test of whether the harness can detect a
> *known* effect before we trust it on speculative ones.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day, 10 bps quintile long/short Sharpe on the change-score signal,
HOLDOUT (2020-2024).

---

## 1. Hypothesis
- **Plain-English claim.** When a company's filing language *changes* materially from its own
  prior filings, the change predicts subsequent returns — and the direction is negative:
  companies that alter their disclosures tend to underperform. (This is the "Lazy Prices"
  effect; changes are informative precisely because filings are usually copied forward.)
- **H0.** The year-over-year textual change score has no relationship to subsequent 20-day
  market-excess returns; change-quintile L/S Sharpe ≤ 0.30.
- **H1.** Higher change → lower subsequent excess return (a short-the-changers / long-the-
  unchanged portfolio earns a positive, cost-surviving Sharpe).
- **Prior.** Strong *for the original corpus* (published: Cohen, Malloy & Nguyen, *Lazy
  Prices*, JF 2020) — but that corpus is 10-K/10-Q: long, templated documents whose
  year-over-year diff is well-defined. 8-Ks are short, event-driven, and heterogeneous, so the
  transfer is genuinely in doubt. **Design risk we name explicitly:** a null here may be
  *uninformative* — "the change metric is ill-posed for most 8-Ks" — rather than informative
  ("8-K novelty carries no signal"). The comparable-filing rule does heavy lifting, and clean
  diffs will concentrate in the few templated item types (chiefly 2.02 earnings), which
  re-imports the PEAD/earnings confound. Mitigations, pre-registered: report **coverage** (what
  fraction of filings even have a well-defined change score) as a first-class result; report the
  effect **excluding 2.02** so it is not a repackaged earnings-drift finding; and read a low
  coverage or a 2.02-only effect as "metric doesn't transfer," not as support for H1. The honest
  framing is that this tests *whether Lazy Prices is even measurable on 8-Ks* — a smaller claim
  than the JF paper's.

## 2. Signal
A **textual-change score** between a filing and the same company's most recent prior
comparable filing: cosine distance on TF-IDF, and (secondary) a normalized edit/Jaccard
distance, computed on the *raw* (pre-anonymization) text since we compare a company to
itself, not across companies. Fixed at the acceptance timestamp — the prior filing is always
older, so no lookahead. Cost ≈ $0 (no LLM). Note: 8-Ks are event-driven and less templated
than periodic reports, so "comparable prior filing" is defined as the prior 8-K sharing the
primary item code (rule fixed here); companies with no prior comparable filing are excluded
and counted.

**Vectorizer lookahead — fixed here:** the TF-IDF vocabulary and IDF weights are fit on
**EXPLORE (2010-2019) text only**, then applied frozen to HOLDOUT filings. Fitting the
vectorizer on the full corpus would leak holdout-era vocabulary and document frequencies
backward — a real, silent lookahead. Same rule for any tuned parameter of the edit/Jaccard
variants.

## 3. Dataset (point-in-time)
2010-2024 8-Ks with a locatable prior comparable filing and price coverage. EXPLORE 2010-2019
to build and tune the change metric and the comparability rule; **HOLDOUT 2020-2024 for the
single confirmatory run.** All tuning of the distance metric happens on EXPLORE only.

## 4. Baseline
(a) Loughran-McDonald *sentiment* on the same filing — does *change* beat *tone*? (b) Filing
length change alone — is the signal more than "the filing got longer"?

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps quintile L/S Sharpe (short high-change, long low-change) on
  HOLDOUT. 20-day chosen a priori because the Lazy Prices effect is a slow drift, not a jump.
- **Kill criteria.** Sharpe < 0.30, or fails BH-FDR q=0.10 across the family, or the sign
  flips vs. the literature's prediction → H1 not supported.
- **Secondary/exploratory.** 1- and 5-day horizons; the alternative distance metrics;
  interaction with item type. Reported, not counted.

## 6. Robustness battery
Time stability (esp. does it survive 2020-2021 volatility); sector and size stability; cost
sensitivity; short-leg reality (PROTOCOL §4) — the "short high-change" leg skews toward
distressed, hard-to-borrow names, so report a borrow-cost sensitivity and a long-only
(long-the-unchanged) variant; metric-specification sensitivity (TF-IDF vs edit distance vs
Jaccard — the effect must not hinge on one); baseline dominance over sentiment and over
length-change; the effect must survive **dropping 2.02 (earnings)** filings; placebo of
shuffled prior-filing pairings.

## 7. Analysis plan
Rank filings by change score within each month; form quintile L/S with monthly rebalance via
the existing portfolio harness; overlapping-window-aware SEs; report calibration is N/A (this
is a ranking signal, not a probability).

## 8–10. Results / Failure analysis / Decision _(filled after)_
