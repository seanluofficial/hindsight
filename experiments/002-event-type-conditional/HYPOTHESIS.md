# Experiment 002 — Event-type conditional returns

> DRAFT. Not locked. Do not run against outcomes until this file is filled and committed with
> status `locked`. No LLM required — this is a cheap, clean structural experiment.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 5-day, 10 bps difference in mean market-excess return between the
"high-impact" and "routine" item-code groups, on HOLDOUT (2020-2024).

---

## 1. Hypothesis
- **Plain-English claim.** *Which kind* of event an 8-K reports predicts the size and sign of
  the subsequent abnormal return, independent of any language model reading it. Some item
  codes (e.g. 4.02 non-reliance on prior financials, 2.06 material impairments, 5.02
  executive departures) systematically precede larger moves than routine ones (e.g. 7.01 Reg
  FD, 8.01 other).
- **H0.** Mean market-excess return does not differ across item-code groups; the high-impact
  group's 5-day/10bps mean is ≤ 0.
- **H1.** The pre-registered high-impact group has a non-zero mean market-excess return at
  5 days, distinguishable from the routine group and surviving costs.
- **Prior.** Moderate-to-strong. The event-study literature documents differential reaction by
  8-K item type; this is closer to replication than discovery, which is a *feature* — it
  validates the harness before we trust it on harder signals.

## 2. Signal
The 8-K's **item codes**, already parsed and stored in `filings.item_codes`. Group into
pre-registered buckets (fixed below, before looking):
- **high-impact:** 1.03, 2.06, 4.02, 5.02
- **earnings/results:** 2.02
- **routine:** 7.01, 8.01, and everything else
No text, no LLM, no anonymization needed. Cost ≈ $0.

## 3. Dataset (point-in-time)
All ingested 2010-2024 8-Ks from point-in-time members with price coverage. EXPLORE 2010-2019
to confirm the grouping behaves; **HOLDOUT 2020-2024 for the one confirmatory run.** Filings
with multiple item codes are assigned to the highest-impact bucket present (rule fixed here).

## 4. Baseline
Two: (a) the unconditional mean excess return (does *conditioning on event type* add anything
over the grand mean?), and (b) the routine group (is high-impact distinguishable from noise
events?).

## 5. Primary endpoint & kill criteria
- **Primary (exactly one test enters the family).** 5-day, 10 bps *difference in mean
  market-excess return, high-impact minus routine*, on HOLDOUT — a two-sample test. The
  high-impact-vs-routine contrast, not high-impact-vs-0, is the primary, because it isolates
  "the *kind* of event matters" from a market-wide drift that would lift both groups.
- **Kill criteria.** The high-impact−routine difference is not distinguishable from 0 at
  BH-FDR q=0.10 across the family (BY reported where dependence bites), or is economically
  trivial (|difference| < 25 bps after costs) → H1 not supported.
- **Secondary/exploratory.** High-impact vs. 0 (one-sample); 1-day and 20-day horizons;
  per-item-code breakdown; a costed long/short of high-impact vs. routine. Reported, not
  counted toward the family.

## 6. Robustness battery
Time stability (by year, pre/post-2020); sector stability; cost sensitivity (0/10/25); sign
consistency of individual codes within the high-impact bucket (the effect shouldn't be one code
carrying the group). Short-leg reality (PROTOCOL §4): 4.02/2.06 filers skew hard-to-borrow, so
the secondary long/short is reported with a borrow-cost sensitivity and a long-only variant.
Placebo: a randomly-assigned "event type" must find nothing.

## 7. Analysis plan
Event-study mean market-excess return per group; Newey-West / clustered SEs given overlapping
20-day windows; portfolio readout via the existing harness with `direction` set by the group's
EXPLORE sign (fixed before HOLDOUT).

## 8–10. Results / Failure analysis / Decision _(filled after)_
