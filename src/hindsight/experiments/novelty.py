"""Experiment 003 — filing novelty / linguistic change ("Lazy Prices").

Signal: how much a filing's language changed from the same company's most recent prior
comparable filing (same primary item code), measured as TF-IDF cosine *distance*
(change = 1 - cosine). Big change = the company rewrote its usual disclosure. H1 (from
the literature on 10-K/10-Q): more change -> lower subsequent return, so a portfolio that
shorts the high-change filings and longs the low-change ones earns a positive Sharpe.

Discipline baked in here:
* The TF-IDF vocabulary and IDF weights are fit on **EXPLORE (2010-2019) text only**, then
  applied frozen to every filing — otherwise holdout-era vocabulary leaks backward.
* Entry timing, market-excess returns, and exclusions reuse the shared harness, so 003
  cannot drift from the invariants.

Pure-Python TF-IDF (no sklearn dependency): a filing is a handful of thousand tokens and
the corpus ~75k filings, which is well within reach without a heavy library.
"""

from __future__ import annotations

import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

from hindsight import config
from hindsight.evaluate.portfolio import MONTHS_PER_YEAR, max_drawdown
from hindsight.evaluate.returns import PriceLookup
from hindsight.experiments.common import filing_excess_return
from hindsight.manifest import RunManifest

# Vocabulary controls (fixed here, tuned only on EXPLORE if at all).
MAX_TEXT_CHARS = 20_000  # bound tokenization cost; captures the substance of an 8-K
MIN_DOC_FREQ = 5  # a token must appear in >= 5 EXPLORE filings to enter the vocabulary
MAX_DOC_FREQ_FRAC = 0.5  # drop tokens in >50% of EXPLORE filings (near-stopwords)
MAX_VOCAB = 50_000
_TOKEN_RE = re.compile(r"[a-z]{3,}")

# A short stopword list; TF-IDF already down-weights ubiquitous tokens, so this is light.
_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "not",
        "but",
        "its",
        "their",
        "our",
        "which",
        "will",
        "shall",
        "may",
        "can",
        "such",
        "other",
        "than",
        "then",
        "into",
        "over",
        "under",
        "more",
        "most",
        "any",
        "all",
        "been",
        "being",
        "about",
        "above",
        "below",
        "between",
        "during",
        "before",
        "after",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()[:MAX_TEXT_CHARS]) if t not in _STOPWORDS]


@dataclass
class Vocabulary:
    """EXPLORE-fit vocabulary and inverse document frequencies."""

    idf: dict[str, float]

    def vector(self, tokens: list[str]) -> dict[str, float]:
        """L2-normalized TF-IDF vector, restricted to the fitted vocabulary."""
        tf = Counter(t for t in tokens if t in self.idf)
        if not tf:
            return {}
        vec = {t: (c / len(tokens)) * self.idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm == 0:
            return {}
        return {t: v / norm for t, v in vec.items()}


def fit_vocabulary(explore_texts: list[list[str]]) -> Vocabulary:
    """Document frequencies -> IDF, on EXPLORE tokens only."""
    n = len(explore_texts)
    doc_freq: Counter[str] = Counter()
    for tokens in explore_texts:
        doc_freq.update(set(tokens))
    max_df = int(MAX_DOC_FREQ_FRAC * n)
    kept = [(tok, df) for tok, df in doc_freq.items() if MIN_DOC_FREQ <= df <= max_df]
    kept.sort(key=lambda kv: kv[1], reverse=True)
    kept = kept[:MAX_VOCAB]
    idf = {tok: math.log(n / df) for tok, df in kept}
    return Vocabulary(idf=idf)


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of two L2-normalized sparse vectors (dot product)."""
    if not a or not b:
        return 0.0
    small, large = (a, b) if len(a) < len(b) else (b, a)
    return sum(v * large.get(t, 0.0) for t, v in small.items())


def primary_item(item_codes: str | None) -> str:
    codes = [c.strip() for c in (item_codes or "").split(",") if c.strip()]
    return codes[0] if codes else "NA"


@dataclass(frozen=True)
class Scored:
    accession_no: str
    ticker: str
    accepted_at_utc: str
    partition: str
    change_score: float


def compute_change_scores(conn: sqlite3.Connection, manifest: RunManifest) -> list[Scored]:
    """Change score for each filing that has a comparable prior filing and anonymized text."""
    rows = list(
        conn.execute(
            "SELECT accession_no, cik, ticker, accepted_at_utc, item_codes, anonymized_text "
            "FROM filings ORDER BY cik, accepted_at_utc"
        )
    )
    manifest.count("filings_considered", len(rows))

    # Fit the vocabulary on EXPLORE filings only.
    explore_tokens: list[list[str]] = []
    for r in rows:
        if r["anonymized_text"] and config.partition_of(r["accepted_at_utc"]) == "explore":
            explore_tokens.append(tokenize(r["anonymized_text"]))
    vocab = fit_vocabulary(explore_tokens)
    manifest.count("vocabulary_size", len(vocab.idf))
    manifest.count("explore_docs_for_vocab", len(explore_tokens))

    # Walk each company's filings in time order, diffing against the last same-item filing.
    prev_vec_by_key: dict[tuple[str, str], dict[str, float]] = {}
    scored: list[Scored] = []
    for r in rows:
        key = (r["cik"], primary_item(r["item_codes"]))
        if not r["anonymized_text"]:
            manifest.exclude("no_anonymized_text", r["accession_no"])
            prev_vec_by_key.pop(key, None)
            continue
        vec = vocab.vector(tokenize(r["anonymized_text"]))
        prior = prev_vec_by_key.get(key)
        prev_vec_by_key[key] = vec
        if prior is None:
            manifest.exclude("no_prior_comparable_filing", r["accession_no"])
            continue
        change = 1.0 - cosine(vec, prior)
        scored.append(
            Scored(
                accession_no=r["accession_no"],
                ticker=r["ticker"],
                accepted_at_utc=r["accepted_at_utc"],
                partition=config.partition_of(r["accepted_at_utc"]),
                change_score=change,
            )
        )
    manifest.count("scored", len(scored))
    return scored


@dataclass(frozen=True)
class NoveltyResult:
    partition: str
    horizon: int
    cost_bps: float
    n_months: int
    n_positions: int
    mean_monthly: float
    sharpe_annualized: float
    t_statistic: float
    max_drawdown: float

    @property
    def is_meaningful(self) -> bool:
        return self.n_months >= MONTHS_PER_YEAR

    def as_dict(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "horizon": self.horizon,
            "cost_bps": self.cost_bps,
            "n_months": self.n_months,
            "n_positions": self.n_positions,
            "mean_monthly": self.mean_monthly,
            "sharpe_annualized": self.sharpe_annualized,
            "t_statistic": self.t_statistic,
            "max_drawdown": self.max_drawdown,
            "is_meaningful": self.is_meaningful,
        }


def _quintile_long_short_monthly(
    scored_with_return: list[tuple[Scored, float, str]], cost_bps: float
) -> list[float]:
    """Monthly long-low-change / short-high-change returns.

    Each item is (scored, market_excess_return, entry_month). Within a month, sort by change
    score; long the bottom quintile (least changed), short the top quintile (most changed).
    """
    by_month: dict[str, list[tuple[Scored, float]]] = defaultdict(list)
    for s, ret, month in scored_with_return:
        by_month[month].append((s, ret))

    series: list[float] = []
    for _, group in sorted(by_month.items()):
        if len(group) < 5:
            continue
        ordered = sorted(group, key=lambda sr: sr[0].change_score)
        size = len(ordered) // 5
        if size == 0:
            continue
        low_change = ordered[:size]  # long these
        high_change = ordered[-size:]  # short these
        long_leg = statistics.fmean(ret - cost_bps / 10_000.0 for _, ret in low_change)
        short_leg = statistics.fmean(-ret - cost_bps / 10_000.0 for _, ret in high_change)
        series.append((long_leg + short_leg) / 2.0)
    return series


def evaluate(
    conn: sqlite3.Connection,
    scored: list[Scored],
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
    horizons: tuple[int, ...] = config.HORIZONS_TRADING_DAYS,
    cost_bps: float = config.BASE_CASE_COST_BPS,
) -> list[NoveltyResult]:
    prices = PriceLookup(conn)
    results: list[NoveltyResult] = []
    for horizon in horizons:
        # (scored, excess_return, entry_month) per partition
        rows_by_part: dict[str, list[tuple[Scored, float, str]]] = {p: [] for p in partitions}
        for s in scored:
            if s.partition not in rows_by_part:
                continue
            fr = filing_excess_return(
                s.accession_no, s.ticker, s.accepted_at_utc, horizon, prices, manifest
            )
            if fr is None:
                continue
            rows_by_part[s.partition].append((s, fr.excess_return, fr.entry_date.strftime("%Y-%m")))

        for partition in partitions:
            data = rows_by_part[partition]
            series = _quintile_long_short_monthly(data, cost_bps)
            n = len(series)
            mean = statistics.fmean(series) if series else 0.0
            stdev = statistics.stdev(series) if n > 1 else 0.0
            sharpe = (mean / stdev) * math.sqrt(MONTHS_PER_YEAR) if stdev > 0 else 0.0
            t = mean / (stdev / math.sqrt(n)) if n > 1 and stdev > 0 else 0.0
            results.append(
                NoveltyResult(
                    partition=partition,
                    horizon=horizon,
                    cost_bps=cost_bps,
                    n_months=n,
                    n_positions=len(data),
                    mean_monthly=mean,
                    sharpe_annualized=sharpe,
                    t_statistic=t,
                    max_drawdown=max_drawdown(series),
                )
            )
    return results


def run(
    conn: sqlite3.Connection,
    manifest: RunManifest,
    partitions: tuple[str, ...] = ("explore", "holdout"),
) -> list[NoveltyResult]:
    scored = compute_change_scores(conn, manifest)
    return evaluate(conn, scored, manifest, partitions=partitions)
