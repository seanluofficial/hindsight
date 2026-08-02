"""Loughran-McDonald sentiment baseline (PREREGISTRATION §8).

    score = (positive count - negative count) / total words

No tuning, no threshold optimisation, no learned weights. That austerity is the point:
H3 predicts the LLM will *not* meaningfully beat a dictionary that does no reading
comprehension at all, and the comparison is only honest if the baseline was never given a
chance to overfit.

The dictionary is Loughran-McDonald's Master Dictionary, which is finance-specific for
good reason — in general-purpose word lists "liability", "cost" and "restructuring" read
as negative, while in filings they are neutral vocabulary.

Committed to `data/lm_dictionary.csv`, trimmed to the sentiment-bearing rows. Word lists
are frozen with the file, so a rerun scores identically (invariant 4).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from hindsight import config

# lm-v2 supersedes lm-v1. The dictionary and formula are unchanged; the *input* is not.
# v1 scored the full anonymized filing, v2 scores the capped text defined by
# `config.MAX_SCORING_CHARS`, so the baseline reads exactly what the LLM reads and H3
# compares two readers rather than two inputs.
LEXICON_VERSION = "lm-v2"

# Words only: drops digits, punctuation and the [PLACEHOLDER] tokens the anonymizer
# leaves behind, which are not words and must not dilute the denominator.
_RE_WORD = re.compile(r"\b[A-Za-z][A-Za-z'-]*\b")
_RE_PLACEHOLDER = re.compile(r"\[[A-Z]+\]")


@dataclass(frozen=True)
class LexiconScore:
    """A filing's sentiment score and the counts behind it."""

    score: float
    positive: int
    negative: int
    total_words: int
    version: str = LEXICON_VERSION

    @property
    def direction(self) -> str:
        """Sign of the score as a directional call.

        Ties break to 'down'. Arbitrary, but fixed in advance and applied uniformly, which
        is what matters; a coin flip here would break reproducibility.
        """
        return "up" if self.score > 0 else "down"


@lru_cache(maxsize=1)
def load_dictionary(path: Path | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """(positive, negative) word sets, uppercased. Cached: the file never changes mid-run."""
    source = path or config.LM_DICTIONARY_PATH
    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found. The Loughran-McDonald dictionary is committed to the "
            "repo; restore it from version control."
        )
    positive: set[str] = set()
    negative: set[str] = set()
    with source.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            word = (row.get("Word") or "").strip().upper()
            if not word:
                continue
            # Non-zero means "in this category"; the value is the year it was added.
            if _nonzero(row.get("Positive")):
                positive.add(word)
            if _nonzero(row.get("Negative")):
                negative.add(word)
    if not positive or not negative:
        raise ValueError(f"{source} parsed but yielded no sentiment words")
    return frozenset(positive), frozenset(negative)


def _nonzero(raw: str | None) -> bool:
    try:
        return float(raw or 0) != 0
    except ValueError:
        return False


def tokenize(text: str) -> list[str]:
    """Uppercase word tokens, with anonymizer placeholders removed first."""
    return [w.upper() for w in _RE_WORD.findall(_RE_PLACEHOLDER.sub(" ", text))]


def score_text(text: str, path: Path | None = None) -> LexiconScore:
    """Score one filing. Empty text scores 0.0 rather than dividing by zero."""
    positive_words, negative_words = load_dictionary(path)
    tokens = tokenize(text)
    total = len(tokens)
    if total == 0:
        return LexiconScore(score=0.0, positive=0, negative=0, total_words=0)

    positive = sum(1 for t in tokens if t in positive_words)
    negative = sum(1 for t in tokens if t in negative_words)
    return LexiconScore(
        score=(positive - negative) / total,
        positive=positive,
        negative=negative,
        total_words=total,
    )


def score_to_probability(score: float, scale: float = 0.02) -> float:
    """Map a sentiment score onto the §7 probability range [0.50, 1.00].

    §7 fixes the output format at a direction plus a confidence in [0.50, 1.00], so the
    baseline has to produce the same shape as the LLM or the two cannot be compared or
    put through the same portfolio construction.

    `scale` is the score magnitude treated as full confidence. It is a *presentation*
    choice, not a tuned parameter: it is monotonic in |score|, so it cannot change the
    quintile ranking in §9 or the direction, and therefore cannot alter H1 or H3. It does
    affect the Brier score, so the calibration of this baseline should be read as
    "the mapping is arbitrary" rather than as a claim about the dictionary.
    """
    magnitude = min(abs(score) / scale, 1.0)
    return 0.50 + 0.50 * magnitude
