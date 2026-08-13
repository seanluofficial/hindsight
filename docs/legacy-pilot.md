# The 2018 pilot (superseded)

This records the first end-to-end run: a single study year, 6,720 filings, and an LLM
scoring pass that stopped at 84 predictions when a free-tier token cap was hit. It is kept
because the exclusion accounting and the dictionary baseline were computed here first, and
because the reasoning that led to the final design is more legible with the starting point
visible.

**None of these numbers describe the current state of the project.** The final run covers
2010–2024 with 100,559 filings and a completed DeepSeek scoring pass. See
[`../FINDINGS.md`](../FINDINGS.md) for current results and [`../README.md`](../README.md)
for current scale.

## Pilot scale

| | |
|---|---|
| Point-in-time universe | 886 intervals, 501–506 members per study year |
| 2018 8-K filings | 6,720 across 501 tickers, mean 13.4 per company |
| 2018 prices | 156,987 rows, 512/530 tickers, SPY complete at 251 sessions |
| Filings joinable to prices | 97.6% |
| Anonymized | 6,720, zero lexical leaks, ~124 redactions per filing |
| Scored (dictionary) | 6,720 by the Loughran-McDonald baseline |
| Scored (LLM) | 84 by `openai/gpt-oss-120b` — halted by a free-tier daily token cap |
| Evaluated | 19,614 trades across 3 horizons × 3 cost levels, 13 monthly rebalances |

Exclusion accounting reconciles exactly: 6,835 in-universe filings = 6,720 stored + 107
accepted outside the 04:00–20:00 ET window (§3) + 8 with no acceptance timestamp.

## The dictionary baseline, computed on the pilot

Full-year 2018: 6,720 filings scored, 19,614 evaluable trades, 13 monthly rebalances. The
dictionary has no directional skill and loses money after costs — every horizon and every
cost level is negative:

| horizon | 0 bps | 10 bps (base) | 25 bps |
|---|---|---|---|
| 1 day | −1.49 | **−3.86** | −7.42 |
| 5 days | −1.02 | **−1.28** | −1.68 |
| 20 days | −1.07 | **−1.25** | −1.53 |

*Annualized Sharpe, quintile long/short, market-excess.*

Against the pre-registered §14 threshold — 5-day Sharpe below 0.3 after 10 bps — the verdict
is **H1 not supported**. Directional hit rate is 48.5% at 1 day and 49.6% at 20 days,
against a 50% null. Note the 1-day row: costs dominate at short horizons, which is exactly
why §10 forbids presenting results cost-free alone.

This null survived into the final run, where the dictionary remains negative at every
horizon and cost level.

## Calibration on the pilot

Overconfident, with the gap widening as confidence rises — the pattern H2 predicts for the
LLM, here in the baseline (20-day horizon):

| stated confidence | n | realised | gap |
|---|---|---|---|
| 0.50–0.60 | 2,959 | 0.493 | +0.055 |
| 0.60–0.70 | 1,713 | 0.508 | +0.136 |
| 0.70–0.80 | 925 | 0.498 | +0.245 |
| 0.80–0.90 | 494 | 0.496 | +0.347 |
| 0.90–1.00 | 430 | 0.467 | **+0.504** |

At its most confident the dictionary is right 46.7% of the time. Read the *calibration* as a
property of the arbitrary score→probability mapping rather than a claim about the
dictionary; the mapping is monotonic, so it cannot affect H1 or H3. The *hit rate* is not
arbitrary — it depends only on the sign. Brier ≈ 0.292, worse than the 0.25 an
always-say-0.50 forecaster scores.

The same overconfidence appeared in the final LLM run: Brier 0.263, reliability curve flat,
right about half the time when stating 80%+ confidence.
