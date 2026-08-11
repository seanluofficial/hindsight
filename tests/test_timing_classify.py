"""Experiment 007 — the buried/control classifier is timing logic, which fails silently.

Every case here is hand-checked against the NYSE calendar and the 16:00 ET cutoff. All
timestamps carry an explicit ET offset so the test states the local wall-clock it means
(EDT = -04:00 in summer, EST = -05:00 in winter).
"""

from __future__ import annotations

from hindsight.experiments.timing import classify, is_buried


def test_friday_after_close_is_weekend_burial() -> None:
    # Fri 2018-06-01 16:30 ET — filed after the close into the weekend.
    assert classify("2018-06-01T16:30:00-04:00") == "weekend"


def test_friday_at_exactly_close_is_buried() -> None:
    # 16:00 ET is on the after-close side of the cutoff (>=), so a Friday 16:00 is buried.
    assert classify("2018-06-01T16:00:00-04:00") == "weekend"


def test_friday_during_hours_is_control() -> None:
    # Fri 2018-06-01 15:00 ET — still in full view; enters Monday's open, not buried.
    assert classify("2018-06-01T15:00:00-04:00") == "control"


def test_saturday_is_weekend_burial() -> None:
    assert classify("2018-06-02T10:00:00-04:00") == "weekend"


def test_sunday_is_weekend_burial() -> None:
    assert classify("2018-06-03T10:00:00-04:00") == "weekend"


def test_wednesday_before_thanksgiving_after_close_is_preholiday() -> None:
    # Thu 2018-11-22 is Thanksgiving (market closed). Wed 17:00 ET files into that gap.
    assert classify("2018-11-21T17:00:00-05:00") == "preholiday"


def test_wednesday_before_thanksgiving_during_hours_is_control() -> None:
    # Same day, but filed during hours — enters the half-day Friday open, not buried.
    assert classify("2018-11-21T11:00:00-05:00") == "control"


def test_ordinary_weekday_after_close_is_control() -> None:
    # Tue 2018-06-05 17:00 ET — after hours but no weekend/holiday ahead: not buried.
    assert classify("2018-06-05T17:00:00-04:00") == "control"


def test_ordinary_weekday_during_hours_is_control() -> None:
    assert classify("2018-06-04T10:00:00-04:00") == "control"


def test_is_buried_matches_buckets() -> None:
    assert is_buried("weekend")
    assert is_buried("preholiday")
    assert not is_buried("control")
