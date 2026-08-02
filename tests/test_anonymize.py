"""Anonymization is the experiment.

If the issuer leaks, the study stops measuring "can a model forecast from a disclosure?"
and starts measuring "does the model remember what happened to this company?" — which it
does, because it was trained on the outcome. So these tests assert zero leakage on names
in headers, footers and mid-sentence, per CLAUDE.md, and that the scorer structurally
cannot be handed un-anonymized text.
"""

from __future__ import annotations

import pytest

from hindsight.score import anonymize as anon


class TestNameVariants:
    def test_drops_corporate_suffixes(self) -> None:
        variants = anon.name_variants("Wells Fargo & Company")
        assert "Wells Fargo" in variants
        assert "Company" not in variants

    def test_longest_first(self) -> None:
        variants = anon.name_variants("Wells Fargo & Company")
        assert variants == sorted(variants, key=len, reverse=True)

    def test_generic_head_token_is_not_redactable(self) -> None:
        # Redacting "General" would also blank "general and administrative expenses".
        assert "General" not in anon.name_variants("General Electric Company")
        assert "General Electric" in anon.name_variants("General Electric Company")

    def test_distinctive_head_token_is_kept(self) -> None:
        assert "Netflix" in anon.name_variants("Netflix, Inc.")

    def test_empty_name_yields_nothing(self) -> None:
        assert anon.name_variants("") == []


class TestCompanyNameRemoval:
    HEADER_FOOTER_BODY = """
    APPLE INC
    One Apple Park Way, Cupertino, California 95014

    Apple Inc. today announced financial results. Revenue at Apple grew sharply,
    and management at Apple Inc noted continued momentum.

    Signed on behalf of APPLE INC.
    """

    @pytest.fixture
    def cleaned(self) -> anon.AnonymizationResult:
        return anon.anonymize(
            self.HEADER_FOOTER_BODY, company_name="Apple Inc.", ticker="AAPL", cik=320193
        )

    def test_no_leaks_reported(self, cleaned: anon.AnonymizationResult) -> None:
        assert [leak for leak in cleaned.leaks if leak.startswith("company_name")] == []

    def test_name_gone_from_header(self, cleaned: anon.AnonymizationResult) -> None:
        assert "APPLE INC" not in cleaned.text

    def test_name_gone_from_midsentence(self, cleaned: anon.AnonymizationResult) -> None:
        assert "Apple" not in cleaned.text

    def test_name_gone_from_footer(self, cleaned: anon.AnonymizationResult) -> None:
        assert "behalf of [COMPANY]" in cleaned.text

    def test_case_insensitive(self, cleaned: anon.AnonymizationResult) -> None:
        assert "apple" not in cleaned.text.lower()

    def test_placeholder_is_present(self, cleaned: anon.AnonymizationResult) -> None:
        assert anon.COMPANY in cleaned.text

    def test_surrounding_prose_survives(self, cleaned: anon.AnonymizationResult) -> None:
        assert "announced financial results" in cleaned.text
        assert "continued momentum" in cleaned.text


class TestFormerNames:
    def test_former_name_is_removed(self) -> None:
        # EDGAR headers carry FORMER-CONFORMED-NAME, and a former name identifies just
        # as well as the current one.
        result = anon.anonymize(
            "Apple Computer Inc changed its name. Apple Inc continues to trade.",
            company_name="Apple Inc",
            former_names=["Apple Computer Inc"],
        )
        assert "Apple" not in result.text
        assert not [leak for leak in result.leaks if leak.startswith("company_name")]


class TestTickerRemoval:
    def test_bare_ticker(self) -> None:
        assert "AAPL" not in anon.anonymize("Shares of AAPL rose.", ticker="AAPL").text

    def test_exchange_prefixed_ticker(self) -> None:
        result = anon.anonymize("The company (NASDAQ: AAPL) reported.", ticker="AAPL")
        assert "AAPL" not in result.text
        assert anon.TICKER in result.text

    def test_ticker_inside_word_is_untouched(self) -> None:
        # Word-boundary anchored: "CAT" must not corrupt "CATEGORY".
        assert "CATEGORY" in anon.anonymize("CATEGORY totals", ticker="CAT").text


class TestDateRemoval:
    """§6 replaces dates with relative language: a date is most of an identification."""

    @pytest.mark.parametrize(
        "raw",
        [
            "on February 1, 2018 the board met",
            "on 1 February 2018 the board met",
            "on 02/01/2018 the board met",
            "on 2018-02-01 the board met",
            "in February 2018 the board met",
        ],
    )
    def test_date_formats_are_removed(self, raw: str) -> None:
        result = anon.anonymize(raw)
        assert "2018" not in result.text
        assert not [leak for leak in result.leaks if leak.startswith(("date", "year"))]

    def test_bare_year_removed(self) -> None:
        assert "2018" not in anon.anonymize("results for 2018 were strong").text

    def test_quarter_becomes_relative_language(self) -> None:
        result = anon.anonymize("revenue for the fourth quarter of 2018 rose")
        assert "the relevant quarter" in result.text
        assert "2018" not in result.text

    def test_non_year_numbers_survive(self) -> None:
        # Redacting every 4-digit number would destroy the financials being reasoned about.
        text = anon.anonymize("revenue of $8,432 million and 1,234 units").text
        assert "8,432" in text and "1,234" in text


class TestPersonRemoval:
    def test_signature_block(self) -> None:
        result = anon.anonymize("/s/ Timothy D. Cook")
        assert "Cook" not in result.text
        assert anon.PERSON in result.text

    def test_honorific(self) -> None:
        assert "Cook" not in anon.anonymize("Mr. Timothy Cook said").text

    def test_name_then_title(self) -> None:
        result = anon.anonymize("Luca Maestri, Chief Financial Officer, commented")
        assert "Maestri" not in result.text

    def test_title_then_name(self) -> None:
        result = anon.anonymize("Chief Executive Officer Timothy Cook said")
        assert "Cook" not in result.text


class TestStructuralIdentifiers:
    def test_address(self) -> None:
        assert "Apple Park Way" not in anon.anonymize("One Apple Park Way, Cupertino").text

    def test_spelled_out_street_number(self) -> None:
        # "One Apple Park Way" — a digit-anchored pattern misses this entirely.
        assert "Apple Park Way" not in anon.anonymize("One Apple Park Way, Cupertino").text

    def test_city_before_state_is_removed(self) -> None:
        # A city identifies the issuer: Los Gatos means Netflix, Bentonville means Walmart.
        result = anon.anonymize("headquartered in Los Gatos, California")
        assert "Los Gatos" not in result.text

    def test_city_before_two_letter_state_code(self) -> None:
        # Found by hand inspection of a real filing: "Voorhees, NJ" names American Water.
        result = anon.anonymize("offices at Voorhees, NJ 08043")
        assert "Voorhees" not in result.text
        assert "NJ" not in result.text

    def test_two_letter_state_word_is_not_redacted_bare(self) -> None:
        # IN, OR, ME, OK, HI and DE are ordinary words; only redact them after a comma.
        text = anon.anonymize("increases IN revenue OR margin, whichever is greater").text
        assert "IN revenue OR margin" in text

    def test_document_filename_is_removed(self) -> None:
        # EDGAR primary documents are named like "aapl-20180201.htm" — ticker and date
        # in a single token.
        result = anon.anonymize("attached as aapl-20180201.htm to this report")
        assert "aapl" not in result.text.lower()
        assert "20180201" not in result.text

    def test_washington_dc_is_removed(self) -> None:
        assert "D.C." not in anon.anonymize("Washington, D.C. 20549").text

    def test_sec_boilerplate_leaves_no_residual_leak(self) -> None:
        """Every 8-K carries the SEC's own address; it must not read as a leak forever.

        Ordering bug: replacing "D.C." after the city pass stranded "WASHINGTON, [STATE]"
        on all 500 filings in the pilot, reported as a 20.8% leak rate that was entirely
        this one phrase.
        """
        result = anon.anonymize(
            "UNITED STATES SECURITIES AND EXCHANGE COMMISSION WASHINGTON, D.C. 20549"
        )
        assert result.leaks == []

    def test_phone(self) -> None:
        assert "555-123-4567" not in anon.anonymize("call (555) 123-4567").text

    def test_zip(self) -> None:
        assert "95014" not in anon.anonymize("Cupertino, CA 95014").text

    def test_cik_by_number(self) -> None:
        assert "320193" not in anon.anonymize("filer 0000320193 reports", cik=320193).text

    def test_cik_by_label(self) -> None:
        assert anon.IDNUM in anon.anonymize("Central Index Key: 0000320193").text

    def test_state_of_incorporation(self) -> None:
        assert "Delaware" not in anon.anonymize("a Delaware corporation").text

    def test_exchange(self) -> None:
        assert (
            "New York Stock Exchange"
            not in anon.anonymize("listed on the New York Stock Exchange").text
        )

    def test_auditor(self) -> None:
        assert "KPMG" not in anon.anonymize("audited by KPMG LLP").text

    def test_transfer_agent(self) -> None:
        assert "Computershare" not in anon.anonymize("contact Computershare for details").text

    def test_url_and_email(self) -> None:
        result = anon.anonymize("see www.apple.com or write ir@apple.com")
        assert "apple.com" not in result.text


class TestLeakDetectionIsIndependent:
    """find_leaks re-derives what should be gone rather than trusting the redactor."""

    def test_detects_a_name_the_redactor_missed(self) -> None:
        leaks = anon.find_leaks("Netflix reported results", company_name="Netflix, Inc.")
        assert any(leak.startswith("company_name") for leak in leaks)

    def test_detects_ticker(self) -> None:
        assert any(
            leak.startswith("ticker") for leak in anon.find_leaks("NFLX rose", ticker="NFLX")
        )

    def test_detects_cik(self) -> None:
        assert any(leak.startswith("cik") for leak in anon.find_leaks("1065280 filed", cik=1065280))

    def test_detects_residual_date(self) -> None:
        assert any(
            leak.startswith(("date", "year")) for leak in anon.find_leaks("on March 3, 2018")
        )

    def test_clean_text_has_no_leaks(self) -> None:
        assert anon.find_leaks("[COMPANY] reported higher revenue in [PERIOD]") == []


class TestEnforcement:
    """Invariant 3: the scorer refuses un-anonymized text. Structurally, not by comment."""

    def test_rejects_missing_version(self) -> None:
        with pytest.raises(anon.NotAnonymizedError, match="expected"):
            anon.assert_anonymized("[COMPANY] reported", None)

    def test_rejects_stale_version(self) -> None:
        with pytest.raises(anon.NotAnonymizedError, match="expected"):
            anon.assert_anonymized("[COMPANY] reported", "anon-v0")

    def test_rejects_correct_version_but_leaky_text(self) -> None:
        # The stamp is not enough — a bug that stamps without redacting must still fail.
        with pytest.raises(anon.NotAnonymizedError, match="identifier-shaped"):
            anon.assert_anonymized("Results announced on March 3, 2018", anon.ANON_VERSION)

    def test_accepts_clean_current_text(self) -> None:
        anon.assert_anonymized("[COMPANY] reported higher revenue", anon.ANON_VERSION)


class TestEndToEndFiling:
    FILING = """
    UNITED STATES SECURITIES AND EXCHANGE COMMISSION
    FORM 8-K
    NETFLIX, INC.
    (Exact name of registrant as specified in its charter)
    Delaware 001-35727 77-0467272
    100 Winchester Circle, Los Gatos, California 95032
    (408) 540-3700
    Securities registered: Common Stock, NASDAQ: NFLX

    Item 2.02 On January 22, 2018, Netflix, Inc. announced results for the fourth
    quarter of 2018. Reed Hastings, Chief Executive Officer, said streaming revenue
    grew 35% to $3,286 million. Contact ir@netflix.com or www.netflix.com.

    /s/ Reed Hastings
    """

    @pytest.fixture
    def result(self) -> anon.AnonymizationResult:
        return anon.anonymize(self.FILING, company_name="Netflix, Inc.", ticker="NFLX", cik=1065280)

    def test_zero_leaks(self, result: anon.AnonymizationResult) -> None:
        assert result.leaks == []

    def test_is_clean(self, result: anon.AnonymizationResult) -> None:
        assert result.is_clean

    @pytest.mark.parametrize(
        "identifier",
        [
            "Netflix",
            "NFLX",
            "1065280",
            "Reed Hastings",
            "Los Gatos",
            "Delaware",
            "January 22",
            "2018",
            "540-3700",
            "95032",
            "netflix.com",
        ],
    )
    def test_identifier_absent(self, result: anon.AnonymizationResult, identifier: str) -> None:
        assert identifier not in result.text

    def test_financial_substance_survives(self, result: anon.AnonymizationResult) -> None:
        # The model still needs something to reason about.
        assert "3,286" in result.text
        assert "35%" in result.text
        assert "streaming revenue" in result.text

    def test_passes_the_scorer_gate(self, result: anon.AnonymizationResult) -> None:
        anon.assert_anonymized(result.text, result.version)

    def test_replacements_are_counted(self, result: anon.AnonymizationResult) -> None:
        assert result.total_replacements > 0
        assert "company_name" in result.replacements
