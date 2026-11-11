"""Работа с периодичностью платежей."""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from ..models import Period


def next_occurrence_after(
    first_payment_date: date, period: Period, after: date
) -> date:
    """Ближайшая дата платежа строго позже указанной.

    Даты считаются от даты первого платежа (якоря), поэтому конец месяца
    не «съезжает»: 31.01 -> 28.02 -> 31.03.
    """
    if first_payment_date > after:
        return first_payment_date

    if period is Period.day:
        return after + timedelta(days=1)

    if period is Period.month:
        months = (after.year - first_payment_date.year) * 12 + (
            after.month - first_payment_date.month
        )
        candidate = first_payment_date + relativedelta(months=months)
        # Считаем от исходной даты, чтобы конец месяца не «съезжал»
        while candidate <= after:
            months += 1
            candidate = first_payment_date + relativedelta(months=months)
        return candidate

    years = after.year - first_payment_date.year
    candidate = first_payment_date + relativedelta(years=years)
    while candidate <= after:
        years += 1
        candidate = first_payment_date + relativedelta(years=years)
    return candidate


def occurrence_on_or_after(first_payment_date: date, period: Period, day: date) -> date:
    """Ближайшая дата платежа не раньше указанного дня."""
    if first_payment_date >= day:
        return first_payment_date
    return next_occurrence_after(first_payment_date, period, day - timedelta(days=1))


def occurrences_between(
    first_payment_date: date,
    period: Period,
    start: date,
    end: date,
    max_count: int = 366,
) -> list[date]:
    """Все даты платежей в интервале [start; end]."""
    if end < start:
        return []

    current = occurrence_on_or_after(first_payment_date, period, start)
    result: list[date] = []
    while current <= end and len(result) < max_count:
        result.append(current)
        current = next_occurrence_after(first_payment_date, period, current)
    return result
