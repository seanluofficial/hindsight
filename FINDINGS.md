# Findings

**One sentence:** across six pre-registered experiments — five testing for a tradeable signal,
one diagnostic — no signal survived out-of-sample, and the failures explain each other: the
market prices public information (8-K filings, earnings, even insider purchases) faster than a
late reader can exploit it. The most instructive result is 005 (post-earnings drift), which
*looked* like a genuine win on development — a 0.53-Sharpe long-only signal that survived costs
— and was then killed by the reserved holdout (−0.38): the single clearest demonstration of why
this platform is built the way it is. Experiment 006 (insider cluster-buying) — the candidate
with the best prior — was a development null, confirming the insider-buying edge is a small-cap
effect this S&P 500 universe cannot capture. (A separate branch, Reaction Gap, was deliberately
gated and never built — a branch you choose not to build is a decision, not a result.)

This is an honest measurement, not a trading system. A clean, well-explained null is the
intended deliverable.

---

## The research arc

Each experiment asks the question the previous one raised.

### 001 — Can an AI predict the move from the filing text?
Show a language model an 8-K with every clue to the company's identity and date stripped
out, and ask which way the stock will move.

**Finding:** about a coin flip (~52% directional accuracy at 5 days), no statistically
significant edge. *(Final number pending completion of the full DeepSeek scoring run; the
Loughran-McDonald dictionary baseline is likewise a null — negative Sharpe at every horizon
and cost level.)*

There is also a deeper problem the audit exposed: asked to name the issuer of an anonymized
filing, the model succeeded **38.7% of the time** — because filings *describe themselves*
("the largest publicly traded U.S. water utility…") and redaction defeats string-matching,
not comprehension. So even the coin flip is measured under contamination we cannot fully
remove. → *Why does the filing carry so little tradeable signal?*

### 002 — Does the type of event matter (no AI needed)?
Forget reading the text. Group filings by their SEC item code and ask whether high-impact
events (restatements, impairments) drift more *after filing* than routine ones.

**Finding:** near-null. Because entry is the next morning's open, the announcement reaction
is already excluded, and the leftover drift barely differs by event type (p ≈ 0.4–0.8). →
*If the reaction isn't after the filing, is it already gone before it?*

### 004 — Was the news already old by the time it was filed?
For each filing, split the abnormal move into the part that happened *before* the filing
reached EDGAR and the part *after*, around the event date.

**Finding:** the median filing already has **~47% of its move over before it can be traded.**
Broken down by event type, **earnings 8-Ks are the stalest (57%)** — the market trades the
earnings release and the 8-K merely formalizes it — and, as the largest category, they pull
the average up. Crucially, **no event type is cleanly "fresh"**: every class already has
~38%+ of its move gone by filing time. → *Maybe the signal isn't in the event but in how the
language changed?*

### 003 — Does new language beat boilerplate? ("Lazy Prices")
Published research shows that when companies *change* their annual-report language instead of
copy-pasting it, returns suffer. Test whether that transfers to 8-Ks: score how much each
filing changed from the company's own prior comparable filing (TF-IDF, vocabulary fit on the
development years only), then run a long-low-change / short-high-change portfolio.

**Finding:** null, and the sign is backwards. The portfolio loses money at every horizon
(20-day Sharpe −0.87 on the 2020–2024 partition — computed there, but not a clean
single-shot test; see `DEVIATIONS.md`). The effect does not transfer — most likely
because an 8-K's "prior comparable filing" is a far weaker analog than last year's 10-K is to
this year's.

### 005 — the informed follow-up: ride the drift instead of the reaction
The first four experiments share a diagnosis: they all try to predict the announcement
reaction from the filing's own text, entered at the next open, over 1–20 days — the part the
market prices fastest. So 005 changes the target. Post-earnings-announcement drift (PEAD) is a
decades-old, widely-replicated anomaly: after an earnings surprise, the stock keeps drifting the
same way for weeks. Using the market's own immediate reaction as the surprise (observable at
entry, no lookahead), we enter *after* the pop and hold a long-big-surprise / short-small-surprise
book for 20–60 days.

**Finding — a development win, killed by the holdout.** On development the pre-registered
long-only variant (PEAD is classically a long-side effect) **cleared the 0.30 materiality bar:
Sharpe 0.53, surviving even 25 bps of cost** — the first construction in the whole project to do
so. It looked like the success. But a year-by-year cut showed the edge was strong through 2016
and **negative in 2017–2019** — a decayed early-2010s effect. We froze that exact construction
and took the **single confirmatory holdout shot on 2020–2024: it came back −0.38 Sharpe** (and
−2.72 in 2024 alone). A 0.53 "win" on development became −0.38 out-of-sample.

This is the most valuable single result in the project, precisely because it is a null. The
machinery — a pre-registered construction, a materiality floor fixed in advance, and a holdout
reserved for one shot — did exactly what it is for: it caught a signal that would have looked
real in any ordinary backtest and proved it was a false discovery *before* anyone could act on
it. That is the difference between a research platform and a story.

### 006 — leave the filings entirely: do insiders' own purchases predict returns?
The first five experiments live inside the disclosure itself. 006 changes data sources: it
ingests 15 years of SEC **Form 4** insider transactions and tests the best-known "smart money"
signal — **cluster buying**, when ≥2 insiders buy their own stock on the open market within a
month. Entry is the next open after the Form 4 filing date (no lookahead); the point-in-time
S&P 500 universe and all costs carry over from the rest of the platform.

**Finding — a development null.** Across 1,349 cluster-buy events, the 20-day mean market-excess
return was **−37 bps (t −1.41, not significant)**, the long-only book scored **−0.18 Sharpe**,
and single-insider buys were flat (a clean check that the timing and sign are right). It failed
on development, so — following the discipline — **the 2020–24 holdout was left unspent.** This is
exactly the pre-registered headwind: the insider-purchase anomaly is documented mainly in
*small caps*, and in large-cap S&P 500 names — where many open-market buys are insiders catching
a falling knife — it is absent. The candidate with the best prior still didn't survive, honestly.

### Reaction Gap — the ambitious follow-up, deliberately not built
The idea: reconstruct when news *first* went public, estimate the reaction historically
comparable events produced, and test whether the *gap* between expected and observed reaction
predicts later drift. It needs data Hindsight does not have (intraday prices, news
timestamps), so it was **gated on Experiment 004** — build it only if some event class is
genuinely fresh at filing time. 004 found none. **Gate closed; branch stays on the shelf.**
The cheap experiment saved months of building on a shaky premise.

---

## What it all means

The first four results converge on one explanation: **8-K filings are, on average, confirmation
of news the market already has.** Roughly half the reaction predates the filing; the stalest and
largest category (earnings) predates it most; no event type beats the market to its own news;
and neither an AI reading the text nor a measure of how the text changed adds tradeable
signal on top. This is what an informationally efficient reaction to public disclosures looks
like — and measuring it honestly, four ways, is the result.

The fifth (005) adds a different kind of lesson. It went looking for a *known*, off-filing
anomaly — post-earnings drift — and found it clearly on development (0.53 Sharpe, long-only,
costed). That is exactly the moment a less careful project declares victory. Instead the
reserved holdout said −0.38, and the year-by-year decay explained why: the effect was real once
and has faded. The takeaway is not "PEAD is fake" — it is that **a signal is only what survives
out-of-sample**, and the value of the platform is that it can tell the difference.

The sixth (006) reinforces both lessons from a different angle: even the strongest textbook
signal — insiders buying their own stock — is a null once you demand it work *in this universe,
after costs, out-of-the-box*. The edge exists in the literature for small caps; the platform's
job was to check honestly whether it survives here, and it doesn't. Six experiments, zero
surviving signals — and each null pins down *why*, which is the actual contribution.

## Limitations (stated plainly)

- **Holdout discipline was partly spent.** 001–004 were computed across all years while their
  code was being built, so they are reported as in-sample, not as clean single-shot tests
  (see `DEVIATIONS.md`). A `--partition explore` flag now protects future experiments.
- **Daily prices, not intraday.** Staleness (004) is a coarse measure; the precise version is
  exactly what the (unbuilt) Reaction Gap branch would require.
- **Contamination.** The 38.7% issuer-identification rate is a lower bound (the audit ran on a
  smaller model than scoring), so 001's numbers are optimistic about the disguise.
- **Price coverage.** Returns are computed only for filings whose tickers have full price
  coverage; every exclusion is counted and reported, never silently dropped.
- **No multiple-testing "winner."** Nothing survived, so no family-wise correction was needed;
  had something looked significant, a Benjamini-Hochberg correction across the primary
  endpoints would apply before any discovery claim.

## What I would do next

1. **Finish 001** — complete the DeepSeek run and report the final directional accuracy,
   calibration (Brier), and quintile Sharpe, restricted to the filings the model could *not*
   identify (per the contamination rule).
2. **Test Lazy Prices where it belongs** — on 10-K/10-Q text, which this corpus does not yet
   contain. That is the fair venue for 003's hypothesis.
3. **Only then reconsider Reaction Gap**, and only with real intraday + first-disclosure data.

## Why this is the point

Surprisingly strong backtests on public data deserve skepticism, not celebration — lookahead
bias, survivorship bias, multiple testing, and unrealistic fills each manufacture convincing
false signals. Hindsight is built to make those mistakes hard:
point-in-time universe, next-open entry on a real trading calendar, mandatory costs,
pre-registered hypotheses with fixed pass/fail tests, and immutable predictions. The payoff of
that machinery is the ability to state a null and *believe it* — and to explain, mechanically,
why the signal isn't there. That is the deliverable.
