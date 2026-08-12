# hindsight

A **contamination-resistant research platform** for testing whether public market data carries
tradeable information — and, more importantly, for *honestly measuring* when it does not.

It began by asking whether an LLM can predict returns from an SEC 8-K it isn't allowed to
identify (the name is that thesis: the model was trained on the outcomes, so *hindsight*
contamination is the central threat). It grew into **ten pre-registered experiments** on a full
**EXPLORE → HOLDOUT → live-FORWARD** design. None produced a signal that survives out-of-sample
after costs — and the value is in *how* they fail: **two "wins" caught by the reserved holdout**
(post-earnings drift; small-cap insider buying, which also failed a live 2025+ forward test), and
**three distinct real-world costs** that each kill a small-cap backtest — the bid-ask **spread**
(007), **survivorship** (009), and **short-borrow** (010, momentum). The deliverable is an honest
measurement, not a profitable bot.

- **[`FINDINGS.md`](FINDINGS.md) — the written narrative: ten pre-registered experiments, no
  surviving signal, and the mechanisms behind each failure. Start here.**
- [`experiments/`](experiments/README.md) — the research platform: pre-registered hypotheses,
  the holdout architecture, and the multiple-testing alpha budget ([`PROTOCOL.md`](experiments/PROTOCOL.md)).
- [`PREREGISTRATION.md`](PREREGISTRATION.md) — the specification. Locked. It wins any disagreement.
- [`CLAUDE.md`](CLAUDE.md) — build brief, invariants, architecture.
- [`DEVIATIONS.md`](DEVIATIONS.md) — append-only log of departures and open questions.
- [`ROADMAP.md`](ROADMAP.md) — what remains, and an honest read on whether this can make money.

**Live dashboard:** https://hindsight-hpunstepzzu536epfhsjwz.streamlit.app

## Status

**Phases 1, 2 and 4 run end-to-end on a 500-filing pilot.** The LLM half of Phase 2 is
written but unrun — it needs an `ANTHROPIC_API_KEY`.

| | |
|---|---|
| Point-in-time universe | 886 intervals, 501–506 members per study year |
| 2018 8-K filings | 6,720 across 501 tickers, mean 13.4 per company |
| 2018 prices | 156,987 rows, 512/530 tickers, SPY complete at 251 sessions |
| Filings joinable to prices | 97.6% |
| Anonymized | 6,720, zero lexical leaks, ~124 redactions per filing |
| Scored (dictionary) | 6,720 by the Loughran-McDonald baseline |
| Scored (LLM) | 84 by `openai/gpt-oss-120b` — halted by a free-tier daily token cap |
| Contamination audit | 150 filings, **38.7% identified** |
| Evaluated | 19,614 trades across 3 horizons × 3 cost levels, 13 monthly rebalances |

Exclusion accounting reconciles exactly: 6,835 in-universe filings = 6,720 stored + 107
accepted outside the 04:00–20:00 ET window (§3) + 8 with no acceptance timestamp.

### Headline result — the disguise fails 38.7% of the time

The contamination audit is the number that decides what everything else means. Asked to
name the issuer of an anonymized filing, the model got it right on **58 of 150 (38.7%)** —
nearly double the 20% threshold fixed in §6 before any code was written.

It succeeds because **filings describe themselves**, and no amount of name-redaction
touches that:

| Actual | Guessed | The clue it used |
|---|---|---|
| AWK | American Water Works | "largest publicly traded U.S. water and wastewater utility, over 6,800 employees" |
| DAL | Delta Air Lines | "Atlanta airport power outage", "Trainer refinery", "profit sharing for pilots" |
| MOS | Mosaic | "phosphate and potash operations", "Vale S.A.", "TIPLAM port" |
| ORLY | O'Reilly Automotive | "leading retailer in the automotive aftermarket, 5,000+ stores" |
| AGN | Allergan | named subsidiary "Forest Laboratories, LLC" |

The anonymizer removes names, tickers, dates, addresses, executives and cities, and it does
that well — zero lexical leaks across 6,720 filings. But it cannot remove *self-description*
without destroying the content being analysed. **Redaction defeats string matching, not
comprehension.**

§6 fixed the consequence in advance: above 20%, the primary analysis must be restricted to
filings the model failed to identify, and both versions reported. That rule now binds.

**This measured rate is a lower bound.** Free-tier quotas forced the audit onto an 8B model
while scoring used a 120B one, and a smaller model recognises fewer companies. The real
contamination of the scored predictions is worse than 38.7%.

### The lexicon baseline is a null, and a costly one

Full-year 2018: 6,720 filings scored, **19,614 evaluable trades**, 13 monthly rebalances.

**The dictionary has no directional skill and loses money after costs.** Every horizon and
every cost level is negative:

| horizon | 0 bps | 10 bps (base) | 25 bps |
|---|---|---|---|
| 1 day | −1.49 | **−3.86** | −7.42 |
| 5 days | −1.02 | **−1.28** | −1.68 |
| 20 days | −1.07 | **−1.25** | −1.53 |

*Annualized Sharpe, quintile long/short, market-excess.*

Against the pre-registered §14 threshold — 5-day Sharpe below 0.3 after 10 bps — the
verdict is **H1 not supported**. Directional hit rate is 48.5% at 1 day and 49.6% at
20 days, against a 50% null.

Note the 1-day row: costs dominate at short horizons, which is exactly why §10 forbids
presenting results cost-free alone.

**Overconfident, with the gap widening as confidence rises** — the pattern H2 predicts for
the LLM, here in the baseline (20-day horizon):

| stated confidence | n | realised | gap |
|---|---|---|---|
| 0.50–0.60 | 2,959 | 0.493 | +0.055 |
| 0.60–0.70 | 1,713 | 0.508 | +0.136 |
| 0.70–0.80 | 925 | 0.498 | +0.245 |
| 0.80–0.90 | 494 | 0.496 | +0.347 |
| 0.90–1.00 | 430 | 0.467 | **+0.504** |

At its most confident the dictionary is right 46.7% of the time. Read the *calibration* as
a property of the arbitrary score→probability mapping rather than a claim about the
dictionary; the mapping is monotonic, so it cannot affect H1 or H3. The *hit rate* is not
arbitrary — it depends only on the sign.

Brier ≈ 0.292, worse than the 0.25 an always-say-0.50 forecaster scores.

This is the comparator H3 measures the LLM against. Phases 3, 5, 6, 8 not started; see the
build order in `CLAUDE.md`.

## Dashboard

```bash
uv run streamlit run src/hindsight/dashboard/app.py
```

Research, Track record and Today. Research leads with sample size, anonymization counts and
sample-size warnings *before* any performance figure, then calibration, then returns at
every horizon and cost level, then the full exclusion ledger.

The working database is ~95MB and the raw filing cache ~2.8GB, so neither is deployable.
`scripts/export_results.py` writes a ~700KB bundle of evaluated trades plus a summary
stamped with its git SHA, and the dashboard reads that when no database is present — both
paths build identical `Trade` objects, so figures are computed by the same code either way.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
cp .env.example .env      # then fill in TIINGO_API_KEY
```

Two credentials matter:

| Variable | Why |
|---|---|
| `HINDSIGHT_EDGAR_CONTACT` | SEC requires a User-Agent with real contact info. Requests without one are throttled, then blocked. |
| `TIINGO_API_KEY` | Price data. Free key at [tiingo.com](https://www.tiingo.com/account/api/token). |

## Running stage 1

```bash
# Reconstruct point-in-time S&P 500 membership and freeze it to data/sp500_membership.csv
uv run python scripts/run_ingest.py universe --rebuild

# Crawl the EDGAR full index and ingest in-universe 8-Ks
uv run python scripts/run_ingest.py filings --year 2018            # whole year
uv run python scripts/run_ingest.py filings --year 2018 --quarter 1 --limit 25   # smoke test

# Daily OHLC + SPY benchmark
uv run python scripts/run_ingest.py prices --year 2018

# Row counts and coverage
uv run python scripts/run_ingest.py status
```

Every fetch is cached under `data/raw/`, so re-running never refetches and a crashed crawl
resumes where it stopped. Every run writes a manifest to `data/manifests/` recording the
git SHA, parameters, row counts, and **every exclusion with its reason** — invariant 5 says
nothing is silently dropped, so dropping something requires naming a reason.

## Checks

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src scripts
```

## Two things worth knowing about the data

**EDGAR acceptance timestamps are Eastern, not UTC.** The archive header records
`<ACCEPTANCE-DATETIME>20180201163017` for a filing the submissions API reports as
`2018-02-01T21:30:17Z`. Reading it as UTC would shift every event five hours and move
filings across the 16:00 ET cutoff in §4 without raising anything. Ingest converts once, at
the boundary; everything downstream is UTC.

**Prices are stored raw, with `adj_close` alongside.** Returns must not mix the two — a
2-for-1 split between entry and exit would read as −50%. Use
`prices.adjustment_factor(close, adj_close)` to recover adjusted values.

## Layout

```
src/hindsight/
  config.py            # every constant a result depends on
  db.py                # five-table SQLite schema; predictions immutable by trigger
  manifest.py          # run provenance and exclusion accounting
  trading_calendar.py  # real NYSE sessions — a weekday is not a trading day
  ingest/
    http.py            # rate-limited, disk-cached fetcher
    universe.py        # point-in-time S&P 500 membership
    edgar.py           # full-index crawl, header parsing, EX-99 extraction
    prices.py          # Tiingo daily OHLC + benchmark
scripts/run_ingest.py
tests/
```

The four pipeline stages are independently runnable and communicate only through SQLite.

## License

MIT — see [LICENSE](LICENSE).
