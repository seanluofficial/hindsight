# Experiment 009 — Insider cluster-buying, whole-market / small-cap (Form 4)

> DRAFT → will be locked before the HOLDOUT shot. This is the direct follow-up to 006's failure
> analysis. 006 found no insider-buying edge in the S&P 500; the literature says the edge lives
> in *small caps*, which that universe excludes by construction. 009 removes the large-cap
> restriction and tests the same signal on the whole market. **Pre-registered before any
> small-cap price data exists — there is no outcome to peek at.**

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day, 10 bps mean market-excess return of **cluster-buy events**
(≥ 2 distinct insiders making open-market purchases within a 30-day window), entered next open
after the Form 4 filing date, on the **whole-market universe**, on HOLDOUT (2020-2024).
One-sided H1: **positive**.

---

## 1. Hypothesis
- **Plain-English claim.** Identical to 006 — a cluster of insiders buying their own stock on
  the open market signals confidence — but tested where the effect is documented to be
  strongest: **small and mid caps.** 006 established the machinery works and the S&P 500 is
  null; 009 asks whether the same signal, unchanged, is *material* once the universe is no
  longer restricted to the most-arbitraged large caps (Lakonishok & Lee 2001; Cohen, Malloy &
  Pomorski 2012; the effect is concentrated in smaller, less-covered names).
- **H0.** Whole-market cluster-buy events have a 20-day mean market-excess return ≤ 0.
- **H1.** Positive, survives costs, and a long-only book clears the 0.30 materiality floor —
  **and** the effect is stronger outside the S&P 500 than inside it (the 006 result should
  re-appear as the large-cap subgroup).
- **Prior.** Moderate-to-good, and the best-motivated of the family: this is the one experiment
  whose *failure analysis in a prior experiment* explicitly predicted where the signal would be.
  Honest risks: small-cap names carry higher transaction costs and borrow constraints (mitigated
  here by being long-only), and thin price data. A null remains possible.

## 2. Signal
Unchanged from 006. From SEC's structured Form 345 quarterly data sets, keep open-market
purchases (`TRANS_CODE='P'`, acquired) by officers/directors — but for **every Form-4 issuer
with a ticker**, not only S&P 500 members (`scripts/ingest_insider.py --scope all` →
`data/insider_purchases_all.csv`, 368,175 purchases across 10,749 tickers). A cluster-buy event
is ≥ 2 distinct insiders within a 30-calendar-day trailing window; the information-available
date is the latest Form 4 filing date; a 30-day cooldown collapses one burst into one event.
Whole-market: **31,701 cluster-buy events** across **6,924 tickers** (vs. 1,349 events in the
S&P 500). No LLM. Cost: purchase data is already cached; the marginal cost is price coverage for
the small-cap tickers (paid data tier).

## 3. Dataset & the survivorship guarantee (point-in-time)
The universe here is **EDGAR-filer-defined**, not an index-membership list — deliberately,
because no free point-in-time small-cap index history exists, and a *current* small-cap list
would be survivorship-biased (invariant 2). Membership is instead enforced event-by-event by the
shared harness: an event is evaluable only if the ticker has a real prior close ≥ $5 at the
event date. Because the price vendor (Tiingo) retains delisted and acquired names, a company that
later went bankrupt still contributes its pre-delisting events, and one that had no listed price
at the event date simply produces no event. This is survivorship-safe by construction: nothing
is included or excluded based on what happened *after* the event. EXPLORE 2010-2019 to confirm
the construction; **HOLDOUT 2020-2024 for one confirmatory shot** (`--partition holdout` only).
Exclusions (each counted): no price coverage, no prior close, prior close < $5, calendar edges.

## 4. Baseline
(a) Single-insider purchases in the same universe (is the *cluster* doing work?). (b) **The
size split — the S&P 500 subset vs. the non-S&P subset.** This is the decisive robustness: H1
predicts the effect is absent/weak in the S&P subset (reproducing 006) and present in the
smaller names. If instead the effect is uniform or reversed, the small-cap story is wrong.

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps mean market-excess return of whole-market cluster-buy events on
  HOLDOUT, one-sample t vs 0 (one-sided, H1 positive), entry = next open after the filing date.
- **Kill criteria.** Mean ≤ 0, or not significant at BH-FDR q=0.10 across the family, **or** a
  monthly long-only book of cluster-buy names fails the 0.30 Sharpe materiality floor after
  10 bps → H1 not supported.
- **Secondary/exploratory.** 5- and 60-day horizons; the S&P-vs-non-S&P size split and, if
  market-cap proxies allow, a size-decile monotonicity check; dollar-weighted and
  distinct-insider intensity; higher cluster thresholds (≥3); insider-*sells* placebo (should be
  far weaker). Reported, not counted.

## 6. Robustness battery
Time stability (per year, pre/post-2020 — is the effect decaying?); cost sensitivity (0/10/25,
noting long-only has no borrow problem but small caps have wider spreads, so 25 bps is the
honest read, not 10); cluster threshold (≥2 vs ≥3, 30- vs 45-day window); the size split (§4);
single-insider baseline dominance; insider-sell placebo. **All robustness is EXPLORE-only**; the
HOLDOUT is a single frozen shot. 009 **joins the multiple-testing family** (PROTOCOL §3): its
primary p-value enters the Benjamini-Hochberg correction with 001-008.

## 7. Analysis plan
Build events on EXPLORE from the whole-market file, freeze the construction, then take the one
HOLDOUT shot. Event-study mean market-excess return with the shared harness timing; a monthly
long-only book for the materiality floor. The size split is computed on EXPLORE as the key
diagnostic. Small-cap spreads make the 25 bps cost level the one to believe.

## 8. Results — development, refinement, and the single HOLDOUT shot

**Development (2010-2019), blunt recipe (006 signal, whole market).** 31,360 cluster events.
20-day mean market-excess **+40 bps (t 4.76)** — the first positive, significant primary in the
project — vs. −37 bps in the S&P (006). The size-split mechanism is confirmed: the effect is
absent in large caps, present in small/mid. But the monthly long-only book was **0.20 Sharpe**,
below the 0.30 materiality floor.

**Development, refined recipe (pre-committed).** Opportunistic insiders only (drop routine
same-month-every-year buyers; Cohen-Malloy-Pomorski) + clustered purchases ≥ $50k + an
overlapping daily-rebalanced book. 16,791 events. The refinement *strengthened* the signal
(20-day mean **+65 bps, t 4.84**) and lifted the book to **0.30 (monthly) / 0.36 (daily)** —
clearing the bar. Per the pre-agreed plan, this recipe was frozen and taken to the holdout.

**HOLDOUT (2020-2024) — the single frozen shot.**

| metric | development | HOLDOUT |
|---|---|---|
| refined 20-day mean excess | +65 bps (t 4.84) | **−128 bps (t −5.43)** |
| refined monthly long-only Sharpe | 0.30 | **−0.34** |

The signal **reversed sign** out-of-sample, as significantly negative as it was positive. H1 is
decisively **not supported.**

**A discarded number, flagged honestly.** The overlapping *daily* book reported +0.40 on the
holdout — contradicting the −128 bps mean and the −0.34 monthly book. It is **not trusted and
not used**: the daily construction skips missing price days, so a small-cap that craters and
delists silently drops its worst days — survivorship bias (invariant 2) re-entering through the
construction. The survivorship-safe numbers (event-study mean, monthly book) are the verdict.

## 9. Failure analysis
Same lesson as 005, starker: a signal real and significant across a full development decade,
right-signed, literature-backed, and cleared for materiality — reversed completely on the
untouched years. The 2020-2024 period (COVID crash and small-cap boom/bust) is unlike 2010-2019;
insiders buying small-cap dips in 2020-22 were, on average, early. The daily-book artifact is a
second, independent lesson: even a "better" construction can smuggle survivorship back in, and
the fix is to trust only the survivorship-safe measure.

## 10. Decision
`null` — H1 rejected on the HOLDOUT (sign reversal). The best-prior candidate, refined the right
way and given one clean shot, did not survive. 009 joins the multiple-testing family; with
nothing surviving, no family-wise correction is needed. The small-cap price data acquired for
009 remains a reusable asset for any future whole-market or FORWARD test.
