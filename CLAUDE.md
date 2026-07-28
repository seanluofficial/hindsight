# hindsight — build brief

Read `PREREGISTRATION.md` before writing any code. It is the specification. Where this file and the pre-registration disagree, the pre-registration wins.

## What this project is

A research pipeline testing whether an LLM can extract predictive signal from SEC 8-K filings when it cannot identify the company or date. The deliverable is an honest measurement — including a null result — not a profitable trading system.

**The name is the thesis.** Contamination by hindsight is the central threat: the model was trained on data that includes the outcomes of the events it is being asked to predict. Every design decision defends against that.

## Non-negotiable invariants

These are the difference between a real experiment and a broken one. Violating any of them silently invalidates all results.

1. **No lookahead.** Nothing that did not exist at the filing's acceptance timestamp may influence a prediction or an entry price. Entry is always the *next* open per the timing rules in §4 of the pre-registration.
2. **No survivorship bias.** Universe membership is point-in-time. Delisted and acquired companies must remain in the sample for the period they were members.
3. **Anonymization is enforced, not assumed.** The scorer refuses to send text that has not passed the anonymizer. The contamination audit is part of the pipeline, not an afterthought.
4. **Deterministic reproducibility.** Temperature 0, pinned model ID, versioned prompts, fixed random seeds. Given the same database, a rerun must produce identical numbers.
5. **Nothing is silently dropped.** Every exclusion is counted and reported. Parse failures, missing prices, empty filings — all logged with reasons and surfaced in the results.
6. **Costs are never optional.** Any function returning performance metrics takes a cost parameter with no default that equals zero.

## Architecture

Four stages, independently runnable, communicating through SQLite. Do not merge them.

```
hindsight/
  PREREGISTRATION.md
  CLAUDE.md
  DEVIATIONS.md          # append-only log of departures from pre-registration
  pyproject.toml
  data/
    hindsight.db         # gitignored
    raw/                 # gitignored: cached filings
    lm_dictionary.csv    # Loughran-McDonald, committed
  src/hindsight/
    config.py            # paths, constants, cost levels, horizons
    db.py                # schema, connection, migrations
    ingest/
      edgar.py           # full-index crawl, filing fetch, EX-99 extraction
      prices.py          # daily OHLC + SPY benchmark
      universe.py        # point-in-time S&P 500 membership
    score/
      anonymize.py       # identifier stripping + verification
      prompt.py          # versioned prompt templates
      llm.py             # scoring client, retry, strict JSON parsing
      lexicon.py         # Loughran-McDonald baseline
    evaluate/
      returns.py         # entry timing, market-excess returns
      portfolio.py       # quintile long/short, cost application
      calibration.py     # Brier, reliability bins
      robustness.py      # the pre-specified splits
    dashboard/
      app.py             # Streamlit: Today / Track Record / Research
  scripts/
    run_ingest.py
    run_score.py         # --mode historical|live --limit N
    run_evaluate.py
    audit_contamination.py
  tests/
```

## Storage schema

Five tables. Predictions are immutable once written — corrections are new rows with a new `prompt_version`, never updates.

- `filings` — accession_no (PK), cik, ticker, accepted_at_utc, period_of_report, item_codes, raw_path, anonymized_text, anon_version
- `universe` — ticker, cik, start_date, end_date
- `prices` — ticker, date, open, high, low, close, adj_close, volume
- `predictions` — id, accession_no, model_id, prompt_version, direction, probability, rationale, raw_response, created_at, run_mode ('historical'|'live')
- `evaluations` — prediction_id, horizon, entry_date, exit_date, raw_return, excess_return, cost_bps, net_return

## Conventions

- Python 3.11+, `uv` for dependencies. pandas, numpy, requests, pydantic, streamlit, pytest.
- All timestamps stored UTC; all market-hours logic uses `zoneinfo` America/New_York with a real NYSE trading calendar (`pandas_market_calendars`). Never assume weekdays are trading days.
- Pydantic models for LLM output. Reject and retry on schema violation; never coerce.
- Structured logging to file. Every run writes a manifest: git SHA, timestamp, parameters, row counts in and out.
- EDGAR requires a descriptive `User-Agent` header with contact info and rate limits to 10 requests/second. Respect both; cache every fetch to `data/raw/` so a rerun never refetches.
- Type hints everywhere. `ruff` and `mypy` clean.

## Testing priorities

Test the things that fail silently. Correctness bugs here don't crash — they produce plausible wrong numbers.

- **Timing.** A filing accepted at 15:59 ET enters next open; at 16:01 ET it enters the open after that. Test both sides, plus Friday evening, plus the day before a holiday.
- **Anonymization.** Given filings with known company names in headers, footers, and mid-sentence, assert zero leakage.
- **Universe.** A company that left the index in 2016 must appear in 2014 samples and not in 2018 samples.
- **Returns.** Hand-compute a known example and assert the pipeline matches.
- **Costs.** Assert net return is strictly below gross return for any nonzero cost.

## Build order

Do not skip ahead. Each phase ends with something verifiable.

**Phase 1 — foundation.** Config, DB schema, EDGAR ingest for a single quarter, price ingest, point-in-time universe. Done when: filings and prices for 2018 are queryable and counts are sane.

**Phase 2 — scoring, small.** Anonymizer with tests, prompt v1, LLM client with strict parsing, lexicon baseline. Run on **500 filings only**. Done when: 500 predictions stored, API cost per filing measured and reported, anonymization spot-checked by hand.

**Phase 3 — contamination audit.** Ask the model to identify the issuer on those 500. Report the rate. Done when: the number is known and written into the eventual results. If it is high, tighten the anonymizer and rerun before proceeding.

**Phase 4 — evaluation.** Returns with correct entry timing, quintile portfolios, costs, Brier score, reliability bins. Run on the 500-filing pilot. Done when: a reliability diagram exists.

**Phase 5 — full historical run.** Scale to 2010–2024. Checkpoint and resume; a crash at filing 20,000 must not lose the first 19,999. Done when: the full results table is populated.

**Phase 6 — robustness.** Every split in §12 of the pre-registration. Done when: all are reported, including unflattering ones.

**Phase 7 — dashboard.** Streamlit, three tabs. Research tab first — it is the one that matters. Done when: deployed at a public URL.

**Phase 8 — live.** Poll EDGAR for new filings on a schedule, score through the identical code path, write with `run_mode='live'`. Done when: predictions accumulate automatically and the Track Record tab updates itself.

## Working style

- Ask before deviating from the pre-registration. If a deviation is genuinely necessary, append it to `DEVIATIONS.md` with the date and reason.
- Prefer boring, readable code over clever code. This will be read by an interviewer.
- When a result looks good, get suspicious and look for the leak. Strong backtest results are usually bugs.
- Commit at each phase boundary with a message describing what is now verifiable.