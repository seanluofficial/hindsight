# Experiment 007 — "Bury bad news" filing timing

> DRAFT → will be locked before the HOLDOUT shot. The cheapest experiment in the family: it
> reads no new data and calls no model. It reuses the acceptance timestamps already in the
> `filings` table and asks whether *when* a filing was released — chosen by the issuer —
> predicts its subsequent return. Pre-registered before any outcome on 2020-2024 is seen.

**Status:** `draft`
**Locked at (git SHA):** _____
**Primary endpoint:** 20-day, 10 bps mean market-excess return of **buried 8-Ks** (accepted in a
low-attention window — Friday after the 16:00 ET close, over a weekend, or the evening before a
market holiday), entered next open per §4, on HOLDOUT (2020-2024). One-sided H1: **negative**
(buried filings carry disproportionately bad, under-reacted news and drift down).

---

## 1. Hypothesis
- **Plain-English claim.** Managers can choose *when* to file. The "bury bad news" idea from the
  disclosure-timing literature (Patell & Wolfson 1982; Damodaran 1989; DellaVigna & Pollet 2009
  on Friday earnings; deHaan, Shevlin & Thornock 2015) is that unfavorable news is disproportionately
  released when investor attention is lowest — Friday afternoons, weekends, the eve of a holiday —
  to soften the immediate reaction. If attention is genuinely lower and the market under-reacts,
  the bad news is not fully priced at the next open, so buried filings should **drift down** over
  the following days relative to filings released in full view.
- **H0.** Buried 8-Ks have a 20-day mean market-excess return ≥ 0 and do not underperform the
  control group of attention-window filings.
- **H1.** Buried 8-Ks have a *negative* 20-day mean market-excess return that survives costs,
  underperform the control group, and a monthly short-buried book clears the 0.30 materiality
  floor after 10 bps.
- **Prior.** Weak-to-moderate, and honestly conflicted. The *content* skew is well documented
  (Friday/after-hours filings do carry worse news). But the sharper finance work
  (deHaan et al. 2015) argues the effect is closer to managers **hiding from complexity than from
  attention**, and finds only a muted, largely-arbitraged drift. Entry here is the *next open*,
  which already discards the announcement pop — so we are betting on residual post-open drift,
  the hardest part to capture. A null is the base case; the interesting outcome either way is a
  clean number.

## 2. Signal
No new data, no LLM. For each 8-K, take its `accepted_at_utc`, convert to America/New_York, and
classify the acceptance moment as **buried** if it lands in a low-attention window:
- **weekend dump** — accepted on a Friday at/after 16:00 ET, or any time Saturday/Sunday (all
  enter the *Tuesday* open, the longest attention gap in a normal week); or
- **pre-holiday dump** — accepted at/after 16:00 ET on a trading day with a market holiday before
  the next session (detected from the real NYSE calendar, not a weekday guess).

Everything else is the **control** group. The classification uses only the timestamp, which
exists at filing time, so there is no lookahead. Crucially, entry timing (§4) is applied
*identically* to both groups — a buried filing and an ordinary after-close filing both enter at
a skipped open — so the test isolates the *attention* channel, not the entry mechanic.
Secondary split: `weekend` vs `preholiday` sub-buckets, and an after-hours-matched control
(buried vs. Mon–Thu after-close) to net out the weekend-gap mechanic. Cost: ~$0.

## 3. Dataset (point-in-time)
Every 8-K already ingested (the `filings` table), 2010-2024, with price coverage. EXPLORE
2010-2019 to settle the buried-window definition; **HOLDOUT 2020-2024 for one confirmatory shot**
(`--partition holdout` only, per DEVIATIONS D-EXP1). Exclusions are the shared harness set
(no ticker price coverage, no prior close, prior close < $5, calendar edges), each counted.

## 4. Baseline
(a) The control group itself — do buried filings underperform ordinary ones, or is any negative
mean just the unconditional drift of the whole 8-K sample? (b) An after-hours-matched control
(Mon–Thu after-close filings), so a difference cannot be attributed to the skipped-open gap that
every after-close filing shares.

## 5. Primary endpoint & kill criteria
- **Primary.** 20-day, 10 bps mean market-excess return of buried 8-Ks on HOLDOUT, one-sample
  t-test vs 0 (one-sided, H1 negative), entry = next open per §4; plus the buried − control mean
  difference (Welch).
- **Kill criteria.** Buried mean ≥ 0, **or** the buried − control difference is not significant
  at BH-FDR q=0.10 across the family, **or** a monthly short-buried book fails the 0.30 Sharpe
  materiality floor after 10 bps → H1 not supported.
- **Secondary/exploratory.** 5- and 60-day horizons; weekend vs. pre-holiday sub-buckets;
  after-hours-matched control; a symmetry check on *good*-news item codes (the effect should be
  concentrated in bad-news filings if the attention story is right). Reported, not counted.

## 6. Robustness battery
Time stability (per year, pre/post-2020 — attention effects are widely reported to have decayed
as markets professionalised); cost sensitivity (0/10/25, plus the honest reminder that the
tradeable side is a **short** book with borrow cost, unlike 006's long-only); window-definition
sensitivity (Friday-after-close only vs. the full weekend/holiday composite); the after-hours
matched control; sub-bucket dominance. **All robustness is EXPLORE-only.**

## 7. Analysis plan
Classify every filing on EXPLORE, freeze the buried definition, then take the one HOLDOUT shot.
Event-study mean market-excess return (buried vs. control) at 5/20/60 days with the shared
harness timing; a monthly short-buried book for the materiality floor (equal-weight all buried
names in the trailing month, 20-day hold, monthly rebalance, return = −excess − cost). The short
leg carries borrow cost and is stated as such.

## 8. Results (EXPLORE / development only — HOLDOUT preserved)
100,559 8-Ks classified; **9,128 buried** (8,754 weekend, 374 pre-holiday). After the shared
exclusions, 3,708 buried / 38,318 control filings are evaluable on EXPLORE at 20 days.

Event study (market-excess, next-open entry):

| horizon | group | n | mean excess | median | t |
|---|---|---|---|---|---|
| 5d | buried | 3,741 | −4.3 bps | −1.4 | −0.76 |
| 5d | control | 38,460 | +1.2 bps | −3.1 | +0.70 |
| **20d** | **buried** | **3,708** | **−17.4 bps** | +3.4 | **−1.57** |
| 20d | control | 38,318 | +6.4 bps | +1.0 | +2.00 |
| 60d | buried | 3,673 | −4.7 bps | +18.7 | −0.24 |
| 60d | control | 37,850 | −6.8 bps | −0.7 | −1.22 |

Buried − control difference (Welch): 5d −5.5 bps (t −0.94, p 0.35); **20d −23.8 bps (t −2.06,
p 0.039)**; 60d +2.1 bps (t +0.11, p 0.92). Bucket cut (20d): **weekend −16.9 bps, pre-holiday
−29.0 bps, control +6.4 bps**, and an after-hours-matched Mon–Thu control is ~flat (+1.9 bps,
t 0.40) — so the effect tracks *attention*, not the skipped-open gap every after-close filing
shares. Materiality short-buried book (EXPLORE, 20d, 10 bps): **Sharpe 0.22**, mean monthly
+0.11%, max drawdown 16.6% over 120 months.

**The direction is right and statistically detectable, but the effect is not economically
material.** Buried 8-Ks underperform by ~24 bps over 20 days (p ≈ 0.04 on development), yet the
tradeable short book scores only 0.22 Sharpe — below the 0.30 floor, and before the borrow cost a
real short would pay.

## 9. Failure analysis
This is the cleanest "statistically significant but not tradeable" result in the family. The
*content* skew the literature documents is visibly present — managers do release worse news into
low-attention windows, and it does drift down — but two things cap the economic size. (a) Entry
is the next open, so the announcement reaction is already gone; only residual drift is left, and
~24 bps of it over a month does not clear costs. (b) Buried filings are ~9% of the sample and
cluster on Fridays, so the short book is thin and lumpy (120 monthly buckets, 16.6% drawdown),
depressing the Sharpe even where the mean is negative. The 5/60-day horizons are noise; the
signal is a 20-day phenomenon, consistent with a slow-attention-correction story rather than a
persistent risk premium. The p ≈ 0.04 difference is a single endpoint that would still face the
family-wise (BH-FDR) correction — but it does not get that far, because it fails the economic
gate first.

## 10. Decision
`null` (development) — **H1 not supported on the materiality gate.** The direction and the
difference test pass on development, but the short-buried book fails the 0.30 Sharpe floor
(0.22), so the two-gate rule (significance **and** materiality) is not cleared. Per the protocol,
a construction that fails development is **not** taken to the HOLDOUT: **2020-2024 remains
unspent** and naive for any future refinement. The honest takeaway is not "bury-bad-news is
fake" — it is measurably real — but "measurably real" and "tradeable after costs" are different
bars, and this clears only the first. A fairer tradeable test would need a lower-cost venue
(e.g. options around buried filings) or intraday entry, both out of scope for this daily-bar,
next-open pipeline.
