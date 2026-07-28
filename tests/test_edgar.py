"""EDGAR parsing.

The timezone assertions here are the highest-value tests in Phase 1. EDGAR records
acceptance in Eastern time; every downstream timing rule is stated in Eastern time; and
the database stores UTC. Getting that chain wrong shifts every event by five hours
without raising anything, which would move filings across the 16:00 cutoff silently.

The Apple fixture is real: accession 0000320193-18-000005 reports 20180201163017 in the
archive header and 2018-02-01T21:30:17Z from the submissions API.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hindsight import config
from hindsight.ingest import edgar
from hindsight.ingest.universe import Membership
from hindsight.manifest import RunManifest

# Angle brackets arrive HTML-escaped inside index-headers.html, as they do live.
APPLE_HEADERS = """<html><body><pre>
&lt;SEC-DOCUMENT&gt;0000320193-18-000005.txt : 20180201
&lt;ACCEPTANCE-DATETIME&gt;20180201163017
ACCESSION NUMBER:		0000320193-18-000005
CONFORMED SUBMISSION TYPE:	8-K
PUBLIC DOCUMENT COUNT:		4
CONFORMED PERIOD OF REPORT:	20180201
&lt;PERIOD&gt;20180201
&lt;ITEMS&gt;2.02
&lt;ITEMS&gt;9.01
FILED AS OF DATE:		20180201
COMPANY CONFORMED NAME:			APPLE INC
CENTRAL INDEX KEY:			0000320193
&lt;DOCUMENT&gt;
&lt;TYPE&gt;8-K
&lt;SEQUENCE&gt;1
&lt;FILENAME&gt;a8-kq1201812302017.htm
&lt;DESCRIPTION&gt;8-K
&lt;DOCUMENT&gt;
&lt;TYPE&gt;EX-99.1
&lt;SEQUENCE&gt;2
&lt;FILENAME&gt;a8-kexhibit991q12018123020.htm
&lt;DESCRIPTION&gt;EXHIBIT 99.1
&lt;DOCUMENT&gt;
&lt;TYPE&gt;GRAPHIC
&lt;SEQUENCE&gt;4
&lt;FILENAME&gt;g325078g0426062022046a05.jpg
&lt;/SEC-DOCUMENT&gt;
</pre></body></html>"""


class TestAcceptanceTimestamp:
    def test_header_time_is_eastern_not_utc(self) -> None:
        meta = edgar.parse_filing_headers(APPLE_HEADERS, "0000320193-18-000005", 320193)
        assert meta.accepted_at_et.hour == 16
        assert meta.accepted_at_et.minute == 30
        # Cross-checked against the live submissions API.
        assert meta.accepted_at_utc.isoformat() == "2018-02-01T21:30:17+00:00"

    def test_winter_filing_offset_is_five_hours(self) -> None:
        meta = edgar.parse_filing_headers(
            APPLE_HEADERS.replace("20180201163017", "20180115090000"), "x", 1
        )
        assert meta.accepted_at_utc.isoformat() == "2018-01-15T14:00:00+00:00"

    def test_summer_filing_offset_is_four_hours(self) -> None:
        # Same wall-clock time in July is EDT (UTC-4). A fixed offset would be wrong here.
        meta = edgar.parse_filing_headers(
            APPLE_HEADERS.replace("20180201163017", "20180716090000"), "x", 1
        )
        assert meta.accepted_at_utc.isoformat() == "2018-07-16T13:00:00+00:00"

    def test_missing_acceptance_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match="no ACCEPTANCE-DATETIME"):
            edgar.parse_filing_headers("<html>nothing here</html>", "x", 1)

    def test_empty_acceptance_tag_does_not_borrow_the_next_line(self) -> None:
        """Real EDGAR case: 8 of 6,751 filings in 2018 emit the tag with no value.

        The parser must fail rather than run past the newline and adopt a following
        field's digits as a timestamp — an invented entry time no one would notice.
        """
        broken = (
            "&lt;ACCEPTANCE-DATETIME&gt;\n"
            "&lt;ACCESSION-NUMBER&gt;0000033185-18-000035\n"
            "&lt;PERIOD&gt;20181001\n"
        )
        with pytest.raises(ValueError, match="no ACCEPTANCE-DATETIME"):
            edgar.parse_filing_headers(broken, "0000033185-18-000035", 33185)


class TestHeaderFields:
    def test_period_and_items(self) -> None:
        meta = edgar.parse_filing_headers(APPLE_HEADERS, "0000320193-18-000005", 320193)
        assert meta.period_of_report == "2018-02-01"
        assert meta.item_codes == "2.02,9.01"

    def test_documents_include_exhibits_and_graphics(self) -> None:
        meta = edgar.parse_filing_headers(APPLE_HEADERS, "0000320193-18-000005", 320193)
        types = [d.doc_type for d in meta.documents]
        assert types == ["8-K", "EX-99.1", "GRAPHIC"]

    def test_only_body_and_ex99_are_wanted(self) -> None:
        wanted = [
            d
            for d in edgar.parse_filing_headers(APPLE_HEADERS, "a", 1).documents
            if edgar._WANTED_DOC_TYPES.match(d.doc_type)
        ]
        assert [d.doc_type for d in wanted] == ["8-K", "EX-99.1"]


class TestAcceptanceWindow:
    """PREREGISTRATION §3: acceptance must fall inside 04:00-20:00 ET."""

    @pytest.mark.parametrize(
        "hour,minute,expected",
        [
            (3, 59, False),
            (4, 0, True),
            (16, 30, True),
            (20, 0, True),
            (20, 1, False),
            (23, 30, False),
        ],
    )
    def test_window_boundaries(self, hour: int, minute: int, expected: bool) -> None:
        dt = datetime(2018, 6, 15, hour, minute, tzinfo=config.MARKET_TZ)
        assert edgar.in_acceptance_window(dt) is expected


class TestMasterIndex:
    IDX = """Description:           Master Index
CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------
320193|APPLE INC|8-K|2018-02-01|edgar/data/320193/0000320193-18-000005.txt
789019|MICROSOFT CORP|10-Q|2018-01-31|edgar/data/789019/0001193125-18-000010.txt
1018724|AMAZON COM INC|8-K/A|2018-02-02|edgar/data/1018724/0001193125-18-000011.txt
66740|3M CO|8-K|2018-01-25|edgar/data/66740/0000066740-18-000007.txt
"""

    def test_keeps_only_exact_8k(self) -> None:
        rows = edgar.parse_master_index(self.IDX)
        assert [r.cik for r in rows] == [320193, 66740]

    def test_amendments_are_not_treated_as_new_events(self) -> None:
        rows = edgar.parse_master_index(self.IDX)
        assert all(r.form_type == "8-K" for r in rows)
        assert not any(r.form_type == "8-K/A" for r in rows)

    def test_accession_derived_from_filename(self) -> None:
        rows = edgar.parse_master_index(self.IDX)
        assert rows[0].accession_no == "0000320193-18-000005"

    def test_malformed_lines_are_skipped_not_fatal(self) -> None:
        rows = edgar.parse_master_index(self.IDX + "garbage|line\n999|X|8-K|not-a-date|f.txt\n")
        assert len(rows) == 2


class TestDeduplication:
    """Co-registrants produce one index row each for a single filing."""

    ACC = "0000066740-18-000007"

    @staticmethod
    def matcher() -> edgar.UniverseMatcher:
        # Only 3M (CIK 66740) is an index member; the financing subsidiary is not.
        return edgar.UniverseMatcher(
            [Membership("MMM", "3M Company", 66740, date(2000, 1, 1), None)]
        )

    def _rows(self, subsidiary_first: bool) -> list[edgar.IndexRow]:
        member = f"66740|3M CO|8-K|2018-01-25|edgar/data/66740/{self.ACC}.txt"
        sub = f"66741|3M FINANCE SUBSIDIARY|8-K|2018-01-25|edgar/data/66740/{self.ACC}.txt"
        order = [sub, member] if subsidiary_first else [member, sub]
        header = "CIK|Company Name|Form Type|Date Filed|Filename\n"
        return edgar.parse_master_index(header + "\n".join(order) + "\n")

    def test_repeated_accession_is_collapsed(self) -> None:
        rows = self._rows(subsidiary_first=False)
        assert len(rows) == 2
        assert len(edgar.deduplicate_index_rows(rows, self.matcher())) == 1

    def test_member_wins_when_listed_first(self) -> None:
        deduped = edgar.deduplicate_index_rows(self._rows(subsidiary_first=False), self.matcher())
        assert deduped[0].cik == 66740

    def test_member_wins_even_when_listed_second(self) -> None:
        """The regression: a plain first-wins collapse loses this filing entirely."""
        deduped = edgar.deduplicate_index_rows(self._rows(subsidiary_first=True), self.matcher())
        assert deduped[0].cik == 66740

    def test_collapsed_rows_are_counted(self) -> None:
        manifest = RunManifest("test")
        edgar.deduplicate_index_rows(self._rows(subsidiary_first=True), self.matcher(), manifest)
        assert manifest.counts["duplicate_index_rows_collapsed"] == 1

    def test_no_duplicates_is_a_no_op(self) -> None:
        rows = edgar.parse_master_index(TestMasterIndex.IDX)
        matcher = edgar.UniverseMatcher(
            [Membership("MMM", "3M Company", 66740, date(2000, 1, 1), None)]
        )
        assert edgar.deduplicate_index_rows(rows, matcher) == rows


class TestUniverseMatcher:
    """Matching a filing to the ticker that was in the index *on the filing date*."""

    MEMBERS = [
        Membership("AAPL", "Apple Inc.", 320193, date(2000, 1, 1), None),
        # Left the index in 2016 but must still match 2014 filings.
        Membership("YHOO", "Yahoo Inc.", 1011006, date(2000, 1, 1), date(2016, 6, 20)),
        # CIK never resolved (delisted): only a name match can find it.
        Membership("ABKX", "Ambac Financial Group", None, date(2005, 1, 1), date(2010, 5, 1)),
    ]

    @pytest.fixture
    def matcher(self) -> edgar.UniverseMatcher:
        return edgar.UniverseMatcher(self.MEMBERS)

    def test_matches_by_cik(self, matcher: edgar.UniverseMatcher) -> None:
        assert matcher.match(320193, "APPLE INC", date(2018, 2, 1)) == ("AAPL", "cik")

    def test_departed_member_matches_before_it_left(self, matcher: edgar.UniverseMatcher) -> None:
        assert matcher.match(1011006, "YAHOO INC", date(2014, 5, 1)) == ("YHOO", "cik")

    def test_departed_member_does_not_match_after(self, matcher: edgar.UniverseMatcher) -> None:
        assert matcher.match(1011006, "YAHOO INC", date(2018, 5, 1)) == (None, "none")

    def test_name_fallback_when_cik_unknown(self, matcher: edgar.UniverseMatcher) -> None:
        ticker, how = matcher.match(874501, "AMBAC FINANCIAL GROUP INC", date(2009, 3, 1))
        assert (ticker, how) == ("ABKX", "name")

    def test_non_member_does_not_match(self, matcher: edgar.UniverseMatcher) -> None:
        assert matcher.match(999999, "SOME PRIVATE CO", date(2018, 1, 1)) == (None, "none")


class TestNameNormalization:
    def test_corporate_suffixes_are_ignored(self) -> None:
        assert edgar.normalize_company_name("APPLE INC") == edgar.normalize_company_name(
            "Apple, Inc."
        )
        assert edgar.normalize_company_name("3M CO") == edgar.normalize_company_name("3M Company")

    def test_distinct_companies_stay_distinct(self) -> None:
        assert edgar.normalize_company_name("APPLE INC") != edgar.normalize_company_name(
            "APPLIED MATERIALS INC"
        )


class TestHtmlExtraction:
    def test_tables_do_not_fuse_words(self) -> None:
        html = "<table><tr><td>Net</td><td>Sales</td></tr></table>"
        assert "Net Sales" in edgar.html_to_text(html)

    def test_script_and_style_removed(self) -> None:
        text = edgar.html_to_text(
            "<style>.x{color:red}</style><p>Revenue rose</p><script>x=1</script>"
        )
        assert "Revenue rose" in text
        assert "color:red" not in text and "x=1" not in text

    def test_nbsp_becomes_space(self) -> None:
        assert "\xa0" not in edgar.html_to_text("<p>a&nbsp;b</p>")
