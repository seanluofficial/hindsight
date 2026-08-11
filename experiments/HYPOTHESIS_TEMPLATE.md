# Experiment NNN — <short title>

> Copy this file to `experiments/NNN-slug/HYPOTHESIS.md`, fill every section, and **commit it
> before looking at a single outcome.** The commit is the pre-registration timestamp. Sections
> marked _(filled after)_ stay empty until their stage is reached.

**Status:** `draft` → `locked` → `explore` → `holdout` → `robustness` → `forward` → `closed`
(one of; keep the registry in `README.md` in sync)
**Locked at (git SHA):** _____
**Primary endpoint (the one test that counts toward the family):** _____

---

## 1. Hypothesis

- **Plain-English claim.** One sentence a non-quant could read.
- **H0 (null).** What "nothing here" looks like, stated as a number.
- **H1 (alternative).** The directional effect claimed. Directional, not two-sided, if the
  prior justifies it — and say why.
- **Prior / rationale.** Why this could plausibly be true. Cite the literature or the
  mechanism. "It might work" is not a rationale.

## 2. Signal

- **What the signal is** and exactly how it is computed from data available *at the filing's
  acceptance timestamp* (no lookahead).
- **Inputs.** Which fields/text, and the anonymization state required.
- **Cost to compute** (API $, wall-clock) for the full sample.

## 3. Dataset (point-in-time)

- **Universe & span.** Which filings, which tickers, which years.
- **Partition map.** Which numbers come from EXPLORE, which single run is reserved for
  HOLDOUT, whether FORWARD applies. (See `PROTOCOL.md` §2.)
- **Exclusions.** Pre-specified; each counted and reported, never silently applied.

## 4. Baseline

- The naive method this signal must beat on identical inputs (lexicon, base-rate constant,
  prior-return, …), and why that is the fair comparison.

## 5. Primary endpoint & kill criteria

- **Primary endpoint.** Exactly one: metric + horizon + cost + partition. This is the only
  test that enters the family-wise correction.
- **Kill criteria (pre-registered).** The numbers at which H1 is declared **not supported**.
  State *both* gates (PROTOCOL §5): the statistical gate (primary p passes BH-FDR at q=0.10 —
  BY where dependence bites) *and* the economic-materiality floor (e.g. HOLDOUT 5-day/10bps
  Sharpe ≥ 0.30, or effect size ≥ X). A survivor must clear both; do not conflate them.
- **Secondary/exploratory readouts.** Everything else you'll report but that does *not* count
  as a discovery.

## 6. Robustness battery

Which attacks from `PROTOCOL.md` §4 apply, and any experiment-specific ones. State them now so
they can't be softened later.

## 7. Analysis plan

- Estimation method, test statistic, how the p-value is formed, how portfolios are built.
- Anything that could be a researcher degree of freedom — fix it here.

---

## 8. Results _(filled after)_

- EXPLORE estimate:
- **HOLDOUT (one shot):**
- Robustness table:
- Family-wise (BH-FDR) verdict:

## 9. Failure analysis _(filled after)_

- If it died: where, and the most likely reason. If it survived: the strongest remaining
  reason to still disbelieve it, and what forward evidence would settle it.

## 10. Decision _(filled after)_

- `survived` / `null` / `inconclusive` / `abandoned`, and what (if anything) it spawns as a
  new pre-registered experiment. Link any `DEVIATIONS.md` entries.
