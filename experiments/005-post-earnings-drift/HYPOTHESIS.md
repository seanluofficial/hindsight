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

### 8b. HOLDOUT (2020-2024) — the single confirmatory shot (spent once, frozen)

The frozen long-only 20-day construction **did not survive out-of-sample.**

| construction (20-day, 10 bps) | development Sharpe | HOLDOUT Sharpe (t) |
|---|---|---|
| long/short (primary) | 0.14 | −0.03 (−0.07) |
| **long-only (frozen secondary)** | **0.53** | **−0.38 (−0.86)** |

Long-only holdout is negative at every horizon (20d −0.38, 40d −0.99, 60d −0.37) and never
clears the 0.30 floor at any cost level (0/10/25 bps → −0.28 / −0.38 / −0.53). The per-year decay
seen on development **continued straight through** the holdout: long-only 20-day Sharpe by year
was +0.42 (2020), −1.18 (2021), +0.30 (2022), −0.94 (2023), **−2.72 (2024)**.

**Verdict: H1 not supported.** The development edge was an early-2010s phenomenon that had already
decayed to zero by 2017-2019 and is absent-to-negative in 2020-2024. This is exactly the outcome
§9 predicted, and exactly what the holdout discipline exists to catch: a construction that looked
like a 0.53-Sharpe "success" on development delivered −0.38 out-of-sample. Pre-registration turned
a would-be false discovery into an honest null.

### 8a. EXPLORE (2010-2019) — development read
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

**Robustness battery (EXPLORE only; HOLDOUT still untouched).**

Long/short vs the pre-registered **long-only** variant (10 bps):

| H (days) | L/S Sharpe (t) | long-only Sharpe (t) |
|---|---|---|
| 20 | 0.14 (0.45) | **0.53 (1.68)** |
| 40 | 0.22 (0.69) | 0.21 (0.68) |
| 60 | 0.23 (0.73) | 0.26 (0.81) |

Cost sensitivity at 20 days: long-only Sharpe 0.67 / 0.53 / **0.31** at 0 / 10 / 25 bps (clears
the 0.30 floor even at 25 bps); L/S 0.34 / 0.14 / −0.16 (fails once costed). **Dropping the short
leg is decisive** — consistent with the literature that PEAD is a long-side effect and the short
leg mostly adds borrow cost and noise.

**But the effect has decayed.** Long-only 20-day Sharpe by development year:

| 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|---|---|---|
| 1.68 | −0.60 | 1.16 | 2.08 | 0.85 | 1.67 | 1.92 | **−1.37** | **−1.02** | **−0.77** |

The aggregate 0.53 is carried by 2010–2016; the last three development years are all negative.
The signal that clears the bar on the full development sample appears to have **faded to nothing
by the late 2010s**.

## 9. Failure analysis

The primary endpoint (20-day L/S) is sub-threshold and costs eat it entirely by 25 bps. The
long-only variant clears the economic floor on the pooled development sample, but the per-year
decay is the dominant fact: PEAD here is an early-2010s phenomenon that is gone — even
reversed — by 2017-2019. A confirmatory holdout on 2020-2024 therefore inherits a *declining*
signal and should be expected to be weak or null; that is the honest prior going in.

## 10. Decision

`null` — **H1 not supported.** The single holdout shot was taken on the frozen long-only 20-day
construction and came back −0.38 Sharpe (vs 0.53 on development). PEAD, as constructed here from
daily prices and a price-reaction surprise proxy, does not produce a costed, out-of-sample edge
in 2020-2024; the development signal was a decayed early-2010s effect. No further iteration —
the shot is spent and the construction is frozen. 005 joins 001-004 as an honest null, and is
the clearest single illustration in the project of *why* the holdout discipline exists: it
converted a 0.53-Sharpe development "win" into the −0.38 reality before it could be believed.
