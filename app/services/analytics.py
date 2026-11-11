"""Расчет аналитики по платежам пользователя."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import Payment, Subscription, SubscriptionStatus, utcnow
from .periods import occurrences_between


def _conditions(
    user_id: int,
    date_from: date | None,
    date_to: date | None,
    currency: str | None = None,
) -> list[Any]:
    conditions: list[Any] = [Payment.user_id == user_id]
    if date_from is not None:
        conditions.append(Payment.paid_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(Payment.paid_at <= datetime.combine(date_to, time.max))
    if currency:
        conditions.append(Payment.currency == currency)
    return conditions


def primary_currency(db: Session, user_id: int) -> str:
    """Валюта, в которой у пользователя больше всего платежей."""
    row = db.execute(
        select(Payment.currency, func.count(Payment.id).label("cnt"))
        .where(Payment.user_id == user_id)
        .group_by(Payment.currency)
        .order_by(func.count(Payment.id).desc())
        .limit(1)
    ).first()
    return row[0] if row is not None else settings.default_currency


def summary(
    db: Session,
    user_id: int,
    date_from: date | None,
    date_to: date | None,
    currency: str | None = None,
) -> dict[str, Any]:
    conditions = _conditions(user_id, date_from, date_to, currency)

    count, total, minimum, maximum = db.execute(
        select(
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0),
            func.min(Payment.amount),
            func.max(Payment.amount),
        ).where(*conditions)
    ).one()

    count = int(count or 0)
    total = float(total or 0)

    by_currency_rows = db.execute(
        select(Payment.currency, func.sum(Payment.amount), func.count(Payment.id))
        .where(*conditions)
        .group_by(Payment.currency)
        .order_by(func.sum(Payment.amount).desc())
    ).all()

    return {
        "date_from": date_from,
        "date_to": date_to,
        "payments_count": count,
        "total": round(total, 2),
        "average": round(total / count, 2) if count else 0.0,
        "min": round(float(minimum), 2) if minimum is not None else 0.0,
        "max": round(float(maximum), 2) if maximum is not None else 0.0,
        "by_currency": [
            {"currency": row[0], "total": round(float(row[1] or 0), 2), "count": int(row[2])}
            for row in by_currency_rows
        ],
    }


def by_category(
    db: Session,
    user_id: int,
    date_from: date | None,
    date_to: date | None,
    currency: str | None = None,
) -> dict[str, Any]:
    conditions = _conditions(user_id, date_from, date_to, currency)
    category_column = func.coalesce(Subscription.category, "Без категории")

    rows = db.execute(
        select(
            category_column.label("category"),
            func.sum(Payment.amount).label("total"),
            func.count(Payment.id).label("cnt"),
        )
        .select_from(Payment)
        .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
        .where(*conditions)
        .group_by(category_column)
        .order_by(func.sum(Payment.amount).desc())
    ).all()

    total = sum(float(row.total) for row in rows)
    categories = [
        {
            "category": row.category,
            "total": round(float(row.total), 2),
            "count": int(row.cnt),
            "share": round(float(row.total) / total * 100, 2) if total else 0.0,
        }
        for row in rows
    ]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "total": round(total, 2),
        "categories": categories,
    }


def _scheduled_payments(
    db: Session,
    user_id: int,
    currency: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Будущие списания по активным подпискам в интервале [start; end]."""
    subscriptions = db.scalars(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.active,
            Subscription.currency == currency,
        )
    ).all()

    upcoming: list[dict[str, Any]] = []
    for subscription in subscriptions:
        period_start = max(start, subscription.next_payment_date)
        for due_date in occurrences_between(
            subscription.first_payment_date, subscription.period, period_start, end
        ):
            upcoming.append(
                {
                    "subscription_id": subscription.id,
                    "name": subscription.name,
                    "category": subscription.category,
                    "amount": float(subscription.cost),
                    "currency": subscription.currency,
                    "date": due_date,
                }
            )

    upcoming.sort(key=lambda item: (item["date"], item["name"]))
    return upcoming


def forecast(
    db: Session,
    user_id: int,
    horizon_days: int = 30,
    history_days: int = 90,
    currency: str | None = None,
) -> dict[str, Any]:
    """Прогноз расходов на следующий период.

    Основной прогноз строится на истории: суммарные расходы за прошедший период
    масштабируются на длину горизонта прогноза. Если истории нет, используется
    сумма запланированных списаний по активным подпискам.
    """
    today = date.today()
    currency = currency or primary_currency(db, user_id)
    history_start = today - timedelta(days=history_days)

    history_conditions = _conditions(user_id, history_start, today, currency)
    history_total = float(
        db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(*history_conditions)) or 0
    )
    factor = horizon_days / history_days
    history_based_forecast = round(history_total * factor, 2)

    category_column = func.coalesce(Subscription.category, "Без категории")
    history_rows = db.execute(
        select(category_column.label("category"), func.sum(Payment.amount).label("total"))
        .select_from(Payment)
        .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
        .where(*history_conditions)
        .group_by(category_column)
        .order_by(func.sum(Payment.amount).desc())
    ).all()

    upcoming = _scheduled_payments(db, user_id, currency, today, today + timedelta(days=horizon_days))
    scheduled_total = round(sum(item["amount"] for item in upcoming), 2)

    if history_total > 0:
        by_category_rows = [
            {"category": row.category, "forecast": round(float(row.total) * factor, 2)}
            for row in history_rows
        ]
        forecast_total = history_based_forecast
    else:
        grouped: dict[str, float] = {}
        for item in upcoming:
            grouped[item["category"]] = grouped.get(item["category"], 0.0) + item["amount"]
        by_category_rows = [
            {"category": category, "forecast": round(amount, 2)}
            for category, amount in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)
        ]
        forecast_total = scheduled_total

    return {
        "generated_at": utcnow(),
        "period_from": today,
        "period_to": today + timedelta(days=horizon_days),
        "horizon_days": horizon_days,
        "history_days": history_days,
        "currency": currency,
        "history_total": round(history_total, 2),
        "history_based_forecast": history_based_forecast,
        "scheduled_total": scheduled_total,
        "forecast_total": round(forecast_total, 2),
        "by_category": by_category_rows,
        "upcoming": upcoming,
    }


def export_payments(
    db: Session,
    user_id: int,
    date_from: date | None,
    date_to: date | None,
    currency: str | None = None,
) -> list[Payment]:
    """Платежи для выгрузки, по возрастанию даты."""
    stmt = (
        select(Payment)
        .options(joinedload(Payment.subscription))
        .where(*_conditions(user_id, date_from, date_to, currency))
        .order_by(Payment.paid_at.asc(), Payment.id.asc())
    )
    return list(db.scalars(stmt).unique().all())
