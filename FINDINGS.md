# Findings

**One sentence:** across four pre-registered experiments — three testing for a tradeable
signal, one diagnostic — the market appears to price the information in an 8-K *before the
filing is even public*, so there is little left for a model — AI or otherwise — to predict
from the filing itself. No signal survived, and the nulls explain each other. A fifth
experiment (005), designed *from* that diagnosis, is the first to come out the right way —
post-earnings drift — and is still under test. (A separate branch, Reaction Gap, was
deliberately gated and never built — a branch you choose not to build is a decision, not a
result.)

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

### 005 — the informed follow-up: ride the drift instead of the reaction (in progress)
The first four experiments share a diagnosis: they all try to predict the announcement
reaction from the filing's own text, entered at the next open, over 1–20 days — the part the
market prices fastest. So 005 changes the target. Post-earnings-announcement drift (PEAD) is a
decades-old, widely-replicated anomaly: after an earnings surprise, the stock keeps drifting the
same way for weeks. Using the market's own immediate reaction as the surprise (observable at
entry, no lookahead), we enter *after* the pop and hold a long-big-surprise / short-small-surprise
book for 20–60 days.

**Finding (development, holdout reserved):** the first real signal — with an honest asterisk.
The long/short book is weak (20-day Sharpe 0.14), but the *pre-registered long-only variant* —
PEAD is classically a long-side effect — **clears the 0.30 materiality bar (Sharpe 0.53, and
still 0.31 at 25 bps costs)**, the first construction in the whole project to do so. The catch is
decay: a year-by-year cut shows the long-only edge was strong through 2016 and then **negative in
2017, 2018 and 2019**. The pooled number is carried by the early 2010s. So the reserved 2020–2024
holdout inherits a *fading* signal, and the honest prior is that it will be weak. This is a
genuine lead — the platform's best — but a right-signed, decaying development result is exactly
the kind of thing that must survive a single clean out-of-sample test before it is called a
discovery. That test is not yet spent.

### Reaction Gap — the ambitious follow-up, deliberately not built
The idea: reconstruct when news *first* went public, estimate the reaction historically
comparable events produced, and test whether the *gap* between expected and observed reaction
predicts later drift. It needs data Hindsight does not have (intraday prices, news
timestamps), so it was **gated on Experiment 004** — build it only if some event class is
genuinely fresh at filing time. 004 found none. **Gate closed; branch stays on the shelf.**
The cheap experiment saved months of building on a shaky premise.

---

## What it all means

The four results converge on one explanation: **8-K filings are, on average, confirmation of
news the market already has.** Roughly half the reaction predates the filing; the stalest and
largest category (earnings) predates it most; no event type beats the market to its own news;
and neither an AI reading the text nor a measure of how the text changed adds tradeable
signal on top. This is what an informationally efficient reaction to public disclosures looks
like — and measuring it honestly, four ways, is the result.

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
