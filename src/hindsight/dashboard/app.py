"""Streamlit dashboard: Research, Track Record, Today.

Research comes first because it is the tab that matters. The deliverable is an honest
measurement, so the page leads with what would falsify the thesis — the contamination
rate, the exclusion ledger, the sample-size caveats — rather than with a return number.

Run locally:
    uv run streamlit run src/hindsight/dashboard/app.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hindsight import config, db  # noqa: E402
from hindsight.evaluate import calibration, portfolio, returns  # noqa: E402
from hindsight.manifest import RunManifest  # noqa: E402

st.set_page_config(page_title="hindsight", page_icon="🔍", layout="wide")

LEXICON_PREFIX = "loughran-mcdonald"


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """A fresh, short-lived SQLite connection.

    Deliberately NOT cached across reruns. Streamlit serves each interaction on a worker
    thread, and a SQLite connection may only be used on the thread that created it — a
    cached connection raises `ProgrammingError` the moment a second thread touches it.

    Opening per call is cheap here because every reader is wrapped in `st.cache_data`, so
    the queries run once per cache window rather than once per rerun.
    """
    conn = db.connect()
    try:
        db.migrate(conn)
        yield conn
    finally:
        conn.close()


@st.cache_data(ttl=300)
def table_counts() -> dict[str, int]:
    with connection() as conn:
        return db.table_counts(conn)


@st.cache_data(ttl=300)
def available_models() -> list[str]:
    with connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT model_id, COUNT(*) n FROM predictions GROUP BY model_id ORDER BY n DESC"
            )
        ]


@st.cache_data(ttl=300)
def anonymized_count() -> int:
    with connection() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM filings WHERE anon_version IS NOT NULL").fetchone()[
                0
            ]
        )


RESULTS_DIR = config.DATA_DIR / "results"


def has_database() -> bool:
    return config.DB_PATH.exists()


def bundled_models() -> list[str]:
    """Models present in the committed results bundle."""
    out = []
    for path in sorted(RESULTS_DIR.glob("summary_*.json")):
        out.append(json.loads(path.read_text(encoding="utf-8"))["model_id"])
    return out


@st.cache_data(ttl=300)
def load_trades(model_id: str) -> list[returns.Trade]:
    """Trades from the database when present, otherwise from the committed bundle.

    The deployed dashboard has no database — it is ~95MB and the filing cache is ~2.8GB —
    so the hosted build reads the exported bundle. Both paths produce identical `Trade`
    objects, so every figure downstream is computed the same way.
    """
    if has_database():
        manifest = RunManifest("dashboard", model_id=model_id)
        with connection() as conn:
            return returns.evaluate_all(conn, model_id, manifest)

    safe = model_id.replace("/", "_")
    path = RESULTS_DIR / f"trades_{safe}.csv.gz"
    if not path.exists():
        return []
    records: list[dict[Hashable, Any]] = pd.read_csv(path).to_dict("records")
    return [
        returns.Trade(
            prediction_id=int(r["prediction_id"]),
            accession_no=str(r["accession_no"]),
            ticker=str(r["ticker"]),
            direction=str(r["direction"]),
            probability=float(r["probability"]),
            horizon=int(r["horizon"]),
            entry_date=date.fromisoformat(str(r["entry_date"])),
            exit_date=date.fromisoformat(str(r["exit_date"])),
            raw_return=float(r["raw_return"]),
            benchmark_return=float(r["benchmark_return"]),
            excess_return=float(r["excess_return"]),
        )
        for r in records
    ]


@st.cache_data(ttl=300)
def bundled_summary(model_id: str) -> dict[str, Any]:
    path = RESULTS_DIR / f"summary_{model_id.replace('/', '_')}.json"
    if not path.exists():
        return {}
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@st.cache_data(ttl=300)
def filings_overview() -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(
            """
            SELECT substr(accepted_at_utc, 1, 7) AS month,
                   COUNT(*) AS filings,
                   COUNT(DISTINCT ticker) AS tickers
              FROM filings GROUP BY month ORDER BY month
            """,
            conn,
        )


@st.cache_data(ttl=300)
def live_predictions() -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(
            """
            SELECT p.created_at, f.ticker, p.direction, p.probability, p.rationale
              FROM predictions p JOIN filings f ON f.accession_no = p.accession_no
             WHERE p.run_mode = 'live' ORDER BY p.created_at DESC LIMIT 200
            """,
            conn,
        )


@st.cache_data(ttl=300)
def evaluation_exclusions(model_id: str) -> list[tuple[str, int]]:
    manifest = RunManifest("dashboard-exclusions", model_id=model_id)
    with connection() as conn:
        returns.evaluate_all(conn, model_id, manifest)
    return manifest.exclusions.most_common()


# --------------------------------------------------------------------------
# Research tab
# --------------------------------------------------------------------------
@st.cache_data(ttl=300)
def contamination_results() -> list[dict[str, Any]]:
    """Every contamination audit found in the results directory."""
    out: list[dict[str, Any]] = []
    for path in sorted(RESULTS_DIR.glob("contamination_*.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def render_contamination() -> None:
    """The number that decides what the whole study measures."""
    audits = contamination_results()
    st.subheader("Can the AI still tell who filed it?")
    st.caption(
        "The central threat. These models were trained on data that already contains what "
        "happened next, so a model that recognises the company can recall the outcome "
        "instead of forecasting it. We ask it to name the issuer and count how often it "
        "gets there anyway."
    )
    if not audits:
        st.info(
            "Contamination audit not run yet — `python scripts/audit_contamination.py`. "
            "This is the headline limitation of the whole project, so results are "
            "provisional until it exists."
        )
        return

    for audit in audits:
        rate = audit["identification_rate"]
        threshold = audit["threshold"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Identified the company", f"{rate:.1%}")
        c2.metric("Pre-set limit", f"{threshold:.0%}")
        c3.metric("Filings tested", f"{audit['attempted']:,}")

        if audit["exceeds_threshold"]:
            st.error(
                f"**Above the {threshold:.0%} limit.** The rule written before the study "
                "began requires the main analysis to be re-run on only the filings the "
                "model failed to identify, and both versions reported. That rule was "
                "fixed in advance precisely so it could not be waived once inconvenient."
            )
        else:
            st.success(
                f"**Below the {threshold:.0%} limit**, so the main analysis stands on the "
                "full sample. The rate is still reported as a headline limitation — "
                "'mostly disguised' is not 'disguised'."
            )

        hits = [r for r in audit["results"] if r["correct"]]
        if hits:
            with st.expander(f"See {len(hits)} filings it identified, and how"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "actual": h["true_ticker"],
                                "its guess": h["guess_company"],
                                "confidence": h["confidence"],
                                "clues it used": h["reasoning"],
                            }
                            for h in hits[:60]
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )


def render_head_to_head(models: list[str]) -> None:
    """H3: does the LLM beat a dictionary that does no reading comprehension?"""
    if len(models) < 2:
        return
    st.subheader("AI versus a word-counting dictionary")
    st.caption(
        "The pre-registration predicts the AI will *not* meaningfully beat a method that "
        "just counts positive and negative words with no comprehension at all. Both read "
        "identical text, so this compares readers rather than inputs."
    )

    rows = []
    for model_id in models:
        trades = load_trades(model_id)
        if not trades:
            continue
        cal = calibration.evaluate(trades, 5)
        base = portfolio.build(trades, 5, float(config.BASE_CASE_COST_BPS))
        if not cal.n:
            continue
        rows.append(
            {
                "method": model_id,
                "predictions": cal.n,
                "hit rate": cal.observed_frequency,
                "beats coin flip": "yes" if cal.observed_frequency > 0.5 else "no",
                "Brier (lower better)": cal.brier_score,
                "overconfidence": cal.overconfidence,
                "Sharpe after costs": base.sharpe_annualized,
                "profitable": "yes" if base.mean_return > 0 else "no",
            }
        )
    if not rows:
        return
    st.dataframe(
        pd.DataFrame(rows).style.format(
            {
                "hit rate": "{:.1%}",
                "Brier (lower better)": "{:.4f}",
                "overconfidence": "{:+.3f}",
                "Sharpe after costs": "{:+.2f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "All figures at the 5-day horizon after 10 bps round-trip costs. Sample sizes "
        "differ: the dictionary is free to run so it scored every filing, while the AI "
        "was capped by free-tier API limits."
    )


def plain_english_verdict(
    cal: calibration.CalibrationResult, base: portfolio.PortfolioResult, model_id: str
) -> None:
    """The finding, in words, before any jargon.

    Someone reading this should be able to tell what happened without knowing what a
    Sharpe ratio is. The technical tables stay below for people who do.
    """
    hit = cal.observed_frequency
    beats_coin = hit > 0.5
    makes_money = base.mean_return > 0

    st.subheader("What this found, in plain English")

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Right this often",
        f"{hit:.1%}",
        delta=f"{(hit - 0.5) * 100:+.1f} points vs a coin flip",
        delta_color="normal" if beats_coin else "inverse",
    )
    c2.metric(
        "After trading costs",
        "Loses money" if not makes_money else "Makes money",
        delta=f"{base.mean_return:+.2%} per month",
        delta_color="normal" if makes_money else "inverse",
    )
    c3.metric(
        "When it says it's sure",
        f"{cal.bins[-1].observed_frequency:.0%} right" if cal.bins else "n/a",
        delta="but claims ~97% confidence",
        delta_color="inverse",
    )

    verdict = (
        "**It does not beat a coin flip.**"
        if not beats_coin
        else "**It edges past a coin flip** — but see the costs and sample size below."
    )
    st.markdown(
        f"""
{verdict} Predicting the direction of a stock from an announcement, with the company's
identity hidden, this method was right **{hit:.1%}** of the time. Guessing at random gets
you 50%.

It is also **badly overconfident**: on the announcements where it claimed to be most
certain, it was right less often than on the ones where it admitted to guessing.

Once you subtract what it costs to actually place the trades, the strategy
**{"loses money" if not makes_money else "still makes money"}**.

*This is the intended kind of answer.* The project was built to measure honestly, including
measuring that something does not work — see "Why a negative result is the point" below.
"""
    )

    with st.expander("What do these terms mean?"):
        st.markdown(
            """
| Term | What it means |
|---|---|
| **8-K filing** | An announcement a US public company must file when something material happens — earnings, an executive leaving, a big contract. |
| **Hit rate** | How often the up/down call was correct. 50% is a coin flip. |
| **Long/short** | Buy the stocks predicted to rise, bet against the ones predicted to fall. Profits if the *ranking* is right, even in a falling market. |
| **Market-excess return** | The stock's return *minus* the whole market's return over the same days. Strips out "everything went up that week". |
| **Basis point (bp)** | One hundredth of a percent. 10 bps = 0.10%. Trading costs are quoted this way. |
| **Sharpe ratio** | Return per unit of risk, annualized. ~1.0 is a genuinely good strategy, 0 means no skill, negative means it loses. |
| **t-statistic** | Whether a result could plausibly be luck. Roughly, above +2 or below −2 starts to look real. |
| **Max drawdown** | The worst peak-to-trough fall along the way. 0.10 means it lost 10% from its high point. |
| **Brier score** | Scores stated confidence against reality. Lower is better. 0.25 is what you'd score by always saying "50-50". |
| **Calibration** | Whether "70% confident" actually means right 70% of the time. |
| **Horizon** | How long the position is held, in trading days. |
"""
        )

    with st.expander("Why a negative result is the point"):
        st.markdown(
            """
Most published trading strategies look profitable and then are not, because the analysis
was quietly bent toward a good answer — testing many variations and reporting the best,
using information that was not actually available at the time, or dropping the awkward data.

This project fixed every decision **in writing before running anything**
(`PREREGISTRATION.md`), including the threshold at which the idea counts as a failure. Then
it reported what came out.

Specific traps that were designed out:

- **Hindsight.** The model is trained on data that already contains what happened next. So
  the company's name, ticker, dates and address are stripped before it sees anything, and a
  separate audit asks the model to name the company anyway, to measure how often the
  disguise fails.
- **Survivorship.** Companies that were dropped from the index — usually the ones that did
  badly — stay in the sample for the years they were members. Studying only today's
  survivors makes any strategy look better than it was.
- **Timing.** A position is opened at the next market open *after* the announcement was
  public, never at a price that had already happened.
- **Costs.** Every result is shown at three cost levels. A strategy that only works at zero
  cost does not work.
"""
        )


def render_research() -> None:
    st.header("Research")
    st.caption(
        "Can a language model extract predictive signal from an 8-K it cannot attribute? "
        "This tab reports the measurement, including the parts that do not flatter it."
    )

    models = available_models() if has_database() else bundled_models()
    if not models:
        st.warning("No predictions available. Run `scripts/run_score.py` first.")
        return

    model_id = st.selectbox("Model", models, index=0)
    trades = load_trades(model_id)
    if not trades:
        st.warning(f"No evaluable trades for {model_id}.")
        return

    if has_database():
        counts = table_counts()
        anonymized = anonymized_count()
    else:
        summary = bundled_summary(model_id)
        counts = summary.get("table_counts", {})
        anonymized = summary.get("anonymized_filings", 0)

    # Plain-English verdict first. A reader should be able to leave after this section
    # knowing what happened; everything below is the evidence for it.
    headline_cal = calibration.evaluate(trades, 5)
    headline_base = portfolio.build(trades, 5, float(config.BASE_CASE_COST_BPS))
    if headline_cal.n:
        plain_english_verdict(headline_cal, headline_base, model_id)
        st.divider()

    # Contamination before performance: if the model can name the issuer, every number
    # below is suspect, and the reader should learn that first.
    render_contamination()
    st.divider()

    render_head_to_head(models)
    st.divider()

    # ---- headline integrity numbers, before any performance figure ----
    st.subheader("How much data this rests on")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Filings ingested", f"{counts.get('filings', 0):,}")
    c2.metric("Predictions", f"{counts.get('predictions', 0):,}")
    c3.metric("Evaluable trades", f"{len(trades) // len(config.HORIZONS_TRADING_DAYS):,}")
    c4.metric("Anonymized", f"{anonymized:,}")

    base = portfolio.build(trades, 5, float(config.BASE_CASE_COST_BPS))
    if not base.is_statistically_meaningful:
        st.error(
            f"**Underpowered sample.** Monthly rebalancing gives only {base.n_periods} "
            "return observations. Sharpe ratios, t-statistics and drawdowns below are "
            "arithmetic, not evidence, and the §14 null-result test is not applied. "
            "Calibration results rest on per-prediction sample size and are interpretable."
        )

    # ---- calibration first: H2 is the hypothesis this project can answer best ----
    st.subheader("Is its confidence honest?")
    st.caption(
        "When it says it is 70% sure, is it right 70% of the time? A well-calibrated "
        "forecaster's line sits on the diagonal. Below the diagonal means overconfident — "
        "it claims more certainty than it earns."
    )
    horizon = st.radio(
        "Horizon (trading days)", config.HORIZONS_TRADING_DAYS, index=1, horizontal=True
    )
    cal = calibration.evaluate(trades, int(horizon))

    k1, k2, k3 = st.columns(3)
    k1.metric(
        "Brier score",
        f"{cal.brier_score:.4f}",
        help="Lower is better; 0.25 is the score of a forecaster who always says 0.50.",
    )
    k2.metric(
        "Hit rate",
        f"{cal.observed_frequency:.3f}",
        delta=f"{cal.observed_frequency - 0.5:+.3f} vs coin flip",
    )
    k3.metric(
        "Overconfidence",
        f"{cal.overconfidence:+.3f}",
        help="Mean stated confidence minus realised hit rate. Positive = overconfident.",
    )

    bins = pd.DataFrame(
        [
            {
                "confidence bin": b.label,
                "n": b.count,
                "stated": b.mean_predicted,
                "realised": b.observed_frequency,
                "gap": b.gap,
            }
            for b in cal.bins
            if b.count > 0
        ]
    )
    left, right = st.columns([2, 3])
    with left:
        st.dataframe(bins, hide_index=True, use_container_width=True)
    with right:
        st.caption("Reliability — perfect calibration is the diagonal")
        chart = bins.set_index("stated")[["realised"]].copy()
        chart["perfect calibration"] = chart.index
        st.line_chart(chart)

    # ---- returns, always at all horizons and all cost levels ----
    st.subheader("Would trading on it have made money?")
    st.caption(
        "Each month, buy the announcements it was most confident would rise and bet "
        "against the ones it thought would fall, in equal amounts. Every holding period "
        "and every cost level is shown — the pre-registration forbids reporting only the "
        "flattering horizon, or showing returns as though trading were free. "
        "**Negative Sharpe means it lost money.**"
    )
    rows = [
        portfolio.build(trades, h, float(c)).as_row()
        for h in config.HORIZONS_TRADING_DAYS
        for c in config.COST_LEVELS_BPS
    ]
    table = pd.DataFrame(rows)
    table.columns = [
        "horizon",
        "cost (bps)",
        "months",
        "positions",
        "mean return",
        "t-stat",
        "Sharpe",
        "max drawdown",
        "hit rate",
    ]
    st.dataframe(
        table.style.format(
            {
                "mean return": "{:+.4f}",
                "t-stat": "{:+.2f}",
                "Sharpe": "{:+.2f}",
                "max drawdown": "{:.3f}",
                "hit rate": "{:.2f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    # ---- the exclusion ledger: invariant 5 made visible ----
    st.subheader("What was thrown away, and why")
    st.caption(
        "Nothing is dropped silently. Discarding inconvenient data is the easiest way to "
        "manufacture a good backtest, so every excluded filing is counted here with its "
        "reason — mostly companies that were renamed or acquired and whose old ticker no "
        "longer returns prices."
    )
    if has_database():
        exclusions = evaluation_exclusions(model_id)
    else:
        exclusions = sorted(
            bundled_summary(model_id).get("exclusions", {}).items(),
            key=lambda kv: -kv[1],
        )
    if exclusions:
        st.dataframe(
            pd.DataFrame(exclusions, columns=["reason", "count"]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("No exclusions at the evaluation stage.")

    with st.expander("Method and known limitations"):
        st.markdown(
            f"""
- **Entry timing (§4).** Filings accepted before 16:00 ET on a trading day enter at the
  next open; everything else skips one open. Same-day returns are never used.
- **Returns (§5).** Market-excess: the issuer's adjusted open-to-close return minus SPY's
  over the identical window, at {", ".join(str(h) for h in config.HORIZONS_TRADING_DAYS)}
  trading days.
- **Costs (§10).** Reported at {", ".join(str(c) for c in config.COST_LEVELS_BPS)} bps
  round trip; {config.BASE_CASE_COST_BPS} bps is the base case.
- **Universe (§3).** Point-in-time S&P 500 membership, reconstructed and frozen, so
  companies that left the index remain in the sample for the period they were members.
- **Known gaps.** 18 renamed or acquired tickers have no price coverage under their
  historical symbol; those filings are excluded and counted, not dropped. The gap sits in
  the survivorship-relevant population, so it is not random missingness.
"""
        )


# --------------------------------------------------------------------------
# Track record and Today
# --------------------------------------------------------------------------
def render_track_record() -> None:
    st.header("Track record")
    st.caption(
        "Live, out-of-sample predictions, recorded before the outcome window closes and "
        "never used to tune anything (§15). Kept strictly separate from historical results."
    )
    if not has_database():
        st.info("Live predictions are not part of the exported results bundle.")
        return
    live_rows = live_predictions()
    if live_rows.empty:
        st.info(
            "No live predictions yet. Phase 8 polls EDGAR on a schedule and scores new "
            "filings through the identical code path."
        )
        return
    st.dataframe(
        live_rows,
        hide_index=True,
        use_container_width=True,
    )


def render_today() -> None:
    st.header("Today")
    if not has_database():
        st.info("Filing-level detail is not part of the exported results bundle.")
        return
    overview = filings_overview()
    if overview.empty:
        st.info("No filings ingested yet.")
        return
    st.metric("Months covered", len(overview))
    st.bar_chart(overview.set_index("month")["filings"])
    st.dataframe(overview, hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Experiments overview — one plain-language card per pre-registered experiment
# --------------------------------------------------------------------------
# Kept as a static, self-contained list so the page renders from the committed
# results bundle without a database. Mirrors experiments/*/HYPOTHESIS.md; update
# both together. `bundle` names the results JSON in data/results/ (if any).
EXPERIMENTS: list[dict[str, str]] = [
    {
        "id": "001",
        "title": "Can an AI predict the move from the filing text?",
        "status": "running",
        "bundle": "",
        "question": "Show a model an 8-K with the company name and date stripped out — can "
        "it call which way the stock goes?",
        "how": "Score ~5,000 anonymized filings at temperature 0, then check the actual "
        "market-excess move at 1 / 5 / 20 days, after trading costs.",
        "why": "The original question, and the honest baseline. A coin-flip result here is "
        "expected — and it's what motivates every experiment below.",
        "result": "Preliminary: about a coin flip (~52% at 5 days), no significant edge. "
        "Final number pending the full scoring run.",
    },
    {
        "id": "002",
        "title": "Does the *type* of event matter — no AI needed?",
        "status": "exploratory",
        "bundle": "experiment_002.json",
        "question": "Forget reading the text. Does a high-impact filing (a restatement, a big "
        "write-down) drift more *after* it is filed than a routine notice?",
        "how": "Group filings by SEC item code and compare the average market-excess return "
        "of the high-impact group against the routine group, entering at the next open.",
        "why": "Almost the point of a sanity check — it proves the measuring machine works "
        "before we trust it on harder questions. Costs ~$0.",
        "result": "Development read: a near-null. Because entry is the *next* open, the "
        "announcement pop is already gone, and the leftover drift barely differs by event "
        "type — consistent with an efficient market (and with Experiment 004).",
    },
    {
        "id": "003",
        "title": "Does *new* language beat boilerplate? ('Lazy Prices')",
        "status": "exploratory",
        "bundle": "experiment_003.json",
        "question": "When a company suddenly rewrites its usual filing language instead of "
        "copy-pasting, is that a warning sign the stock will underperform?",
        "how": "Measure how much each filing's text changed from the company's own prior "
        "comparable filing, rank filings by that change, and test a long/short portfolio.",
        "why": "A published effect for annual reports — the open question is whether it "
        "carries over to short, messy 8-Ks. The one real signal-discovery experiment here.",
        "result": "Null — and the sign is backwards. The long/short loses money at every "
        "horizon (20-day Sharpe −0.87 on the 2020–24 partition, not significant). 'Lazy Prices' does not "
        "transfer from annual reports to 8-Ks, most likely because an 8-K's 'prior comparable "
        "filing' is a far weaker analog than last year's 10-K is to this year's.",
    },
    {
        "id": "004",
        "title": "Was the news already old by the time it was filed?",
        "status": "exploratory",
        "bundle": "experiment_004.json",
        "question": "How much of the stock's reaction already happened *before* the 8-K "
        "reached EDGAR?",
        "how": "For each filing, split the abnormal move into 'before the filing' and 'after "
        "the filing' around the event date, using prices we already have — no new data.",
        "why": "The most likely reason 001 fails: if the market already moved, there's "
        "nothing left to predict. This diagnostic shows where the *fresh* information is.",
        "result": "Development read: the median filing has ~47% of its abnormal move "
        "*already over* before it can be traded — substantial staleness that partly explains "
        "001's coin flip, but just under half, so the filing isn't pure old news either.",
    },
    {
        "id": "005",
        "title": "Do earnings surprises keep drifting? (PEAD)",
        "status": "done",
        "bundle": "experiment_005.json",
        "question": "After an earnings report, does the stock keep moving in the direction of "
        "the surprise for weeks — the classic 'post-earnings drift' — even entered late?",
        "how": "Use the market's own immediate reaction as the surprise, enter *after* it at "
        "the next open, and hold a long-big-surprise / short-small-surprise book for 20–60 days.",
        "why": "The first experiment designed after diagnosing why 001–004 failed: stop fighting "
        "the announcement pop, ride the documented drift that follows it. PEAD is real and "
        "widely replicated — the open question is whether it survives *here*, with costs.",
        "result": "Killed by the holdout — the project's cleanest lesson. On development the "
        "pre-registered long-only variant looked like a real win (Sharpe 0.53, survives 25 bps). "
        "But it had already decayed to negative by 2017–19, and the single 2020–24 confirmatory "
        "shot came back **−0.38**. A 0.53 'success' became −0.38 out-of-sample: exactly the false "
        "discovery that pre-registration and a reserved holdout exist to catch.",
    },
    {
        "id": "RG",
        "title": "Reaction Gap — did the market move *enough*? (future branch)",
        "status": "gated",
        "bundle": "",
        "question": "When real news breaks, did the stock move as much as similar news "
        "historically moved comparable companies — or is there unprocessed news left?",
        "how": "Reconstruct when the news first went public, estimate the reaction "
        "historically-similar events produced, and test whether the gap predicts later drift.",
        "why": "The ambitious payoff, and the best story — but it needs data we don't have "
        "yet (intraday prices, news timestamps), so it is gated on what 004 finds.",
        "result": "Gate only half-passed: 004 shows real pre-filing staleness (~47%) but not "
        "a clean majority, so this stays on the shelf until a sharper, intraday measure "
        "(or an event-type split) says it's worth the data-engineering cost.",
    },
]

_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "running": ("🟢", "running"),
    "exploratory": ("🟡", "development read (in-sample)"),
    "draft": ("⚪", "pre-registered, holdout reserved"),
    "gated": ("🔒", "gated — not started"),
    "done": ("✅", "complete"),
}


def load_experiment_bundle(name: str) -> dict[str, Any] | None:
    if not name:
        return None
    path = RESULTS_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return None


def _fmt_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


# One-line plain-English verdict per experiment: (streamlit box type, text).
FINDINGS: dict[str, tuple[str, str]] = {
    "001": (
        "warning",
        "So far: a coin flip. The AI shows no reliable edge — which is the honest, "
        "expected result and the reason the other experiments exist.",
    ),
    "002": (
        "warning",
        "Near-null. Once you buy at the next morning's open, the *type* of event barely "
        "matters — the reaction already happened.",
    ),
    "003": (
        "error",
        "Null, and pointing the wrong way. Rewriting a filing did NOT predict lower returns; "
        "the 'Lazy Prices' effect does not carry over from annual reports to 8-Ks.",
    ),
    "004": (
        "info",
        "About 47% of a filing's stock move is already over before you could trade it — and "
        "earnings filings are the stalest (57%). No event type is cleanly 'fresh', so the "
        "filing rarely beats the market to its own news.",
    ),
    "005": (
        "error",
        "Development said 0.53, the holdout said −0.38. The pre-registered long-only variant "
        "cleared the materiality bar on 2010–19 data, but it was a decayed early-2010s effect, "
        "and the single 2020–24 confirmatory shot was negative. Not a signal — but the single "
        "clearest proof the platform does its job: it caught a would-be false discovery.",
    ),
    "RG": (
        "info",
        "Not built. The cheap check (004) said the premise is only half-true, so this stays "
        "on the shelf until it's worth the extra data.",
    ),
}


def _finding_box(exp_id: str) -> None:
    tone, text = FINDINGS.get(exp_id, ("info", ""))
    if not text:
        return
    {"warning": st.warning, "error": st.error, "info": st.info, "success": st.success}[tone](
        f"**What we found.** {text}"
    )


# Compact, skimmable summary per experiment: result badge + one-line key finding.
_RESULT_BADGE: dict[str, str] = {
    "001": "❌ No edge (final run pending)",
    "002": "❌ Near-null",
    "003": "❌ Rejected — wrong sign",
    "004": "◑ Diagnostic — ~47% stale",
    "005": "❌ 0.53 on dev → −0.38 on holdout",
    "RG": "🔒 Not built (gated)",
}
_KEY_FINDING: dict[str, str] = {
    "001": "An AI reading anonymized filings scores about a coin flip — no reliable direction.",
    "002": "Once you enter at the next open, high-impact events barely beat routine ones (p≈0.8).",
    "003": "Buying least-changed / shorting most-changed 8-Ks loses money (20d Sharpe −0.87).",
    "004": "~47% of the average filing's move is already over before you can trade it; "
    "earnings 8-Ks are stalest at 57%.",
    "005": "Long-only PEAD looked like a win on development (Sharpe 0.53) but the single "
    "out-of-sample shot came back −0.38 — a decayed effect caught by the reserved holdout.",
    "RG": "004 showed no cleanly-fresh event class, so this expensive branch was not built.",
}


# Contamination audit numbers, fixed in §6 before any code was written.
_CONTAM_EXAMPLES = [
    ("American Water Works", "\"largest publicly traded U.S. water utility, 6,800+ employees\""),
    ("Delta Air Lines", "\"Atlanta airport power outage\", \"Trainer refinery\", pilot profit-sharing"),
    ("Mosaic", "\"phosphate and potash operations\", \"Vale S.A.\", \"TIPLAM port\""),
    ("O'Reilly Automotive", "\"leading automotive-aftermarket retailer, 5,000+ stores\""),
    ("Allergan", "named its own subsidiary \"Forest Laboratories, LLC\""),
]


def render_contamination_panel() -> None:
    """The 38.7% issuer-identification finding — arguably the most interesting result."""
    st.markdown(
        "#### The disguise fails 38.7% of the time\n"
        "The whole project hinges on the model *not* knowing which company it is reading. So "
        "we asked it directly: name the issuer of an anonymized filing. It succeeded on "
        "**58 of 150 (38.7%)** — nearly double the 20% red line we fixed *before* writing any "
        "code."
    )
    a, b = st.columns(2)
    a.metric("identified the company", "38.7%", help="58 of 150 anonymized filings")
    b.metric("stayed anonymous", "61.3%")
    st.markdown(
        "It works because **filings describe themselves**, and no name-redaction touches that:"
    )
    st.dataframe(
        pd.DataFrame(
            [{"the model guessed": name, "from a clue like": clue}
             for name, clue in _CONTAM_EXAMPLES],
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "Redaction defeats string-matching, not comprehension. §6 fixed the consequence in "
        "advance: above 20%, the primary analysis is restricted to filings the model could "
        "*not* identify, and both versions reported. This measured rate is a **lower bound** — "
        "the audit ran on a smaller model than scoring, and smaller models recognize fewer "
        "companies."
    )


def render_002_results(bundle: dict[str, Any]) -> None:
    """Event-type contrast, by partition and horizon, in basis points."""
    rows = []
    for r in bundle.get("results", []):
        g = r["groups"]
        rows.append(
            {
                "data": "2010–19 (dev)" if r["partition"] == "explore" else "2020–24",
                "horizon (days)": r["horizon"],
                "high-impact (bps)": round(g["high-impact"]["mean"] * 1e4, 1),
                "routine (bps)": round(g["routine"]["mean"] * 1e4, 1),
                "high − routine (bps)": round(r["high_minus_routine_bps"], 1),
                "p-value": _fmt_p(r["p_value"]),
            }
        )
    st.markdown(
        "**Average market-excess return after the filing, by event type (basis points; "
        "1 bp = 0.01%).** If knowing the event type helped, the *high − routine* gap would be "
        "large and its p-value small. It isn't."
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_003_results(bundle: dict[str, Any]) -> None:
    """Novelty long/short Sharpe by partition and horizon."""
    rows = []
    for r in bundle.get("results", []):
        rows.append(
            {
                "data": "2010–19 (dev)" if r["partition"] == "explore" else "2020–24",
                "horizon (days)": r["horizon"],
                "months": r["n_months"],
                "return / month": f"{r['mean_monthly'] * 100:.3f}%",
                "Sharpe (per year)": round(r["sharpe_annualized"], 2),
                "t-stat": round(r["t_statistic"], 2),
            }
        )
    st.markdown(
        "**A long/short portfolio that buys the least-changed filings and shorts the "
        "most-changed.** A working signal would show a clearly positive Sharpe. Every row is "
        "negative and none is significant (|t| < 2), so there is no signal — if anything, the "
        "reverse."
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_005_results(bundle: dict[str, Any]) -> None:
    """PEAD long/short Sharpe by partition and horizon."""
    shot = bundle.get("holdout_shot")
    if shot:
        st.error(
            "**Holdout verdict: the development signal did not survive.** The frozen long-only "
            "20-day construction scored **0.53 Sharpe on development** and **−0.38 out-of-sample** "
            "(2020–24). This is the whole point of the platform — a would-be 'success' caught and "
            "killed by one honest test."
        )
        lo20 = next(
            (x["long_only"] for x in shot.get("book_comparison", []) if x["horizon"] == 20), None
        )
        ls20 = next(
            (x["long_short"] for x in shot.get("book_comparison", []) if x["horizon"] == 20), None
        )
        cmp_rows = [
            {
                "construction (20-day, 10 bps)": "long/short (primary)",
                "development Sharpe": 0.14,
                "holdout Sharpe": round(ls20["sharpe_annualized"], 2) if ls20 else None,
            },
            {
                "construction (20-day, 10 bps)": "long-only (frozen secondary)",
                "development Sharpe": 0.53,
                "holdout Sharpe": round(lo20["sharpe_annualized"], 2) if lo20 else None,
            },
        ]
        st.dataframe(pd.DataFrame(cmp_rows), hide_index=True, use_container_width=True)
        years = shot.get("by_year_long_only", [])
        if years:
            st.caption(
                "Long-only 20-day Sharpe by holdout year — the development decay simply "
                "continued (2024 alone: −2.72):"
            )
            ser = pd.DataFrame(years)
            ser["sharpe"] = ser["sharpe"].astype(float).round(2)
            st.bar_chart(ser.set_index("year")["sharpe"])
        st.divider()
        st.markdown("#### How we got here (development, 2010–19)")

    rows = []
    for r in bundle.get("results", []):
        rows.append(
            {
                "data": "2010–19 (dev)" if r["partition"] == "explore" else "2020–24",
                "hold (days)": r["horizon"],
                "months": r["n_months"],
                "return / month": f"{r['mean_monthly'] * 100:.3f}%",
                "Sharpe (per year)": round(r["sharpe_annualized"], 2),
                "t-stat": round(r["t_statistic"], 2),
            }
        )
    st.markdown(
        "**A long/short book that buys the biggest positive earnings surprises and shorts the "
        "biggest negatives, held for 20–60 days.** For the first time the numbers are *positive* "
        "and grow with the holding period — the fingerprint of real post-earnings drift. The "
        "0.30 line is the materiality bar a signal must clear to count. The confirmatory 2020–24 "
        "read is intentionally still reserved."
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    rob = bundle.get("robustness")
    if not rob:
        return
    st.markdown(
        "#### Development robustness (2010–19 only)\n"
        "**Dropping the short leg is decisive.** PEAD is classically a long-side effect; the "
        "long-only variant clears the 0.30 bar while the long/short doesn't:"
    )
    comp = []
    for x in rob.get("book_comparison", []):
        ls, lo = x["long_short"], x["long_only"]
        comp.append(
            {
                "hold (days)": x["horizon"],
                "long/short Sharpe": round(ls["sharpe_annualized"], 2),
                "long-only Sharpe": round(lo["sharpe_annualized"], 2),
                "long-only t": round(lo["t_statistic"], 2),
            }
        )
    st.dataframe(pd.DataFrame(comp), hide_index=True, use_container_width=True)

    costs = [
        {
            "cost (bps)": c["cost_bps"],
            "long/short Sharpe": round(c["long_short_sharpe"], 2),
            "long-only Sharpe": round(c["long_only_sharpe"], 2),
        }
        for c in rob.get("cost_sensitivity", [])
    ]
    st.markdown(
        "**Cost sensitivity (20-day).** Long-only survives even 25 bps (Sharpe 0.31); "
        "long/short goes negative once realistically costed:"
    )
    st.dataframe(pd.DataFrame(costs), hide_index=True, use_container_width=True)

    years = rob.get("by_year_long_only", [])
    if years:
        st.markdown(
            "**But it decayed.** Long-only 20-day Sharpe by year — strong in the early 2010s, "
            "**negative by 2017–19.** The aggregate edge is carried by the early years, which is "
            "the honest warning going into the reserved 2020–24 holdout:"
        )
        ser = pd.DataFrame(years)
        ser["sharpe"] = ser["sharpe"].astype(float).round(2)
        st.bar_chart(ser.set_index("year")["sharpe"])


def render_004_results(bundle: dict[str, Any]) -> None:
    """Staleness fraction by partition."""
    rows = []
    for r in bundle.get("results", []):
        if not r["n"]:
            continue
        rows.append(
            {
                "data": "2010–19 (dev)" if r["partition"] == "explore" else "2020–24",
                "filings measured": f"{r['n']:,}",
                "median staleness": f"{r['median_fraction']:.0%}",
                "share mostly-stale (>50%)": f"{r['share_mostly_stale']:.0%}",
            }
        )
    if not rows:
        st.info("Staleness is still computing (event dates are being backfilled). Check back.")
        return
    st.markdown(
        "**How much of the move was already over before the filing** (100% = the whole "
        "reaction happened before you could trade it; 0% = the filing was the first the market "
        "heard of it). The median filing sits near 47%."
    )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    by_event = bundle.get("by_event_type", [])
    if by_event:
        st.markdown("**By event type — is any kind of news still fresh when it's filed?**")
        et_rows = [
            {
                "event type": f"{r['code']} · {r['label']}",
                "filings": f"{r['n']:,}",
                "median staleness": f"{r['median_fraction']:.0%}",
                "mostly-stale (>50%)": f"{r['share_mostly_stale']:.0%}",
            }
            for r in by_event
        ]
        st.dataframe(pd.DataFrame(et_rows), hide_index=True, use_container_width=True)
        st.caption(
            "Earnings 8-Ks (2.02) are the stalest by far — the market reacts to the earnings "
            "release, and the filing just formalizes it. No category is cleanly 'fresh' "
            "(all sit above ~38%), so there's no event type where the filing beats the market "
            "to the news — which is why the Reaction Gap branch stays on the shelf."
        )


_RESULT_RENDERERS = {
    "002": render_002_results,
    "003": render_003_results,
    "004": render_004_results,
    "005": render_005_results,
}


def render_overview() -> None:
    st.subheader("What this project is")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("8-K filings", "100K+")
    c2.metric("price observations", "1.58M")
    c3.metric("pre-registered experiments", "5")
    c4.metric("signals that survived", "0", help="Nothing cleared the pass/fail bar. 005 came "
              "closest — a 0.53-Sharpe long-only signal on development — but the reserved holdout "
              "returned −0.38, exactly the false discovery the discipline exists to catch.")
    st.caption(
        "A contamination-resistant research platform for testing whether SEC filings carry "
        "tradeable information. Five experiments, none surviving — four explain each other "
        "(~half the price reaction happens before the filing is public), and the fifth is the "
        "cleanest lesson: a development 'win' killed by one honest out-of-sample test."
    )
    st.markdown(
        "**Hindsight asks a simple question honestly: can public company filings tell you "
        "where a stock is headed?** Instead of one flashy strategy, it runs a small family of "
        "**pre-registered experiments** — each one written down, with its pass/fail test fixed "
        "*before* the answer is looked at. That's the discipline serious quant research runs on, "
        "and it's what stops 'we tried a bunch of things and one happened to work' from being "
        "mistaken for a discovery."
    )
    st.markdown(
        "**The story so far, in one line:** an AI reading anonymized filings can't beat a coin "
        "flip (001); the *type* of event doesn't rescue it (002); roughly **half the market's "
        "reaction is already over before the filing is even public** (004); and *new* wording "
        "doesn't predict returns either (003). Four honest nulls that explain each other — then "
        "**005** uses that diagnosis to target post-earnings drift, *looks* like a win on "
        "development (Sharpe 0.53), and gets killed by the reserved holdout (−0.38): the cleanest "
        "demonstration of why the whole apparatus exists."
    )
    st.markdown(
        "📄 **Read the [Findings] tab** for the full written narrative — the arc, what each "
        "result means, the limitations, and what I'd do next."
    )
    st.markdown("**The experiments at a glance** — open each tab above for the full story:")
    cols = st.columns(2)
    for i, e in enumerate(EXPERIMENTS):
        with cols[i % 2].container(border=True):
            st.markdown(f"**{e['id']} — {e['title'].replace('*', '')}**")
            st.markdown(f"{_RESULT_BADGE.get(e['id'], '')}")
            st.caption(_KEY_FINDING.get(e["id"], ""))

    st.divider()
    render_contamination_panel()
    st.caption(
        "This is arguably the most interesting result in the project — and the reason "
        "\"I anonymized the ticker\" is not a safe assumption when the reader is an LLM. Full "
        "detail on the **001** tab."
    )
    st.divider()
    st.info(
        "**Why so cautious?** Run several experiments and one will look 'significant' by pure "
        "luck. The final verdict corrects for how many were tried and reports only what "
        "survives — including, and especially, when nothing does."
    )
    st.caption(
        "🟡 *development read (in-sample)* — 002, 003 and 004 were computed on all years while "
        "being built, so they're reported honestly as in-sample rather than as clean "
        "single-shot tests (see DEVIATIONS.md in the repo)."
    )


def render_findings() -> None:
    """Render the written narrative from FINDINGS.md (single source of truth)."""
    path = config.ROOT / "FINDINGS.md"
    if path.exists():
        st.markdown(path.read_text(encoding="utf-8"))
    else:
        st.info("FINDINGS.md not found in the deployment.")


def render_experiment_detail(exp: dict[str, str]) -> None:
    icon, label = _STATUS_STYLE.get(exp["status"], ("•", exp["status"]))
    st.subheader(f"{exp['id']} — {exp['title'].replace('*', '')}")
    st.markdown(f"{icon} *{label}* &nbsp;·&nbsp; **{_RESULT_BADGE.get(exp['id'], '')}**")
    st.caption(_KEY_FINDING.get(exp["id"], ""))

    st.markdown(f"### In one sentence\n{exp['question']}")
    _finding_box(exp["id"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**How we test it**\n\n{exp['how']}")
    with col2:
        st.markdown(f"**Why it matters**\n\n{exp['why']}")

    st.markdown(f"**The detail.** {exp['result']}")

    bundle = load_experiment_bundle(exp.get("bundle", ""))
    renderer = _RESULT_RENDERERS.get(exp["id"])
    if bundle and renderer:
        st.divider()
        st.markdown("#### The numbers")
        renderer(bundle)

    # 001 carries the deep research view (contamination, calibration, exclusions).
    if exp["id"] == "001":
        st.divider()
        render_contamination_panel()
        st.divider()
        with st.expander("Full research detail (calibration, returns, exclusions)"):
            render_research()


# Short tab labels, one per experiment.
_TAB_LABELS: dict[str, str] = {
    "001": "001 · AI reader",
    "002": "002 · Event type",
    "003": "003 · Novelty",
    "004": "004 · Staleness",
    "005": "005 · PEAD",
    "RG": "Reaction Gap",
}


def main() -> None:
    st.title("hindsight")
    st.markdown(
        "**Can public company filings tell you where a stock is headed?** "
        "A family of pre-registered experiments that answer that honestly — including when "
        "the answer is *no*."
    )
    if not has_database() and not bundled_models():
        st.warning(
            "Serving committed results only — the working database isn't deployed. Some "
            "deeper views under 001 may be empty, but every experiment's headline result is "
            "read from the committed bundles in data/results/."
        )
    elif not has_database():
        st.caption(
            "Serving the committed results bundle — the working database (~95MB) and raw "
            "filing cache (~2.8GB) are not deployed. Figures come from exported results by the "
            "same code path."
        )

    labels = (
        ["Overview", "Findings"]
        + [_TAB_LABELS[e["id"]] for e in EXPERIMENTS]
        + ["Live"]
    )
    tabs = st.tabs(labels)
    with tabs[0]:
        render_overview()
    with tabs[1]:
        render_findings()
    for exp, tab in zip(EXPERIMENTS, tabs[2:], strict=False):
        with tab:
            render_experiment_detail(exp)
    with tabs[-1]:
        st.caption("Phase 8 — automatic scoring of new filings as they are published.")
        render_track_record()
        st.divider()
        render_today()

    st.caption(f"Data as of {date.today().isoformat()} · schema v{db.SCHEMA_VERSION}")


main()
