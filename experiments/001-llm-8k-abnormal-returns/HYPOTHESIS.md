# Experiment 001 — Can anonymized LLM analysis of 8-K filings predict abnormal returns?

> This experiment predates the platform. Its full specification is
> [`../../PREREGISTRATION.md`](../../PREREGISTRATION.md); this file is the registry-compatible
> summary. Where the two differ, the pre-registration wins for 001.

**Status:** `running` (Phase 5 historical scoring in progress)
**Locked at (git SHA):** pre-registration committed before scoring; see repo history
**Primary endpoint:** 5-day, 10 bps quintile long/short Sharpe

---

## 1. Hypothesis
- **Plain-English claim.** An LLM, shown an 8-K with every clue to the company's identity and
  date removed, can predict the direction of the stock's market-excess move.
- **H0.** Directional accuracy = 50%; 5-day/10bps Sharpe ≤ 0.30.
- **H1.** Accuracy > 50% and the pre-registered Sharpe threshold is cleared — *and* it is not
  explained by the model recognizing the issuer (the contamination audit).
- **Prior.** Weak. The design expects a likely null; the value is measuring it honestly.

## 2. Signal
Direction + probability in [0.50, 1.00] from an LLM at temperature 0 over anonymized filing
text (≤12k chars). Backends pluggable; primary run is `deepseek-v4-flash`. Cost ≈ $0.00057
per filing (~$2.85 for the 5,000-filing frozen sample).

## 3. Dataset (point-in-time)
Frozen stratified 5,000-filing sample of 2010-2024 8-Ks from point-in-time S&P 500 members.
**Partition caveat:** 001's pre-registered test runs on the full sample, so its HOLDOUT is
already spent. It is reported as a single-shot / in-sample study; the EXPLORE⁄HOLDOUT split
binds 002 onward. (See `PROTOCOL.md` §2.)

## 4. Baseline
Loughran-McDonald lexicon over identical text (comprehension-free word counting). Complete:
6,720-filing pilot each for v1/v2.

## 5. Primary endpoint & kill criteria
- **Primary.** 5-day, 10 bps quintile L/S Sharpe on the full sample.
- **Kill criteria.** Sharpe < 0.30 → H1 not supported (a valid, expected outcome). A
  contamination identification rate above 20% forces the analysis to be re-run on only the
  filings the model failed to identify, both versions reported.

## 6. Robustness battery
All §4 attacks, plus the §12 splits in the pre-registration. Contamination audit is
mandatory and gates interpretation of every downstream number.

## 7. Analysis plan
Per `PREREGISTRATION.md` §4–§14. Immutable predictions; costs at 0/10/25 bps; all three
horizons reported.

## 8. Results _(filled after)_
- Pilot (n≈230 evaluable, early slice): 5-day hit 51.7%, Brier 0.259 (worse than uninformed),
  1-day expectancy negative after costs, 5-day Sharpe +0.96 but t≈1.1 (not significant).
- **Full-sample HOLDOUT/primary:** pending completion of the DeepSeek run.

## 9. Failure analysis _(filled after)_

## 10. Decision _(filled after)_
