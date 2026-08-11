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
# both together. Status drives the badge colour.
EXPERIMENTS: list[dict[str, str]] = [
    {
        "id": "001",
        "title": "Can an AI predict the move from the filing text?",
        "status": "running",
        "question": "Show a model an 8-K with the company name and date stripped out. "
        "Can it call which way the stock goes?",
        "how": "Score ~5,000 anonymized filings at temperature 0, then check the actual "
        "market-excess move at 1 / 5 / 20 days, after trading costs.",
        "why": "It's the original question — and the honest baseline. A coin-flip result "
        "here is expected, and it's what motivates every experiment below.",
        "result": "Preliminary: about a coin flip (~52% direction at 5 days), no "
        "statistically significant edge. Final number pending the full run.",
    },
    {
        "id": "002",
        "title": "Does the *type* of event matter — no AI needed?",
        "status": "draft",
        "question": "Forget reading the text. Does a high-impact filing (a financial "
        "restatement, a big write-down) move the stock more than a routine notice?",
        "how": "Group filings by their SEC item code and compare the average move of the "
        "high-impact group against the routine group on held-out years.",
        "why": "It's almost certainly true — which is the point. It proves the measuring "
        "machine works before we trust it on harder questions. Costs ~$0.",
        "result": "Not yet run. Locked before looking at the answer.",
    },
    {
        "id": "003",
        "title": "Does *new* language beat boilerplate? ('Lazy Prices')",
        "status": "draft",
        "question": "When a company suddenly rewrites its usual filing language instead of "
        "copy-pasting, is that a warning sign the stock will underperform?",
        "how": "Measure how much each filing's text changed from the company's own prior "
        "comparable filing, rank filings by that change, and test a long/short portfolio.",
        "why": "A published effect for annual reports — the open question is whether it "
        "carries over to short, messy 8-Ks. The one real signal-discovery experiment here.",
        "result": "Not yet run. Locked before looking at the answer.",
    },
    {
        "id": "004",
        "title": "Was the news already old by the time it was filed?",
        "status": "draft",
        "question": "How much of the stock's reaction already happened *before* the 8-K "
        "reached EDGAR?",
        "how": "For each filing, split the abnormal move into 'before the filing' and "
        "'after the filing' using the prices we already have — no new data.",
        "why": "The most likely reason 001 fails: if the market already moved, there's "
        "nothing left to predict. This diagnostic tells us where the *fresh* information is.",
        "result": "Not yet run. Diagnostic — it explains the null rather than trading on it.",
    },
    {
        "id": "RG",
        "title": "Reaction Gap — did the market move *enough*? (future branch)",
        "status": "gated",
        "question": "When real news breaks, did the stock move as much as similar news "
        "historically moved comparable companies — or is there unprocessed news left?",
        "how": "Reconstruct when the news first went public, estimate the reaction "
        "historically-similar events produced, and test whether the gap predicts later drift.",
        "why": "The ambitious payoff — and the best story. But it needs data we don't have "
        "yet (intraday prices, news timestamps), so it's gated on what Experiment 004 finds.",
        "result": "Not started. Only built if 004 confirms filings are genuinely late.",
    },
]

_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "running": ("🟢", "running"),
    "draft": ("⚪", "pre-registered, not yet run"),
    "gated": ("🔒", "gated — not started"),
    "done": ("✅", "complete"),
}


def render_experiments() -> None:
    st.header("Experiments")
    st.markdown(
        "Hindsight is not one strategy — it is a small family of **pre-registered "
        "experiments**. Each one is written down, with its success test fixed, *before* the "
        "answer is looked at. The discipline is the point: it's what stops 'we tried a bunch "
        "of things and one worked' from masquerading as a discovery."
    )
    st.caption(
        "How to read a card: the **question** in plain English, **how** we test it, **why** "
        "it's worth doing, and where it stands. Full method lives in each "
        "`experiments/NNN/HYPOTHESIS.md`."
    )
    for exp in EXPERIMENTS:
        icon, label = _STATUS_STYLE.get(exp["status"], ("•", exp["status"]))
        with st.container(border=True):
            st.markdown(f"#### {exp['id']} — {exp['title']}")
            st.markdown(f"{icon} *{label}*")
            st.markdown(f"**The question.** {exp['question']}")
            st.markdown(f"**How we test it.** {exp['how']}")
            st.markdown(f"**Why it matters.** {exp['why']}")
            st.markdown(f"**Where it stands.** {exp['result']}")
    st.info(
        "Because we run several experiments, any single 'significant' result could be luck. "
        "The final read applies a multiple-comparisons correction across all of them, and "
        "reports what survives — including, and especially, when nothing does."
    )


def main() -> None:
    st.title("hindsight")
    st.markdown(
        "**Can an AI predict a stock's move from a company announcement — if it isn't "
        "allowed to know which company it is?**"
    )
    st.caption(
        "US public companies must file an 8-K whenever something material happens: earnings, "
        "an executive departing, a major contract. This project strips out every clue to the "
        "company's identity, asks a model which way the stock will move, and checks what "
        "actually happened.\n\n"
        "The name is the point. These models were trained on data that already contains the "
        "outcomes, so a model that recognises the company can *remember* the answer instead "
        "of predicting it. That is hindsight, not skill — and the whole design exists to "
        "prevent it. The deliverable is an honest measurement, including a finding that "
        "nothing works."
    )
    if not has_database() and not bundled_models():
        st.error(
            f"No database at {config.DB_PATH} and no exported results in {RESULTS_DIR}. "
            "Run the ingest and scoring scripts, then `scripts/export_results.py`."
        )
        return
    if not has_database():
        st.info(
            "Serving the committed results bundle — the working database is ~95MB and "
            "the raw filing cache ~2.8GB, so neither is deployed. Figures are computed "
            "from exported trades by the same code path."
        )

    experiments, research, track, today = st.tabs(
        ["Experiments", "Research", "Track record", "Today"]
    )
    with experiments:
        render_experiments()
    with research:
        render_research()
    with track:
        render_track_record()
    with today:
        render_today()

    st.caption(f"Data as of {date.today().isoformat()} · schema v{db.SCHEMA_VERSION}")


main()
