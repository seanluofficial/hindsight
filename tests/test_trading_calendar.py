"""The calendar underpins every date in the study. A weekday is not a trading day."""

from __future__ import annotations

from datetime import date

import pytest

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
