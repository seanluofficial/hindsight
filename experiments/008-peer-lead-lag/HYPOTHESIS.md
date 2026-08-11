# Experiment 008 — Peer / lead-lag information diffusion

> DRAFT → will be locked before the HOLDOUT shot. The last drafted candidate in the family.
> It reads one new, cheap dataset (SEC SIC industry codes, one JSON per issuer) and otherwise
> reuses the shared price harness. Pre-registered before any outcome on 2020-2024 is seen.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day, 10 bps mean **signed peer market-excess return** — the peer's
return times the sign of the filer's own reaction — for 3-digit-SIC industry peers, peers
entered the next open *after* the filer's entry day, on HOLDOUT (2020-2024). One-sided H1:
**positive** (news diffuses; peers drift in the filer's direction).

---

## 1. Hypothesis
- **Plain-English claim.** An 8-K is partly news about a company and partly news about its
  industry. If investors are slow to propagate industry-relevant information to *related* firms,
  then when a filer's stock reacts to its 8-K, its industry peers should drift the same way over
  the following days — a lead-lag effect. This is the filing-triggered version of documented
  anomalies: industry momentum (Moskowitz & Grinblatt 1999), industry lead-lag from
  slow information diffusion (Hou 2007), and returns predictability along economic links
  (Cohen & Frazzini 2008).
- **H0.** The mean signed peer return (peer return × sign of filer reaction) is ≤ 0 at 20 days.
- **H1.** It is positive, survives costs, and a monthly long/short peer book clears the 0.30
  materiality floor.
- **Prior.** Weak-to-moderate. The effect is real in the literature, but (a) it is strongest in
  *small, neglected* firms and along specific supply-chain links, whereas this universe is
  large-cap S&P 500 names that are heavily co-traded and arbitraged; (b) peers within an
  industry are highly correlated, so a naive test overstates significance — addressed below. A
  null, or a significant-but-immaterial result like 007, is entirely plausible.

## 2. Signal
Peers are defined from **SEC SIC industry codes** (`data/industry.csv`, one submissions-API
JSON per issuer; the code is a stable issuer attribute, not a return-derived quantity, so it
does not look ahead). The primary grouping is the **3-digit SIC**; 2-digit is a robustness
widening. For each 8-K:
1. **Filer reaction** = the filer's market-excess return from the prior close to its entry-day
   close E (the reaction to the filing), fully known at E's close.
2. **Peers** = other point-in-time universe members sharing the filer's 3-digit SIC (frozen
   `universe` table, no survivorship), entered at the **next open after E** so the filer's
   reaction is already public — no lookahead, no simultaneity.
3. **Signal per peer** = sign(filer reaction) × peer market-excess return over H days. Positive
   means the peer followed the filer. No LLM. Cost: ~600 tiny JSON fetches (cached), ~$0.

## 3. Dataset (point-in-time)
All 8-Ks 2010-2024 as trigger events; peers restricted to point-in-time S&P 500 members with
price coverage. EXPLORE 2010-2019 to settle the peer definition and horizon; **HOLDOUT
2020-2024 for one confirmatory shot** (`--partition holdout` only, per DEVIATIONS D-EXP1).
Exclusions, each counted: filer/peer without price coverage, no prior close, prior close < $5,
filer in a singleton SIC group (no peers), calendar edges.

## 4. Baseline
The unconditional (unsigned) peer market-excess return over the same window — a peer basket
should be ~flat in excess terms, so any positive *signed* mean must come from the alignment
with the filer's reaction, not from a drifting market. Reported alongside the headline.

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps mean signed peer return on HOLDOUT, one-sample t vs 0 (one-sided,
  H1 positive), peers entered the next open after E.
- **Kill criteria.** Mean ≤ 0, or not significant at BH-FDR q=0.10 across the family, **or** the
  monthly long/short peer book fails the 0.30 Sharpe materiality floor after 10 bps → H1 not
  supported.
- **Secondary/exploratory.** 5- and 60-day horizons; 2-digit SIC; up-filers vs. down-filers
  separately (diffusion may be asymmetric); high-impact item codes only. Reported, not counted.

## 6. Robustness battery
Time stability (per year, pre/post-2020); cost sensitivity (0/10/25, and the reminder the book
is long/short with borrow cost on the short leg); SIC granularity (3- vs 2-digit); **the overlap
correction** — because industry peers are highly correlated, event-level t-stats are
anticonservative, so the materiality decision rests on the *monthly* long/short series (one
observation per month), not the event-level t. **All robustness is EXPLORE-only.**

## 7. Analysis plan
Build events on EXPLORE, freeze the peer construction, then take the one HOLDOUT shot. Event
study of the signed peer return at 5/20/60 days; a monthly long/short peer book (long peers of
up-filers, short peers of down-filers, 20-day hold, cost on each leg) for the materiality floor.
The monthly series is the primary defence against the within-industry overlap.

## 8. Results (EXPLORE / development only — HOLDOUT preserved)
42,250 trigger events built (156 3-digit-SIC groups). Signed peer return
(sign(filer reaction) × peer market-excess):

| horizon | events | peer pairs | mean signed | event-level t | hit rate |
|---|---|---|---|---|---|
| 5d | 30,839 | 177,510 | +0.01 bps | +0.01 | 50.0% |
| **20d** | 30,827 | 176,409 | **+1.40 bps** | **+0.97** | 50.7% |
| 60d | 30,764 | 173,044 | +9.73 bps | +3.99 | 50.6% |

Materiality (monthly long/short peer book, EXPLORE, 20d, 10 bps): **Sharpe −0.17**, mean monthly
−0.04%, 121 months.

**H1 not supported on development.** The 20-day mean is barely positive (+1.4 bps) and
insignificant even by the anticonservative event-level t; the hit rate is a coin flip. The one
"significant"-looking cell — 60-day, t 3.99 — is exactly the overlap artifact §6 warned about:
it pools 173k peer pairs that are massively cross-correlated (every filing in an industry trades
the same names), so its standard error is far too small. **The moment the correlated peers are
collapsed into a monthly long/short series — one observation per month — the effect is
negative (Sharpe −0.17), not positive.** The overlap correction turns an apparent discovery into
a null. The unsigned baseline is implicitly ~flat (hit rate 50%, near-zero signed mean), so
there is no alignment between the filer's reaction and its peers' subsequent drift to trade.

## 9. Failure analysis
The pre-registered headwind held. Industry lead-lag and economic-link predictability are
documented in *small, neglected* firms and along specific supply-chain pairs; in a universe of
large-cap S&P 500 names — co-traded, index-arbitraged, covered by the same analysts — same-industry
peers move together *contemporaneously*, leaving no exploitable lag. The event-level 60-day
t-stat is a cautionary example of why the protocol fixes the overlap correction *in advance*: a
naive reading would have called it a discovery and spent the holdout on noise. The materiality
book, which is the honest object, is negative after costs.

## 10. Decision
`null` (development) — **H1 not supported.** The primary 20-day mean is insignificant and the
monthly long/short book fails the 0.30 floor (−0.17). The only significant-looking horizon is an
artifact of correlated-peer overlap, which the monthly aggregation removes. Per the protocol, a
construction that fails development is **not** taken to HOLDOUT: **2020-2024 remains unspent.** A
fair test of lead-lag diffusion needs a small-/mid-cap universe and an explicit economic-link
graph (customers/suppliers), both out of scope for this S&P 500, SIC-only pipeline.
