"""Contamination-audit grading (§6).

Grading errs toward counting a guess as correct. Understating contamination is the
dangerous direction: it is what would let a memorised outcome pass as a forecast, which is
precisely the failure the project is named after.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_contamination import distinctive_tokens, is_correct  # noqa: E402


class TestDistinctiveTokens:
    def test_drops_corporate_boilerplate(self) -> None:
        assert distinctive_tokens("Apple Inc.") == {"APPLE"}

    def test_drops_generic_industry_words(self) -> None:
        # "American Energy Company" is all filler — nothing here identifies anyone.
        assert distinctive_tokens("American Energy Company") == set()

    def test_keeps_multiple_distinctive_tokens(self) -> None:
        assert distinctive_tokens("Wells Fargo & Company") == {"WELLS", "FARGO"}

    def test_ignores_short_tokens(self) -> None:
        assert "3M" not in distinctive_tokens("3M Co")


class TestGrading:
    def test_exact_ticker_counts(self) -> None:
        assert is_correct("", "AAPL", "AAPL", "Apple Inc.")

    def test_ticker_case_insensitive(self) -> None:
        assert is_correct("", "aapl", "AAPL", "Apple Inc.")

    def test_exact_name_counts(self) -> None:
        assert is_correct("Apple Inc.", "", "AAPL", "Apple Inc.")

    def test_partial_name_counts(self) -> None:
        # A partial hit still means the model knows who filed.
        assert is_correct("Apple", "unknown", "AAPL", "Apple Inc.")

    def test_wrong_company_does_not_count(self) -> None:
        assert not is_correct("Microsoft Corporation", "MSFT", "AAPL", "Apple Inc.")

    def test_unknown_does_not_count(self) -> None:
        assert not is_correct("unknown", "unknown", "AAPL", "Apple Inc.")

    def test_empty_does_not_count(self) -> None:
        assert not is_correct("", "", "AAPL", "Apple Inc.")

    def test_generic_overlap_does_not_count(self) -> None:
        """ "American ... Company" overlapping "American ... Company" is not identification."""
        assert not is_correct(
            "American Standard Company", "", "AWK", "American Water Works Company"
        )

    @pytest.mark.parametrize(
        "guess,expected",
        [("Netflix", True), ("Netflix Inc", True), ("NETFLIX, INC.", True), ("Roku", False)],
    )
    def test_name_variants(self, guess: str, expected: bool) -> None:
        assert is_correct(guess, "", "NFLX", "Netflix, Inc.") is expected


class TestThresholdRule:
    """§6 fixes the consequence in advance, so it cannot be decided after seeing the number."""

    def test_threshold_is_twenty_percent(self) -> None:
        from hindsight import config

        assert config.CONTAMINATION_IDENTIFICATION_THRESHOLD == 0.20

    def test_sample_size_is_five_hundred(self) -> None:
        from hindsight import config

        assert config.CONTAMINATION_SAMPLE_SIZE == 500
