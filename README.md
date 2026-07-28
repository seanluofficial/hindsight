# hindsight

Can a large language model extract predictive signal from SEC 8-K filings **when it cannot
identify the company or the date?**

The name is the thesis. The model was trained on data that includes the outcomes of the
events it is being asked to predict, so contamination by hindsight is the central threat,
and every design decision defends against it. The deliverable is an honest measurement —
including a null result — not a profitable trading system.

- [`PREREGISTRATION.md`](PREREGISTRATION.md) — the specification. Locked. It wins any disagreement.
- [`CLAUDE.md`](CLAUDE.md) — build brief, invariants, architecture.
- [`DEVIATIONS.md`](DEVIATIONS.md) — append-only log of departures and open questions.

## Status

**Phase 1 (foundation) — filings done, prices pending a Tiingo key.**

| | |
|---|---|
| Point-in-time universe | 886 membership intervals, 501–506 members per study year |
| 2018 8-K filings | 6,720 across 501 tickers, mean 13.4 per company |
| 2018 prices | **not yet ingested** — needs `TIINGO_API_KEY` |

Exclusion accounting for 2018 reconciles exactly: 6,835 in-universe filings = 6,720 stored
+ 107 accepted outside the 04:00–20:00 ET window (§3) + 8 with no acceptance timestamp.

Phases 2–8 not started; see the build order in `CLAUDE.md`.

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
