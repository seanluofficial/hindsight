# Hindsight — research platform

Hindsight is not one strategy. It is a **reusable, contamination-resistant research platform**
for asking whether public information in SEC filings carries signal about subsequent returns —
and, more importantly, for *honestly measuring* when it does not.

The engine is already built: 100k+ point-in-time 8-K filings, 1.58M price observations,
point-in-time S&P 500 membership, lookahead-free entry timing on a real NYSE calendar,
market-excess returns, costed quintile portfolios, calibration, an enforced anonymizer, and
reproducible manifests. Each experiment below is a new **signal** plugged into that same
evaluation harness — not a new pipeline.

The discipline is the product. Read **[`PROTOCOL.md`](PROTOCOL.md)** first: it defines the
staged progression (hypothesis → EXPLORE → untouched HOLDOUT → robustness → FORWARD), the
holdout architecture, and — the part that matters most — the **multiple-testing alpha budget**
that keeps "we ran eight strategies and one worked" from masquerading as a discovery.

## How to run an experiment

1. Copy [`HYPOTHESIS_TEMPLATE.md`](HYPOTHESIS_TEMPLATE.md) to `NNN-slug/HYPOTHESIS.md`.
2. Fill it out and **commit before looking at any outcome.** The commit is the timestamp.
3. Develop and estimate on EXPLORE (2010-2019).
4. Freeze the procedure; run it **once** on HOLDOUT (2020-2024).
5. Run the robustness battery. Fill in Results and Failure analysis.
6. Update the registry row below, including the primary p-value for the family-wise correction.

## Experiment registry

The **family** for multiple-testing correction is the set of `primary endpoint` cells below.
Benjamini-Hochberg FDR at q = 0.10 is applied across them **once, at the end**. Abandoned
experiments stay in the table — every test counts.

| # | Title | Primary endpoint | Status | HOLDOUT result | Primary p |
|---|---|---|---|---|---|
| 001 | LLM analysis of anonymized 8-Ks → abnormal returns | 5-day, 10bps quintile L/S Sharpe (full sample; holdout already spent) | `running` | ~coin flip (pending full run) | — |
| 002 | Event-type conditional returns | 5-day, 10bps high-impact−routine mean-excess difference (HOLDOUT) | `exploratory` | near-null (+1.9 bps, p 0.83) | 0.83 |
| 003 | Filing novelty / linguistic change vs. prior filings ("Lazy Prices") | 20-day, 10bps quintile L/S Sharpe on change-score (HOLDOUT) | `exploratory` | null, wrong sign (Sharpe −0.87) | — |
| 004 | Information staleness / first-disclosure (**diagnostic**) | Median staleness fraction > 0.5 on HOLDOUT (not a trading endpoint) | `exploratory` | ~47% (H1 not supported) | — |
| 005 | Post-earnings-announcement drift (PEAD) | 20-day, 10bps quintile L/S Sharpe on the surprise signal (HOLDOUT) | `null` (holdout spent) | long-only 0.53 on dev → **−0.38 on holdout**; H1 not supported (decayed effect, caught out-of-sample) | −0.86 (t) |
| 006 | Insider cluster-buying (Form 4) | 20-day, 10bps mean market-excess of cluster-buy events (HOLDOUT) | `null` (dev; **holdout reserved**) | dev −37 bps / Sharpe −0.18; H1 not supported (small-cap effect, absent in large caps) | −1.41 (t) |

**Read the narrative:** [`../FINDINGS.md`](../FINDINGS.md). 001–005 are in-sample (see
`../DEVIATIONS.md` D-EXP1); 006 failed on development so its holdout was left unspent. Nothing
survived, so no family-wise correction was needed.

Planned but not yet drafted (kept here so the family is declared up front, not discovered —
see `PROTOCOL.md` §3): "bury bad news" filing-timing (007, cheap, reuses 004 staleness);
peer/lead-lag information diffusion (008). Subgroup conditioning (size/sector/regime) is a
**robustness dimension**, not a standalone experiment — see `PROTOCOL.md` §4.

### Major branch — gated, not yet started

**Hindsight / Reaction Gap.** The bigger follow-up: reconstruct when news *first* became
public, estimate the reaction that historically comparable events produced, and test whether
the *gap* between expected and observed reaction predicts subsequent drift. It is a research
*branch*, not a one-file experiment: it needs infrastructure Hindsight does **not** have yet —
news-wire / IR timestamps for true first-disclosure, and intraday prices for the immediate
reaction. **It is explicitly gated on Experiment 004:** we do not invest in that data
pipeline until staleness confirms the premise (that 8-Ks are frequently late and *which* event
types are freshest). If 004 says the filing is usually the first look, Reaction Gap loses its
motivation and is not built.

## The honest pitch

The goal is not a profitable bot. It is to run a family of pre-registered experiments, attack
each one, correct for the fact that we ran several, and report what survives — including, and
especially, when nothing does.
