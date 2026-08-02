"""The Loughran-McDonald baseline (§8). No tuning — that austerity is what makes H3 fair."""

from __future__ import annotations

import pytest

from hindsight.score import lexicon


class TestDictionary:
    def test_loads_published_counts(self) -> None:
        # Loughran-McDonald publishes 2,355 negative and 354 positive words.
        positive, negative = lexicon.load_dictionary()
        assert len(negative) == 2355
        assert len(positive) == 354

    def test_finance_specific_words_present(self) -> None:
        positive, negative = lexicon.load_dictionary()
        assert "ABANDON" in negative
        assert "ACCOMPLISH" in positive

    def test_words_are_uppercase(self) -> None:
        positive, negative = lexicon.load_dictionary()
        assert all(w.isupper() for w in list(negative)[:50])


class TestTokenize:
    def test_uppercases(self) -> None:
        assert lexicon.tokenize("Revenue grew") == ["REVENUE", "GREW"]

    def test_drops_numbers(self) -> None:
        assert lexicon.tokenize("revenue of 3,286 million") == ["REVENUE", "OF", "MILLION"]

    def test_drops_anonymizer_placeholders(self) -> None:
        # Placeholders are not words; counting them would dilute the denominator and
        # push every score toward zero.
        assert lexicon.tokenize("[COMPANY] reported [DATE]") == ["REPORTED"]

    def test_keeps_hyphenated_and_apostrophes(self) -> None:
        assert lexicon.tokenize("well-known company's") == ["WELL-KNOWN", "COMPANY'S"]


class TestScoring:
    def test_negative_text_scores_negative(self) -> None:
        result = lexicon.score_text("The company reported a loss and impairment and litigation")
        assert result.score < 0
        assert result.direction == "down"

    def test_positive_text_scores_positive(self) -> None:
        result = lexicon.score_text("strong gains achieved record profitable growth improvement")
        assert result.score > 0
        assert result.direction == "up"

    def test_score_is_the_preregistered_formula(self) -> None:
        # (positive - negative) / total words, exactly as §8 states.
        result = lexicon.score_text("loss gains revenue")
        expected = (result.positive - result.negative) / result.total_words
        assert result.score == pytest.approx(expected)

    def test_neutral_text_scores_zero(self) -> None:
        assert lexicon.score_text("the quick brown fox jumped").score == pytest.approx(0.0)

    def test_empty_text_does_not_divide_by_zero(self) -> None:
        result = lexicon.score_text("")
        assert result.score == 0.0
        assert result.total_words == 0

    def test_placeholder_only_text_is_safe(self) -> None:
        assert lexicon.score_text("[COMPANY] [DATE] [PERSON]").score == 0.0

    def test_deterministic(self) -> None:
        text = "revenue declined amid litigation but margins improved"
        assert lexicon.score_text(text) == lexicon.score_text(text)

    def test_ties_break_to_down_consistently(self) -> None:
        # Fixed in advance and applied uniformly; a coin flip would break invariant 4.
        assert lexicon.score_text("the quick brown fox").direction == "down"


class TestProbabilityMapping:
    def test_stays_inside_the_preregistered_range(self) -> None:
        # §7 fixes probability in [0.50, 1.00].
        for score in (-1.0, -0.05, -0.001, 0.0, 0.001, 0.05, 1.0):
            p = lexicon.score_to_probability(score)
            assert 0.50 <= p <= 1.00

    def test_zero_score_is_minimum_confidence(self) -> None:
        assert lexicon.score_to_probability(0.0) == pytest.approx(0.50)

    def test_is_monotonic_in_magnitude(self) -> None:
        # Monotonicity is what makes the mapping safe: it cannot reorder the quintiles
        # in §9, so it cannot affect H1 or H3.
        probs = [lexicon.score_to_probability(s) for s in (0.000, 0.005, 0.010, 0.015, 0.020)]
        assert probs == sorted(probs)

    def test_symmetric_in_sign(self) -> None:
        assert lexicon.score_to_probability(0.01) == lexicon.score_to_probability(-0.01)

    def test_saturates_rather_than_exceeding_one(self) -> None:
        assert lexicon.score_to_probability(99.0) == pytest.approx(1.0)


class TestScoringTextCap:
    """The lexicon and the LLM must read identical text (§8), so both go through the cap."""

    def test_short_text_is_untouched(self) -> None:
        from hindsight.score import anonymize as anon

        assert anon.scoring_text("short filing") == "short filing"

    def test_long_text_is_capped(self) -> None:
        from hindsight.score import anonymize as anon

        text = "word " * 10_000
        assert len(anon.scoring_text(text)) <= 12_000

    def test_cut_lands_on_a_word_boundary(self) -> None:
        from hindsight.score import anonymize as anon

        capped = anon.scoring_text("revenue " * 5_000)
        assert not capped.endswith("reven")

    def test_truncation_is_detectable(self) -> None:
        from hindsight.score import anonymize as anon

        assert anon.was_truncated("x" * 20_000)
        assert not anon.was_truncated("x" * 100)

    def test_explicit_cap_overrides_default(self) -> None:
        from hindsight.score import anonymize as anon

        assert len(anon.scoring_text("a b c d e f g h", max_chars=5)) <= 5


class TestRealFilingText:
    NEGATIVE = """
    [COMPANY] announced that it will restate previously issued financial statements
    following the discovery of material weakness in internal controls. The restatement
    relates to an impairment. Litigation is pending and the loss may be significant.
    """
    POSITIVE = """
    [COMPANY] reported record revenue, with strong growth and improved margins.
    Results exceeded expectations and the outlook is favorable, reflecting successful
    execution and profitable expansion.
    """

    def test_restatement_reads_negative(self) -> None:
        assert lexicon.score_text(self.NEGATIVE).score < 0

    def test_beat_reads_positive(self) -> None:
        assert lexicon.score_text(self.POSITIVE).score > 0

    def test_ranks_the_pair_correctly(self) -> None:
        assert lexicon.score_text(self.POSITIVE).score > lexicon.score_text(self.NEGATIVE).score
