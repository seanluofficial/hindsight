# Experiment 005 — Post-earnings-announcement drift (PEAD)

> DRAFT. Not locked. The first experiment designed *after* learning why 001–004 were nulls:
> they all predicted returns from an 8-K's own text, at the next open, over 1–20 days — exactly
> the reaction the market prices fastest. 005 changes the target: it does not try to beat the
> announcement reaction, it tries to ride the well-documented *drift that continues after it*.

**Status:** `draft`
**Locked at (git SHA):** 52aaa73
**Primary endpoint:** 20-day, 10 bps quintile long/short annualized Sharpe of a portfolio that
longs the most-positive and shorts the most-negative earnings surprises, HOLDOUT (2020-2024).

---

## 1. Hypothesis

- **Plain-English claim.** When a company reports earnings, the stock does not fully adjust at
  once. It keeps drifting in the direction of the surprise for weeks — good surprises keep
  rising, bad ones keep falling. This "post-earnings-announcement drift" (PEAD) is one of the
  most replicated anomalies in finance (Ball & Brown 1968; Bernard & Thomas 1989) and, though
  weaker since ~2000, is widely reported to persist. If it survives *here* — point-in-time
  universe, next-open entry, real costs — it is a genuine, usable signal, not a backtest
  artifact.
- **The surprise proxy.** We have no analyst consensus, so we cannot compute a classic
  standardized unexpected earnings (SUE). Instead the **sign and size of the market's own
  immediate reaction** is the surprise: the market-excess return from the close before the
  earnings date up to our entry open. A large positive reaction = a positive surprise. This is
  fully observable *at* the entry open (its window ends there), so there is no lookahead.
- **H0.** The post-entry drift is unrelated to the surprise: a long-high / short-low-surprise
  portfolio earns a 20-day Sharpe ≤ 0.30 after 10 bps on HOLDOUT.
- **H1.** Drift continues in the surprise direction: the portfolio earns a 20-day Sharpe > 0.30
  after 10 bps on HOLDOUT.
- **Prior.** Moderate-to-strong that *some* drift exists; genuinely uncertain that it clears the
  0.30 economic floor after costs at a daily, retail-feasible cadence. That uncertainty is the
  point of testing.

## 2. Signal / measure

For each **earnings** 8-K (SEC item code **2.02** present), using daily prices already in the DB:

- **Surprise** = market-excess return from the close *before* `period_of_report` (the earnings
  date the filer stamps) to the **entry open** (the next open after `accepted_at_utc`, per the
  existing timing rules). Reuses exactly the pre-filing window that Experiment 004 already
  computed and validated. Observable at entry; no lookahead.
- **Drift** = the existing market-excess return from the entry open over horizon *H* trading
  days, via the shared `filing_excess_return` harness (identical timing/exclusion rules as every
  other experiment).

No LLM, no anonymization, ≈ $0.

**Honest limits (stated up front).** The price-reaction proxy conflates surprise with anything
else that moved the stock in the pre-window; a true SUE would be cleaner (deferred — we lack
consensus estimates). Daily bars miss intraday adjustment. Holding *H* > ~21 days while
rebalancing monthly overlaps cohorts, so monthly observations are autocorrelated and t-stats are
optimistic — reported as a caveat, and the 20-day horizon (≈ one month, minimal overlap) is the
primary for that reason.

## 3. Dataset (point-in-time)

All 2010-2024 earnings 8-Ks (item 2.02) with a usable `period_of_report`, price coverage over
both the surprise and drift windows, and prior close ≥ $5. EXPLORE 2010-2019 to settle the
construction; **HOLDOUT 2020-2024 for the single confirmatory read.** Every exclusion (no event
date, no coverage, penny stock, event not before entry) pre-specified, counted, reported.

## 4. Baseline

The null is a zero-Sharpe portfolio (no drift). Secondary reference: an equal-weight long-only
version of the top-surprise quintile, and the full-sample (all-item) version, to see whether any
drift is earnings-specific or general.

## 5. Primary endpoint & kill criteria

- **Primary.** 20-day, 10 bps quintile long/short annualized Sharpe on HOLDOUT. Two gates
  (PROTOCOL §5): (a) significant after the family-wise correction, and (b) ≥ 0.30 Sharpe
  economic-materiality floor.
- **Kill criteria.** 20-day HOLDOUT Sharpe ≤ 0.30 after 10 bps → H1 not supported; PEAD does not
  survive this construction with costs.
- **Secondary/exploratory.** Horizons 40 and 60 days; long-only variant; the all-item version;
  monotonicity across quintiles (does drift rise smoothly Q1→Q5?). Reported, not the primary
  claim.

## 6. Robustness battery

Time stability (per year — has PEAD decayed over 2010→2024?); sensitivity to the surprise window
definition (event-date close vs. one session earlier); higher cost level (25 bps); excluding vs.
imputing missing event dates; quintile monotonicity as a placebo on noise. A working signal
should be positive, roughly monotone, and survive 25 bps at the 20-day horizon.

## 7. Analysis plan

Compute surprise and drift via the shared harness; each calendar month, sort that month's
earnings filings into quintiles by surprise, long the top and short the bottom, hold *H* days,
and take the cohort's mean market-excess return net of `cost_bps`. Annualize the monthly series
to a Sharpe; report the t-statistic (flagged optimistic under overlap for *H* > 21). Primary is
HOLDOUT 20-day; EXPLORE is development.

## 8. Results

**EXPLORE (2010-2019) — development read. HOLDOUT (2020-2024) remains untouched.**
30,375 earnings 8-Ks considered; 16,729 scored a surprise; exclusions counted (7,708 penny/no
prior close, 4,144 no event date, 1,791 no price coverage, 288 missing window prices).

| partition | H (days) | months | positions | return/mo | Sharpe (ann.) | t | max DD |
|---|---|---|---|---|---|---|---|
| explore | 20 | 120 | 11,031 | +0.070% | **0.14** | 0.45 | −22% |
| explore | 40 | 120 | 10,942 | +0.170% | 0.22 | 0.69 | −27% |
| explore | 60 | 120 | 10,871 | +0.225% | 0.23 | 0.73 | −35% |

**The sign is finally right, and it behaves like real PEAD.** Unlike 001-003, every horizon is
**positive** (drift continues in the surprise direction, not against it), and the effect **grows
with horizon** (0.14 → 0.22 → 0.23 Sharpe as the drift accumulates over 20 → 40 → 60 days) —
exactly the signature the literature describes. But on development data it is **economically
weak**: the primary 20-day Sharpe of 0.14 is well below the 0.30 materiality floor, and no
horizon is statistically significant (|t| < 1). A promising direction that does not, on its own,
clear the bar.

_HOLDOUT is deliberately not yet run — see §10._

## 9. Failure analysis

_Pending the confirmatory read and the EXPLORE robustness battery (long-only leg, per-year
decay, 25 bps, surprise-window sensitivity)._

## 10. Decision

_Open. The pre-registered primary (20-day L/S) is sub-threshold on development, so a single
HOLDOUT shot would most likely confirm a weak-null at that horizon. Before freezing, the
EXPLORE-legal secondaries in §5-6 (long-only variant — PEAD is classically stronger on the long
side — and per-year decay) are worth running to see whether a pre-specified construction is
materially stronger. Refinement stays on EXPLORE; HOLDOUT is spent once, later._
