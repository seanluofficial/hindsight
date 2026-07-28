"""The calendar underpins every date in the study. A weekday is not a trading day."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hindsight import config
from hindsight import trading_calendar as tc


class TestHolidays:
    def test_weekend_is_not_a_trading_day(self) -> None:
        assert not tc.is_trading_day(date(2018, 1, 6))  # Saturday
        assert not tc.is_trading_day(date(2018, 1, 7))  # Sunday

    @pytest.mark.parametrize(
        "holiday",
        [
            date(2018, 1, 1),  # New Year's Day
            date(2018, 1, 15),  # MLK
            date(2018, 2, 19),  # Presidents' Day
            date(2018, 3, 30),  # Good Friday — moves every year
            date(2018, 5, 28),  # Memorial Day
            date(2018, 7, 4),  # Independence Day
            date(2018, 9, 3),  # Labor Day
            date(2018, 11, 22),  # Thanksgiving
            date(2018, 12, 25),  # Christmas
        ],
    )
    def test_2018_market_holidays_are_closed(self, holiday: date) -> None:
        assert not tc.is_trading_day(holiday)

    def test_national_day_of_mourning_bush_funeral(self) -> None:
        # The NYSE closed 2018-12-05, a Wednesday. A naive weekday calendar misses this.
        assert not tc.is_trading_day(date(2018, 12, 5))

    def test_2018_has_251_sessions(self) -> None:
        sessions = tc.trading_days(date(2018, 1, 1), date(2018, 12, 31))
        assert len(sessions) == 251


class TestNavigation:
    def test_next_trading_day_skips_weekend(self) -> None:
        assert tc.next_trading_day(date(2018, 1, 5)) == date(2018, 1, 8)  # Fri -> Mon

    def test_next_trading_day_skips_holiday(self) -> None:
        # Friday 2018-03-29 -> Good Friday closed -> Monday 2018-04-02
        assert tc.next_trading_day(date(2018, 3, 29)) == date(2018, 4, 2)

    def test_next_trading_day_is_strict(self) -> None:
        assert tc.next_trading_day(date(2018, 1, 8)) == date(2018, 1, 9)

    def test_previous_trading_day_is_strict(self) -> None:
        assert tc.previous_trading_day(date(2018, 1, 8)) == date(2018, 1, 5)

    def test_trading_day_on_or_after_is_not_strict(self) -> None:
        assert tc.trading_day_on_or_after(date(2018, 1, 8)) == date(2018, 1, 8)
        assert tc.trading_day_on_or_after(date(2018, 1, 6)) == date(2018, 1, 8)

    def test_add_trading_days_crosses_thanksgiving(self) -> None:
        # Wed 2018-11-21; Thu closed; +1 session is Fri 2018-11-23.
        assert tc.add_trading_days(date(2018, 11, 21), 1) == date(2018, 11, 23)

    def test_add_zero_is_identity(self) -> None:
        assert tc.add_trading_days(date(2018, 6, 15), 0) == date(2018, 6, 15)

    def test_add_five_sessions(self) -> None:
        # Mon 2018-06-04 + 5 sessions = Mon 2018-06-11.
        assert tc.add_trading_days(date(2018, 6, 4), 5) == date(2018, 6, 11)

    def test_add_trading_days_rejects_non_session_start(self) -> None:
        with pytest.raises(ValueError, match="not a trading day"):
            tc.add_trading_days(date(2018, 1, 6), 1)

    def test_add_trading_days_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            tc.add_trading_days(date(2018, 6, 4), -1)


def et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    """An Eastern wall-clock instant, as the market experiences it."""
    return datetime(y, m, d, hh, mm, tzinfo=config.MARKET_TZ)


class TestEntryTimingCutoff:
    """PREREGISTRATION §4. These fix the price every position is opened at."""

    # Mon 2018-03-05 .. Fri 2018-03-09 is a clean week: no holidays either side.
    def test_1559_enters_next_open(self) -> None:
        assert tc.entry_date_for(et(2018, 3, 5, 15, 59)) == date(2018, 3, 6)

    def test_1601_skips_an_open(self) -> None:
        assert tc.entry_date_for(et(2018, 3, 5, 16, 1)) == date(2018, 3, 7)

    def test_exactly_1600_is_after_the_cutoff(self) -> None:
        # §4 says "at or after 16:00", so 16:00:00 itself belongs to the later branch.
        assert tc.entry_date_for(et(2018, 3, 5, 16, 0)) == date(2018, 3, 7)

    def test_one_minute_apart_lands_a_day_apart(self) -> None:
        before = tc.entry_date_for(et(2018, 3, 5, 15, 59))
        after = tc.entry_date_for(et(2018, 3, 5, 16, 1))
        assert (before, after) == (date(2018, 3, 6), date(2018, 3, 7))

    def test_early_morning_still_enters_next_open(self) -> None:
        # 06:00 ET is pre-market but inside the §3 acceptance window, and before 16:00.
        assert tc.entry_date_for(et(2018, 3, 6, 6, 0)) == date(2018, 3, 7)


class TestEntryTimingWeekends:
    def test_friday_evening_enters_tuesday(self) -> None:
        # Fri 2018-03-09 after close: next open is Mon 12th, which is skipped.
        assert tc.entry_date_for(et(2018, 3, 9, 16, 1)) == date(2018, 3, 13)

    def test_friday_afternoon_enters_monday(self) -> None:
        assert tc.entry_date_for(et(2018, 3, 9, 15, 59)) == date(2018, 3, 12)

    def test_saturday_enters_tuesday(self) -> None:
        assert tc.entry_date_for(et(2018, 3, 10, 11, 0)) == date(2018, 3, 13)

    def test_sunday_enters_tuesday(self) -> None:
        assert tc.entry_date_for(et(2018, 3, 11, 11, 0)) == date(2018, 3, 13)

    def test_weekend_filings_agree_with_each_other(self) -> None:
        # The resolution of Q1: a Sunday filing must not enter later than a Saturday one.
        assert tc.entry_date_for(et(2018, 3, 10, 11, 0)) == tc.entry_date_for(
            et(2018, 3, 11, 11, 0)
        )

    def test_saturday_is_not_earlier_than_friday_evening(self) -> None:
        # A newer filing must never get an earlier entry than an older one.
        assert tc.entry_date_for(et(2018, 3, 10, 11, 0)) >= tc.entry_date_for(et(2018, 3, 9, 16, 1))


class TestEntryTimingHolidays:
    def test_day_before_thanksgiving_after_close(self) -> None:
        # Wed 2018-11-21 16:01. Thu 22nd closed, Fri 23rd is the next open and is
        # skipped, so entry is Mon 2018-11-26.
        assert tc.entry_date_for(et(2018, 11, 21, 16, 1)) == date(2018, 11, 26)

    def test_day_before_thanksgiving_during_session(self) -> None:
        assert tc.entry_date_for(et(2018, 11, 21, 15, 0)) == date(2018, 11, 23)

    def test_filed_on_a_holiday(self) -> None:
        # Thanksgiving itself: next open Fri 23rd is skipped -> Mon 26th.
        assert tc.entry_date_for(et(2018, 11, 22, 10, 0)) == date(2018, 11, 26)

    def test_good_friday_moves_with_the_year(self) -> None:
        # Thu 2018-03-29 after close; Good Friday closed; Mon 4/2 skipped -> Tue 4/3.
        assert tc.entry_date_for(et(2018, 3, 29, 16, 30)) == date(2018, 4, 3)

    def test_national_day_of_mourning_is_skipped(self) -> None:
        # Tue 2018-12-04 16:01. Wed 5th closed (Bush funeral), Thu 6th skipped -> Fri 7th.
        assert tc.entry_date_for(et(2018, 12, 4, 16, 1)) == date(2018, 12, 7)


class TestEntryTimingTimezone:
    def test_utc_input_is_converted_before_the_cutoff_is_applied(self) -> None:
        # 2018-02-01T21:30:17Z is 16:30 ET — after the cutoff, so an open is skipped.
        apple = datetime(2018, 2, 1, 21, 30, 17, tzinfo=config.UTC)
        assert tc.entry_date_for(apple) == date(2018, 2, 5)

    def test_utc_input_just_before_the_cutoff(self) -> None:
        # 20:59Z = 15:59 ET in February -> next open.
        assert tc.entry_date_for(datetime(2018, 2, 1, 20, 59, tzinfo=config.UTC)) == date(
            2018, 2, 2
        )

    def test_summer_utc_offset_is_four_hours(self) -> None:
        # 19:59Z in July = 15:59 EDT -> next open, not a skipped one.
        assert tc.entry_date_for(datetime(2018, 7, 16, 19, 59, tzinfo=config.UTC)) == date(
            2018, 7, 17
        )

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            tc.entry_date_for(datetime(2018, 3, 5, 16, 1))


class TestEntryTimingInvariants:
    @pytest.mark.parametrize(
        "moment",
        [
            et(2018, 3, 5, 9, 30),
            et(2018, 3, 5, 16, 1),
            et(2018, 3, 9, 16, 1),
            et(2018, 3, 10, 11, 0),
            et(2018, 11, 21, 16, 1),
            et(2018, 12, 31, 18, 0),
        ],
    )
    def test_entry_is_always_a_trading_day(self, moment: datetime) -> None:
        assert tc.is_trading_day(tc.entry_date_for(moment))

    @pytest.mark.parametrize(
        "moment",
        [
            et(2018, 3, 5, 9, 30),
            et(2018, 3, 5, 15, 59),
            et(2018, 3, 10, 11, 0),
            et(2018, 11, 21, 16, 1),
        ],
    )
    def test_entry_is_strictly_after_acceptance(self, moment: datetime) -> None:
        # Same-day returns are never used, at any horizon (§4).
        assert tc.entry_date_for(moment) > moment.date()

    def test_entry_is_monotonic_in_acceptance_time(self) -> None:
        """A later filing can never receive an earlier entry."""
        moments = [
            et(2018, 3, 5, 9, 0),
            et(2018, 3, 5, 15, 59),
            et(2018, 3, 5, 16, 1),
            et(2018, 3, 6, 9, 0),
            et(2018, 3, 9, 15, 59),
            et(2018, 3, 9, 16, 1),
            et(2018, 3, 10, 12, 0),
            et(2018, 3, 11, 12, 0),
            et(2018, 3, 12, 9, 0),
        ]
        entries = [tc.entry_date_for(m) for m in moments]
        assert entries == sorted(entries)
