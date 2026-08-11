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
comparable filing: **TF-IDF cosine distance** (change = 1 − cosine similarity). Computed on
the stored **anonymized text** — not the raw text as originally drafted. Because the
comparison is a company against *itself*, the only identifier that anonymization removes (the
company name) is constant across both filings and irrelevant to the *change* signal; using the
in-DB anonymized text is reproducible and avoids re-reading 100k cached files. Fixed at the
acceptance timestamp — the prior filing is always older, so no lookahead. Cost ≈ $0 (no LLM).
"Comparable prior filing" = the most recent earlier 8-K from the same company (CIK) sharing
the **primary item code** (the filing's first listed item; rule fixed here). Companies with no
prior comparable filing, or filings missing anonymized text, are excluded and counted.

**Vectorizer lookahead — fixed here:** the TF-IDF vocabulary and IDF weights are fit on
**EXPLORE (2010-2019) text only**, then applied frozen to HOLDOUT filings. Fitting the
vectorizer on the full corpus would leak holdout-era vocabulary and document frequencies
backward — a real, silent lookahead. Tokens absent from the EXPLORE vocabulary are ignored at
transform time.

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

## 8. Results (in-sample — see DEVIATIONS D-EXP1)
Change scores computed for 66,211 filings (EXPLORE-fit vocabulary of 40,691 tokens).
Quintile long/short (long least-changed, short most-changed), 10 bps:

| data | horizon | months | Sharpe | t | max DD |
|---|---|---|---|---|---|
| development | 20d | 101 | −0.20 | −0.58 | 13.2% |
| held-out | 5d | 50 | −0.86 | −1.75 | 14.7% |
| held-out | 20d | 50 | −0.87 | −1.77 | 19.6% |

**H1 rejected.** The Sharpe is *negative* at every horizon and partition — the opposite of the
literature's prediction that low-change filings outperform — and never statistically
significant. The "Lazy Prices" linguistic-change effect does **not** transfer to 8-Ks here.

## 9. Failure analysis
Most likely structural, as pre-registered: 8-Ks are short, event-driven, and heterogeneous, so
a company's "prior comparable filing" (same primary item code) is a much weaker analog than a
prior 10-K is to the next 10-K. The change score is dominated by which event happened, not by
managerial obfuscation. A clean test of Lazy Prices really wants periodic reports (10-K/10-Q),
which this corpus does not contain.

## 10. Decision
`null` (in-sample; sign contrary to H1, not significant). Note this experiment was intended as
the one with a clean single-shot holdout, but per DEVIATIONS D-EXP1 both partitions were
computed together during implementation, so it is reported in-sample. Does not spawn a follow-up
on 8-Ks; the honest next step for Lazy Prices would be ingesting 10-K/10-Q text — out of scope.
