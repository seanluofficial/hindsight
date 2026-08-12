# Experiment 010 — Cross-sectional momentum, whole-market / small-cap

> DRAFT → locked before the HOLDOUT shot. B-track: after nine signal experiments found no
> tradeable edge, this is a deliberate test of the *most persistent* documented anomaly, in the
> universe where it is strongest (small caps), using the price data acquired for 009. A brand-new
> signal, so its 2020-2024 holdout is clean. Pre-registered before any outcome is seen.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day (≈1-month) hold, 10 bps, quintile long/short **Sharpe** on the
12-1 momentum signal, whole-market universe, on HOLDOUT (2020-2024). H1: positive.

---

## 1. Hypothesis
- **Plain-English claim.** Stocks that went up over the past year (skipping the most recent
  month) keep outperforming the ones that went down, for a while — cross-sectional momentum
  (Jegadeesh-Titman 1993). It is the most replicated anomaly in equities and is stronger in
  smaller, less-arbitraged names.
- **H0.** The 12-1 momentum quintile long/short has a 20-day/10bps Sharpe ≤ 0.30 on HOLDOUT.
- **H1.** Positive and clears the 0.30 materiality floor after costs.
- **Prior.** The best of any experiment in this project — momentum has survived 30+ years of
  out-of-sample scrutiny across markets. **Honest caveats, pre-stated:** (a) it is heavily
  arbitraged in liquid names, so the edge concentrates in small caps where *our costs are
  worst* (25 bps is the honest read); (b) momentum **crashes** (2009, 2020) — sharp reversals
  that wreck the long/short exactly in rebounds; (c) a "win" here is a known factor surviving,
  not discovered alpha. A null after realistic costs is very plausible and would itself be an
  honest, useful result.

## 2. Signal
For each stock at each monthly formation date, **12-1 momentum** = the return from ~12 months
ago to ~1 month ago (skip the most recent month to avoid short-term-reversal contamination),
computed from adjusted daily closes: `adj_close[t−21] / adj_close[t−252] − 1`. All prices used
are ≥ 21 trading days before formation, so the signal is strictly point-in-time. No new data —
reuses the whole-market prices ingested for 009. Cost ≈ $0.

## 3. Dataset (point-in-time)
Every ticker in the `prices` table (whole market, ~4,900 names incl. delisted, retained by the
vendor — survivorship-safe). Monthly formation on the last trading day of each month; entry the
next open, hold 20 trading days, market-excess vs. SPY. EXPLORE 2010-2019 to fix the exact
construction; **HOLDOUT 2020-2024 for one confirmatory shot**; FORWARD 2025+ reported
separately. Exclusions (counted): missing formation/entry/exit price, prior close < $5.

## 4. Baseline
The unconditional universe return (does ranking on momentum beat holding everything?), and a
1-month **short-term reversal** signal (buy losers) as the opposite-sign control — momentum
and reversal should point opposite ways at these horizons.

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps quintile L/S annualized Sharpe on HOLDOUT; H1 positive.
- **Kill criteria.** Sharpe < 0.30 after 10 bps, or not distinguishable from 0 at BH-FDR
  q=0.10 across the family, or negative → H1 not supported. Also reported at 25 bps (the honest
  small-cap cost) — an effect that dies between 10 and 25 bps is flagged as fragile.
- **Secondary/exploratory.** 5- and 60-day holds; long-only (top quintile) vs. the short leg;
  size and liquidity subgroups; a momentum-crash diagnostic (performance in market rebounds).

## 6. Robustness battery
Time stability (per year; does it survive 2020's crash-and-rebound?); cost sensitivity
(0/10/25); the reversal control (§4); long-only vs. long/short (small-cap shorts have borrow
constraints, so the long-only Sharpe is the realistically tradeable one); quintile-count
sensitivity. **All robustness EXPLORE-only**; HOLDOUT is a single frozen shot. 010 joins the
multiple-testing family (PROTOCOL §3).

## 7. Analysis plan
Build monthly quintile L/S on EXPLORE via the shared harness (next-open entry, market-excess,
mandatory costs), freeze the construction, take the one HOLDOUT shot, then report FORWARD.
Overlapping-window-aware SEs. The long-only leg is the tradeable object given small-cap borrow.

## 8. Results (EXPLORE / development — HOLDOUT preserved)
6,345 tickers, 108 monthly formations (2010-2019).

**Primary (20-day hold):** quintile L/S Sharpe **0.16 at 10 bps, −0.18 at 25 bps**; long-only
−0.37. **H1 not supported at the pre-registered horizon** — a one-month hold sits near the
short-term-reversal zone and is a poor construction for momentum (an honest pre-registration
mistake).

**Secondary (longer holds, exploratory):**

| hold | L/S Sharpe (10 bps) | L/S Sharpe (25 bps) | long-only Sharpe (10 bps) |
|---|---|---|---|
| 60-day | 0.74 | 0.51 | −0.73 |
| 120-day | 0.88 | 0.71 | −1.14 |

At 60-120-day holds the **long/short book clears the materiality bar even at 25 bps** — the first
construction in the project to do so on development at realistic cost. **But the entire edge is
in the short leg:** the long-only (winners) Sharpe is strongly *negative*. The book only works by
shorting small-cap losers — the least-borrowable, highest-fee names, whose true short cost the flat
bps model badly understates.

## 9. Failure analysis
The pre-registered 20-day primary is a null. The longer-hold L/S "win" is a short-side artifact:
in the small-cap universe, high-momentum names are lottery/pump stocks that reverse (negative long
leg) and low-momentum names crash (profitable but un-borrowable short leg). It is the project's
recurring lesson with a fresh mechanism — looks tradeable, isn't, this time because of short-borrow
constraints rather than spread (007) or survivorship (009).

## 10. Decision
`null` at the pre-registered primary (20-day); HOLDOUT preserved. The longer-hold L/S finding is a
**development-only, short-side, not-retail-tradeable** result, logged honestly, not claimed as a
survivor. It could be re-pre-registered as its own experiment (60-day L/S) with a clean single
holdout shot — but even a survivor there would be a borrow-constrained, known factor, not
discovered alpha. Momentum joins the family; nothing tradeable survived.
