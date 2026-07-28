"""NYSE trading-day arithmetic.

Never assume a weekday is a trading day. 2018 alone has nine market holidays, and
Good Friday moves every year. Everything here goes through a real NYSE calendar.

Note on scope: this module deliberately stops at calendar arithmetic. The §4 entry-timing
rule is built on top of it in the evaluate stage, not here.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal

from hindsight import config

# Padded beyond the study window so lookups near the edges never fall off the end.
_CALENDAR_START = date(2009, 1, 1)
_CALENDAR_END = date(2027, 12, 31)


@lru_cache(maxsize=1)
def _sessions() -> pd.DatetimeIndex:
    """All NYSE session dates in the padded window, ascending. Computed once."""
    cal = mcal.get_calendar(config.NYSE_CALENDAR_NAME)
    schedule = cal.schedule(start_date=_CALENDAR_START, end_date=_CALENDAR_END)
    return pd.DatetimeIndex(schedule.index).normalize()


@lru_cache(maxsize=1)
def _session_set() -> frozenset[date]:
    return frozenset(d.date() for d in _sessions())


def is_trading_day(day: date) -> bool:
    return day in _session_set()


def trading_days(start: date, end: date) -> list[date]:
    """Sessions in [start, end], inclusive."""
    idx = _sessions()
    mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    return [d.date() for d in idx[mask]]


def _session_at(idx: pd.DatetimeIndex, pos: int) -> date:
    """Positional lookup, narrowed to a plain `date` for callers."""
    stamp: pd.Timestamp = idx[pos]
    return stamp.date()


def next_trading_day(day: date) -> date:
    """First session strictly after `day`."""
    idx = _sessions()
    pos = int(idx.searchsorted(pd.Timestamp(day), side="right"))
    if pos >= len(idx):
        raise ValueError(f"no trading day after {day}; extend _CALENDAR_END")
    return _session_at(idx, pos)


def previous_trading_day(day: date) -> date:
    """Last session strictly before `day`."""
    idx = _sessions()
    pos = int(idx.searchsorted(pd.Timestamp(day), side="left")) - 1
    if pos < 0:
        raise ValueError(f"no trading day before {day}; extend _CALENDAR_START")
    return _session_at(idx, pos)


def trading_day_on_or_after(day: date) -> date:
    return day if is_trading_day(day) else next_trading_day(day)


def add_trading_days(day: date, n: int) -> date:
    """Session `n` places after `day`. `day` must itself be a session."""
    if n < 0:
        raise ValueError("n must be non-negative; use previous_trading_day to go back")
    idx = _sessions()
    pos = int(idx.searchsorted(pd.Timestamp(day), side="left"))
    if pos >= len(idx) or _session_at(idx, pos) != day:
        raise ValueError(f"{day} is not a trading day")
    if pos + n >= len(idx):
        raise ValueError(f"{day} + {n} sessions runs past the calendar; extend _CALENDAR_END")
    return _session_at(idx, pos + n)
