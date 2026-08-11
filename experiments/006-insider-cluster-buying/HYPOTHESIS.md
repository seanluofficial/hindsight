# Experiment 006 — Insider cluster-buying (Form 4)

> DRAFT → will be locked before the HOLDOUT shot. This is the candidate with the highest prior
> of a *usable* signal, and the first to leave the 8-K corpus: it reads SEC Form 4 insider
> transactions. Pre-registered before any outcome on 2020-2024 is seen.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day, 10 bps mean market-excess return of **cluster-buy events**
(≥ 2 distinct insiders making open-market purchases within a 30-day window), entered next open
after the Form 4 filing date, on HOLDOUT (2020-2024). One-sided H1: positive.

---

## 1. Hypothesis
- **Plain-English claim.** When several insiders at the same company *buy their own stock on
  the open market* in a short span, they are signalling confidence with their own money — and
  the stock tends to outperform over the following weeks. Selling is noisy (diversification,
  taxes, option exercises); *buying*, especially by a cluster of insiders, is the informative
  side.
- **H0.** Cluster-buy events have a 20-day mean market-excess return ≤ 0.
- **H1.** Cluster-buy events have a positive 20-day mean market-excess return that survives
  costs, and a long-only portfolio of such names clears the 0.30 materiality floor.
- **Prior.** Moderate. The insider-purchase effect is well documented (Lakonishok & Lee 2001;
  Cohen, Malloy & Pomorski 2012 on *opportunistic* vs *routine* trades) and cluster buying is
  its strongest form. **Two honest headwinds:** (a) it is a *known* effect, so it may be
  arbitraged, especially in large caps; (b) open-market purchases by S&P 500 insiders are
  **rare** (execs mostly receive and sell grants), so events will be relatively sparse and the
  large-cap universe is where the effect is weakest. A null is entirely possible.

## 2. Signal
From SEC's structured **Form 345 quarterly data sets** (issuer ticker/CIK, transaction code,
shares, price, reporting-owner role), keep **open-market purchases** only: non-derivative
transactions with `TRANS_CODE = 'P'` and `TRANS_ACQUIRED_DISP_CD = 'A'`, by officers/directors.
A **cluster-buy event** for an issuer is fixed here as **≥ 2 distinct insiders** with a
qualifying purchase whose transactions fall within a **30-calendar-day trailing window**; the
event's information-available date is the **latest Form 4 filing date** in the cluster (Form 4
must be filed within two business days of the trade, so the filing date — not the trade date —
is the point-in-time signal). Secondary intensity measures: distinct-insider count and total
dollars purchased. No LLM. Cost: ~60 small file downloads (cached), ~$0.

## 3. Dataset (point-in-time)
Form 345 data sets 2010-2024, restricted to issuers that are **point-in-time S&P 500 members**
at the event date (via the frozen `universe` table — no survivorship) and have price coverage.
EXPLORE 2010-2019 to settle the window and threshold; **HOLDOUT 2020-2024 for one confirmatory
shot** (computed only with `--partition holdout`, per DEVIATIONS D-EXP1). Exclusions
pre-specified and counted: no issuer ticker match, not a universe member at the event date, no
price coverage, prior close < $5.

## 4. Baseline
(a) The unconditional next-20-day market-excess return of universe members (does a cluster buy
beat a random entry?). (b) Single-insider purchases (is the *cluster* doing work beyond one
insider buying?).

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps mean market-excess return of cluster-buy events on HOLDOUT,
  one-sample t-test vs 0 (one-sided, H1 positive), entry = next open after the filing date.
- **Kill criteria.** Mean ≤ 0, or not significant at BH-FDR q=0.10 across the family, **or** a
  monthly long-only portfolio of cluster-buy names fails the 0.30 Sharpe materiality floor
  after 10 bps → H1 not supported.
- **Secondary/exploratory.** 5- and 60-day horizons; dollar-weighted and distinct-insider
  intensity; officer-only vs. any-insider; size/sector cuts. Reported, not counted.

## 6. Robustness battery
Time stability (per year, pre/post-2020 — is the effect decaying like 005's PEAD?); cost
sensitivity (0/10/25 + the reminder that a long-only book has no borrow problem); cluster
threshold sensitivity (≥2 vs ≥3 insiders, 30- vs 45-day window); baseline dominance over
single-insider buys; placebo of insider *sells* (code S) which should be far weaker or absent.
**All robustness is EXPLORE-only**; the HOLDOUT is a single frozen shot.

## 7. Analysis plan
Build events on EXPLORE, freeze the construction, then take the one HOLDOUT shot. Event-study
mean market-excess return with the shared harness timing; a monthly long-only portfolio for the
materiality floor (equal-weight all names with an active cluster-buy in the trailing window,
20-day hold, monthly rebalance). Overlapping-window-aware SEs. Long-only, so no short-borrow
caveat.

## 8. Results (EXPLORE / development only — HOLDOUT preserved)
14,619 open-market insider purchases ingested (officers/directors of point-in-time members).
1,349 cluster-buy events (≥2 distinct insiders / 30 days); 675 evaluable on EXPLORE.

| horizon | n | mean excess | median | t | hit rate |
|---|---|---|---|---|---|
| 5d | 675 | −0.8 bps | +10.0 | −0.06 | 51.9% |
| 20d | 674 | **−36.8 bps** | −17.1 | −1.41 | 49.0% |
| 60d | 671 | −80.8 bps | +8.2 | −1.63 | 50.8% |

Baseline (any single-insider buy, 20d): −1.2 bps, t −0.09 — flat, confirming no sign/timing
bug. Materiality long-only book (EXPLORE): Sharpe **−0.18**.

**H1 not supported on development.** Cluster buying does not precede positive returns in this
universe; the point estimates are slightly negative and never significant.

## 9. Failure analysis
Exactly the pre-registered headwind: the insider-purchase anomaly is documented mainly in
**small caps** and for *opportunistic* (non-routine) traders. The S&P 500 is all large caps,
where the effect is weakest, and many large-cap open-market buys are insiders buying into
declines (e.g. financials/energy in down years) that keep falling — dragging the mean negative.
The 5/20/60-day signs are inconsistent (noise), not a coherent negative edge.

## 10. Decision
`null` (development). **The HOLDOUT was not spent** — the construction failed to clear
development, so per the protocol there is no frozen procedure to confirm; 2020-2024 remains
naive for any future refinement. A fair test of the insider anomaly needs a small-/mid-cap
universe, which is out of scope for this S&P 500 pipeline. Does not spawn a follow-up here.
