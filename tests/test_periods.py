from __future__ import annotations

from datetime import date

from app.models import Period
from app.services.periods import (
    next_occurrence_after,
    occurrence_on_or_after,
    occurrences_between,
)


def test_monthly_anchor_keeps_end_of_month():
    first = date(2025, 1, 31)

    assert occurrence_on_or_after(first, Period.month, date(2025, 2, 1)) == date(2025, 2, 28)
    assert next_occurrence_after(first, Period.month, date(2025, 2, 28)) == date(2025, 3, 31)
    assert occurrence_on_or_after(first, Period.month, date(2025, 1, 1)) == first


def test_daily_period_returns_requested_day():
    first = date(2025, 1, 1)
    assert occurrence_on_or_after(first, Period.day, date(2025, 3, 1)) == date(2025, 3, 1)
    assert next_occurrence_after(first, Period.day, date(2025, 3, 1)) == date(2025, 3, 2)


def test_yearly_period_handles_leap_year():
    first = date(2024, 2, 29)
    assert occurrence_on_or_after(first, Period.year, date(2025, 1, 1)) == date(2025, 2, 28)
    assert next_occurrence_after(first, Period.year, date(2025, 2, 28)) == date(2026, 2, 28)


def test_occurrences_between():
    result = occurrences_between(date(2025, 1, 1), Period.day, date(2025, 1, 5), date(2025, 1, 14))
    assert len(result) == 10
    assert result[0] == date(2025, 1, 5)
    assert result[-1] == date(2025, 1, 14)

    monthly = occurrences_between(date(2025, 1, 31), Period.month, date(2025, 2, 1), date(2025, 5, 1))
    assert monthly == [date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]


def test_occurrences_between_invalid_range():
    assert occurrences_between(date(2025, 1, 1), Period.month, date(2025, 5, 1), date(2025, 1, 1)) == []
