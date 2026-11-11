"""Планировщик: автоматические платежи и напоминания о списаниях."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..emailer import send_payment_reminder_email
from ..models import (
    Notification,
    NotificationKind,
    Payment,
    PaymentSource,
    Subscription,
    SubscriptionStatus,
    User,
)
from .periods import next_occurrence_after

logger = logging.getLogger(__name__)

# Защита от бесконечного цикла, если в данных окажется некорректная дата
MAX_CATCHUP_PAYMENTS = 240


def process_due_payments(db: Session, today: date | None = None) -> list[Payment]:
    """Регистрирует платежи по активным подпискам, у которых наступила дата списания.

    Если подписка «просрочена» на несколько периодов, создается платеж за каждый
    пропущенный период, а дата следующего платежа сдвигается вперед.
    """
    today = today or date.today()
    subscriptions = db.scalars(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.active,
            Subscription.next_payment_date <= today,
        )
    ).all()

    created: list[Payment] = []
    for subscription in subscriptions:
        guard = 0
        while subscription.next_payment_date <= today and guard < MAX_CATCHUP_PAYMENTS:
            due_date = subscription.next_payment_date
            payment = Payment(
                user_id=subscription.user_id,
                subscription_id=subscription.id,
                amount=subscription.cost,
                currency=subscription.currency,
                paid_at=datetime.combine(due_date, time.min),
                source=PaymentSource.auto,
                note="Автоматическое списание по расписанию",
            )
            db.add(payment)
            created.append(payment)
            subscription.next_payment_date = next_occurrence_after(
                subscription.first_payment_date, subscription.period, due_date
            )
            guard += 1

    if created:
        db.commit()
        logger.info("Автоматически зарегистрировано платежей: %s", len(created))
    return created


def process_upcoming_notifications(db: Session, today: date | None = None) -> list[Notification]:
    """Создает уведомления о списаниях, до которых осталось заданное число дней."""
    today = today or date.today()
    subscriptions = db.scalars(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.active,
            Subscription.notify_days_before > 0,
        )
    ).all()

    created: list[Notification] = []
    for subscription in subscriptions:
        notify_date = subscription.next_payment_date - timedelta(days=subscription.notify_days_before)
        if notify_date != today:
            continue

        exists = db.scalar(
            select(Notification.id).where(
                Notification.subscription_id == subscription.id,
                Notification.kind == NotificationKind.upcoming_payment,
                Notification.due_date == subscription.next_payment_date,
            )
        )
        if exists is not None:
            continue

        message = (
            f"Списание {subscription.cost:.2f} {subscription.currency} по подписке "
            f"«{subscription.name}» запланировано на {subscription.next_payment_date:%d.%m.%Y}"
        )
        notification = Notification(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            kind=NotificationKind.upcoming_payment,
            due_date=subscription.next_payment_date,
            message=message,
        )
        db.add(notification)
        created.append(notification)

    if created:
        db.commit()
        for notification in created:
            subscription = db.get(Subscription, notification.subscription_id)
            user = db.get(User, notification.user_id)
            if subscription is None or user is None:
                continue
            send_payment_reminder_email(
                to=user.email,
                subscription_name=subscription.name,
                amount=f"{subscription.cost:.2f}",
                currency=subscription.currency,
                due_date=subscription.next_payment_date.strftime("%d.%m.%Y"),
                days_left=subscription.notify_days_before,
            )
        logger.info("Создано уведомлений о списаниях: %s", len(created))
    return created
