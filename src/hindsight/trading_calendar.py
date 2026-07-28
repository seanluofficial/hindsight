"""NYSE trading-day arithmetic, and the §4 entry-timing rule built on it.

Never assume a weekday is a trading day. 2018 alone has nine market holidays, Good Friday
moves every year, and the NYSE closed on Wednesday 2018-12-05 for a state funeral.
Everything here goes through a real NYSE calendar.

`entry_date_for()` implements PREREGISTRATION §4 — the single most important rule in the
project, since it fixes the price every position is opened at. It lives here rather than
in the evaluate stage because it is pure date arithmetic: no prices, no returns.
"""

from __future__ import annotations

from datetime import date, datetime
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


def entry_date_for(accepted_at_utc: datetime) -> date:
    """The session whose OPEN is the entry price for a filing (PREREGISTRATION §4).

    The rule, in one sentence: **filings that arrive while the market is open enter at the
    next open; everything else skips one open.**

        accepted before 16:00 ET on a trading day  ->  the next session's open
        accepted at/after 16:00 ET, or on a
        non-trading day                            ->  the session after that one

    Worked examples, all verified in the tests:

        Mon 15:59      -> Tue          (market was open; next open)
        Mon 16:01      -> Wed          (after close; Tuesday's open is skipped)
        Fri 16:01      -> Tue          (next open is Mon, skipped)
        Sat / Sun      -> Tue          (next open is Mon, skipped)
        Wed 16:01 before Thanksgiving  -> the following Mon

    Why the skipped open. A filing accepted after the close is first tradeable at the next
    morning's open, and that open frequently *gaps* on the news. Claiming that price
    invites the obvious objection that the fill was never realistically available. Giving
    it up costs a day of signal and buys a result that is harder to argue with — the right
    trade for a study whose deliverable is an honest measurement. If the edge only exists
    in the gap, that is itself a finding.

    Weekend and holiday filings are grouped with the after-close case because §4 groups
    them in one clause, and because treating them differently would mean a Saturday filing
    entered *earlier* than a Friday-evening one despite being newer.

    Same-day returns are never used at any horizon, which this guarantees: the returned
    date is always strictly after the acceptance date.
    """
    if accepted_at_utc.tzinfo is None:
        raise ValueError(
            "accepted_at_utc must be timezone-aware. A naive timestamp here would be "
            "silently read as local time and could land on the wrong side of the 16:00 "
            "ET cutoff."
        )

    eastern = accepted_at_utc.astimezone(config.MARKET_TZ)
    day = eastern.date()

    if is_trading_day(day) and eastern.time() < config.ENTRY_CUTOFF_ET:
        return next_trading_day(day)
    return next_trading_day(next_trading_day(day))
