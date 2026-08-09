# Roadmap

Two goals, and they pull in different directions more often than people admit:

1. **Profit** — a signal that survives costs out of sample.
2. **Credential** — evidence of quant and engineering judgement that a hiring manager can verify in ten minutes.

The honest position: **the credential is close, the profit is not.** This document says so
plainly and then lays out what would move each.

---

## Where the project actually stands

| | |
|---|---|
| Ingest, anonymization, evaluation, dashboard | built, tested, reproducible |
| Historical coverage | 2018 only, of a pre-registered 2010–2024 |
| Dictionary baseline | 6,720 filings, hit rate 50.2%, Sharpe −1.42 after costs |
| LLM | 84 filings — one month, not interpretable for returns |
| Contamination | 38.7% identified, versus a 20% pre-set limit |
| Robustness splits (§12) | specified, not run |
| Live out-of-sample (§15) | not started |

The binding constraint has never been engineering, and it is **not money either** — see C1.
It is throughput: free API tiers allow ~100 filings/day, and a local model ~1,700/day. The
fix is to stop trying to score all ~100,000 filings and sample ~5,000 instead, which is
statistically equivalent for every hypothesis in the pre-registration.

**Budget for everything below: $0.**

---

## The honest read on profit

**Public 8-K sentiment is close to fully mined.** Reacting to an 8-K on a next-open entry
competes with people who trade it in milliseconds. The current design cannot win that race
and should not pretend to.

Three things would have to be true for this to make money, and only the third is realistic:

1. *The signal is real and unexploited* — unlikely for plain sentiment.
2. *We are faster than the competition* — we are not; entry is the next open by design.
3. **We are measuring something others do not bother to measure** — plausible.

That third door is where the remaining ideas live.

### P1. Surprise, not sentiment — the biggest missing input

Returns respond to news **relative to expectation**, not to whether news is good. "Revenue
up 12%" is bullish or bearish entirely depending on whether the street expected 10% or 15%.
This project currently has no expectation anchor at all, which alone could explain a null.

Cheap proxies that need no paid consensus data:

- The company's own prior guidance, extracted from the previous 8-K or 10-Q.
- Trailing four-quarter growth as the naive expectation.
- The pre-announcement drift in the stock over the prior 5–20 days.

**Effort:** medium. **Payoff:** the single highest-expected-value change here, and it makes
the null result far more interesting either way, because "no signal *even conditioning on
surprise*" is a much stronger statement than the current one.

### P2. Predict volatility instead of direction

Direction is close to a coin flip for almost everyone. **Magnitude is far more predictable** —
some 8-K types reliably move a stock, regardless of which way. That is tradeable through
options (straddles), and it is a far easier target.

**Effort:** medium, and this is the one idea with a real cost attached — free options
history is scarce. Defer it until the free work is exhausted. **Payoff:** genuinely the
most likely route to a positive result in this repo.

### P3. Condition on item type

Item 2.02 (earnings), 5.02 (executive departure) and 1.01 (material agreement) have
different return dynamics. Pooling them averages real signal against noise. Item codes are
already stored and unused.

**Effort:** low — one groupby. **Payoff:** modest, but it is already half-built and is a
pre-registered robustness split (§12) regardless.

### P4. Post-earnings announcement drift

PEAD is one of the most replicated anomalies in finance: prices under-react to earnings
surprises and drift for weeks. The 20-day horizon is already implemented. Combined with
P1's surprise measure, this is a documented effect rather than a hopeful one.

**Effort:** low once P1 exists. **Payoff:** the most defensible profit hypothesis available.

> **Anything from P1–P4 is a new hypothesis and must be pre-registered before it is run,
> in a new dated section of `PREREGISTRATION.md`, with its own null threshold.** Testing
> them against the existing data and reporting the winner is exactly the practice this
> project was built to demonstrate the absence of.

---

## The credential track — higher certainty, lower cost

These do not need a profitable result. Several are *stronger* without one.

### C1. Finish the pre-registered study (Phases 5–6) — **do this first, and it is free**

Scale to 2010–2024 and run every §12 robustness split: market-cap terciles, three time
periods, item type, and the contamination-excluded subset.

**Cost: $0.** An earlier draft of this file put it at $60–210. That was wrong, and the
correction matters enough to record:

**Prices are free.** Tiingo's free tier caps *unique symbols per month*, not requests or
date ranges — and a single request returns a symbol's entire 2010–2024 history. The whole
study needs ~886 symbols, so it is two months of free quota, not a subscription. 512 are
already stored.

**Scoring is free, and the real currency is patience.** Two routes, both measured on this
machine rather than estimated:

| Route | Throughput | 5,000 filings | Notes |
|---|---|---|---|
| Groq free tier, `gpt-oss-120b` | ~100/day (200k tokens/day) | ~50 nights | Strongest free model; unattended nightly job |
| Local Ollama, `qwen2.5:3b` | ~52 s/filing | ~72 hours | Unlimited, offline, no quota at all |

**And the study does not need 100,000 filings.** That number came from a census instinct,
not from a power calculation. To detect a 2-point edge over a coin flip at 80% power needs
**~4,900 observations**; a 3-point edge needs ~2,180. A *stratified random sample* of ~5,000
filings across 2010–2024 answers every pre-registered hypothesis with essentially the same
power as scoring all 100,000, at 5% of the effort.

Sampling is only legitimate if it is fixed in advance: the stratification (by year and item
type), the target size, and the seed all go into `PREREGISTRATION.md` **before** the run.

**Why first:** "I pre-registered a study, ran it across 15 years, and reported that my
hypothesis failed across every subgroup" is a *better* interview story than a suspicious
positive. It also closes the sample-size caveat currently attached to every LLM number.

**One caution on the local route.** In a 3-filing smoke test, `qwen2.5:3b` returned
`up @ 0.75` on all three. That may be coincidence at n=3, but a model that answers
identically regardless of input has no signal to measure and would produce a null for
trivial reasons. Check output variance on ~50 filings before committing 72 hours to it, and
prefer a 7–8B model if the machine tolerates the slowdown.

### C2. Statistical rigour

Currently missing, and a quant interviewer will notice within minutes:

- Bootstrapped confidence intervals on Sharpe and hit rate.
- Newey–West standard errors — overlapping 20-day holds violate independence, so the
  current t-statistics are overstated.
- Deflated Sharpe ratio, which explicitly corrects for the number of specifications tried.
- A disclosed count of every specification run (§13 already requires this).

**Effort:** low. **Payoff:** disproportionately high. This is the difference between
"built a backtest" and "knows why most backtests are wrong."

### C3. Live paper trading (Phase 8)

Poll EDGAR on a schedule, score new filings through the identical code path, write with
`run_mode='live'`, and let the Track Record tab fill up.

**Why it matters most:** a live, timestamped, out-of-sample record that nobody could have
fitted after the fact is the single most credible artifact in quantitative work. Six months
of it — *even if flat* — beats any backtest.

**Effort:** medium. **Start it early**, because its value is measured in elapsed calendar
time, not in hours worked.

### C4. Fix the contamination finding properly

38.7% is currently the headline, and the obvious follow-up questions have good answers
available:

- Re-run scoring and audit on **one** model, ideally a frontier one, removing the D15 caveat.
- Report the primary analysis restricted to unidentified filings, as §6 requires.
- Try a **semantic** anonymizer: have a model rewrite each filing into industry-generic
  language, then re-audit. Whether identification falls is a genuinely publishable result.

**Effort:** medium. **Payoff:** this is the most distinctive thing the project has. It is a
finding about the limits of anonymization for LLM evaluation, and it generalises well beyond
finance — the same trap sits under every "we held out this data" claim about a model trained
on the internet.

### C5. Engineering surface

Cheap signals that a SWE screener reads directly off the repo:

- CI on GitHub Actions running ruff, mypy and pytest on every push.
- A coverage badge.
- Dockerfile plus `docker compose up` for one-command reproduction.
- The dashboard deployed at a public URL (bundle is already committed and ready).
- A short architecture diagram in the README.

**Effort:** low, a few hours total. **Payoff:** high per hour spent.

---

## Suggested order

| Phase | Work | Cost | Why here |
|---|---|---|---|
| 1 | C5 engineering surface, C3 live trading started | $0 | Cheap; C3's value accrues with calendar time, so start the clock immediately |
| 2 | C1 sampled 2010–2024 run + §12 splits | $0, ~50 nights unattended | Closes every sample-size caveat at once |
| 3 | C2 statistical rigour | $0 | Small effort, largest credibility gain |
| 4 | C4 contamination follow-up | $0 | Turns the headline into a defensible result |
| 5 | P1 surprise measure, pre-registered | $0 | The only profit idea likely to change the answer |
| 6 | P4 drift | $0 | Builds on P1 |
| 7 | P2 volatility | needs options data | The only item here worth paying for, and only after the rest |

---

## What "done" looks like

- A pre-registered study run over 15 years, reported with its unflattering subgroups intact.
- A live out-of-sample record accumulating in public.
- A contamination result that says something real about evaluating models trained on the internet.
- A repo that a stranger can clone, run, and reproduce to the number.

**Note that none of those require the strategy to work.** That is the point, and it is worth
stating in the interview before anyone asks: the deliverable was always an honest
measurement. If a profitable signal turns up along the way, it will be believable precisely
because the machinery that found it was built to try to kill it.
