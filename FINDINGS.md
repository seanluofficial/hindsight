# Findings

**One sentence:** across nine pre-registered experiments — eight testing for a tradeable signal,
one diagnostic — no signal cleared both the significance and the materiality gate, and the
failures explain each other: the market prices public information (8-K filings, earnings, insider
purchases, the timing of disclosure, and one firm's news reaching its peers) faster than a late
reader can trade it. Two experiments looked like wins on development and were then killed by their
reserved holdouts — 005 (post-earnings drift): 0.53 Sharpe → −0.38; and 009 (small-cap insider
buying): +65 bps/20d → **−128 bps**, a full sign reversal. Those two catches are the single
clearest demonstration of why this platform is built the way it is: a signal is only what survives
out-of-sample. Experiment 006 (insider cluster-buying) was a development null in the S&P 500, which
*motivated* 009's small-cap test. Experiment 007 ("bury bad news" timing) is the subtlest: buried
filings *do* underperform, detectably (−24 bps vs control over 20 days, p ≈ 0.04) — but the short
book scores only 0.22 Sharpe, a textbook significant-but-not-economic result. Experiment 008 (peer
lead-lag) is the methodological bookend: a 60-day peer effect *looks* significant (t ≈ 4) until you
notice it double-counts thousands of correlated peers, and the honest monthly book is negative.
(A separate branch, Reaction Gap, was deliberately gated and never built — a branch you choose not
to build is a decision, not a result.)

This is an honest measurement, not a trading system. A clean, well-explained null is the
intended deliverable.

---

## The research arc

Each experiment asks the question the previous one raised.

### 001 — Can an AI predict the move from the filing text?
Show a language model an 8-K with every clue to the company's identity and date stripped
out, and ask which way the stock will move.

**Finding (final):** a coin flip. Across 5,000 anonymized filings (DeepSeek, temperature 0),
directional hit rate is **49.9% / 51.2% / 49.8%** at 1 / 5 / 20 days, and the 5-day quintile
long/short Sharpe is **+0.14 after 10 bps** — below the pre-registered null threshold, so **H1 is
not supported (§14)**. The calibration is the revealing part: the model is **overconfident by
~0.08 (Brier 0.263)**, and its reliability curve is flat — when it states 80%+ confidence it is
right about half the time. It reads fluently and predicts nothing. *(The Loughran-McDonald
dictionary baseline is likewise a null — negative Sharpe at every horizon and cost level.)*

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

### 007 — do managers who file when nobody's watching get away with it?
006 left the filings for a different data source; 007 comes back to the filings but asks a new
question of them — not *what* was disclosed but *when*. Issuers choose their filing time, and the
disclosure-timing literature says bad news is disproportionately dumped into low-attention windows
(Friday afternoons, weekends, holiday eves). 007 flags every 8-K accepted in such a window as
**buried** and tests whether buried filings drift down relative to filings released in full view.
Entry is the next open for both groups, so the test isolates *attention*, not the entry mechanic.

**Finding — significant on development, but not economically material.** Buried 8-Ks underperform
at 20 days (**−17 bps** on their own; **−24 bps versus the control group, Welch t −2.06,
p ≈ 0.039**), the direction the hypothesis predicted, and the bucket cut is coherent (weekend
−17 bps, pre-holiday −29 bps, control +6 bps, after-hours-matched control flat). This is the
first construction to *clear the statistical gate on development.* But the tradeable object — a
monthly short-buried book — scores only **0.22 Sharpe after 10 bps**, below the 0.30 floor, on a
thin, lumpy book (buried filings are ~9% of the sample and cluster on Fridays; 16.6% drawdown).
So it fails the **economic** gate, and — per the two-gate rule — **the holdout was left unspent.**
The lesson is precise: an effect can be real and detectable and still not worth trading once you
demand it survive costs at daily-bar, next-open resolution. "Statistically significant" and
"tradeable" are different bars; 007 clears the first and not the second.

### 008 — does one firm's news move its industry peers next?
007 asked about the *timing* of a filing; 008 asks about its *reach*. An 8-K is partly news
about a whole industry, and if that information diffuses slowly to related firms, a filer's peers
should drift in the same direction as the filer over the following days (industry lead-lag,
economic-link momentum). Mapping every issuer to its SIC industry, 008 signs each peer's return
by the filer's own reaction and enters the peers at the next open — and doubles as a stress test
of the platform's statistics, because same-industry peers are heavily correlated.

**Finding — a development null, and the clearest overlap lesson in the project.** The 20-day
signed peer return is a coin flip (**+1.4 bps, t 0.97**, hit rate 50.7%). One cell looks like a
discovery — the 60-day event-level t-stat is **3.99** — but it pools **173,000 peer pairs that
are massively cross-correlated** (every filing in an industry trades the same handful of names),
so its standard error is far too small to believe. The pre-registered fix is to collapse the
overlap into a **monthly long/short book** — one observation per month — and there the effect is
**negative: −0.17 Sharpe.** The apparent signal was an artifact of double-counting. In a
universe of large-cap S&P 500 names, industry news is priced across peers *together*, not with a
tradeable lag; the small-cap, supply-chain venue where the effect lives is out of scope here.
The holdout was left unspent.

### 009 — insider buying where the edge is supposed to live, done properly
006 found no insider-buying edge in the S&P 500; the literature places that edge in *small caps*,
which the S&P universe excludes by construction. So 009 acquired whole-market daily prices and
reran the identical signal on **31,360 cluster buys across ~6,900 tickers** (23× the S&P sample),
with a survivorship-safe, EDGAR-filer-defined universe. This is the one experiment a *prior*
experiment's failure analysis explicitly aimed — the best-prior candidate in the family — and it
was worked the full, disciplined way: build on development, refine, freeze, one holdout shot.

**Finding — the sharpest false-discovery catch in the project.** On development the blunt signal
was already the first positive, significant primary (+40 bps/20d, t 4.76), confirming the size-split
mechanism (absent in large caps, present in small). Refining it the way the literature prescribes —
*opportunistic* insiders only (dropping routine, calendar-clockwork buyers), a $50k conviction
floor, and a proper overlapping portfolio — **strengthened it to +65 bps/20d and lifted the book to
0.30 Sharpe, clearing the materiality bar.** It was, on development, the project's best result. We
froze that exact recipe and took the single holdout shot on 2020–2024: it **reversed to −128 bps
(t −5.43), monthly Sharpe −0.34.** A convincing, literature-backed, decade-strong signal was
negative out-of-sample.

There is a second lesson buried in 009. One variant — a *daily-rebalanced* book — reported a
positive holdout Sharpe (+0.40), contradicting everything else. It was **discarded, not reported**:
the daily construction skips missing price days, so a small-cap that craters and delists silently
drops its worst days — survivorship bias (invariant 2) re-entering through the construction itself.
The survivorship-safe measures (event-study mean, monthly book) are the verdict, and they say the
signal failed. Catching that artifact *before* it became a false headline is exactly the platform's
job.

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
job was to check honestly whether it survives here, and it doesn't.

The seventh (007) adds the final distinction the project needed: the difference between
*statistical* and *economic* significance. Buried filings genuinely underperform — the effect is
there, in the right direction, at p ≈ 0.04 — and a project with a single significance test would
have called it a discovery. The materiality floor is what stops that: a 0.22-Sharpe short book is
not a signal you can trade, however real the underlying drift. Requiring a construction to clear
*both* gates — significance and materiality — before it may even touch the holdout is exactly
what keeps a true-but-tiny effect from being oversold.

The eighth (008) closes the loop on the statistics themselves. Its headline peer effect is a
coin flip, but one horizon throws a t-stat near 4 — and a project that read that number at face
value would have declared a discovery and spent its holdout on noise. The reason it is noise is
overlap: the "independent" observations are thousands of correlated peers reacting to the same
industry news. Because the overlap correction (a monthly book) was fixed *in advance*, the honest
answer — a negative Sharpe — was never in doubt. Eight experiments, zero signals clearing both
gates — and each null pins down *why*, which is the actual contribution.

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

1. **001 is complete** (5,000 filings: coin flip, H1 not supported). The remaining refinement is
   to re-cut it *restricted to the filings the model could not identify* (per the contamination
   rule) — the audit ran on a smaller model, so the current number is a mild upper bound on the
   disguise's leakiness, not on the edge.
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
