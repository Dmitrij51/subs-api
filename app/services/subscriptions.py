"""Сервисные функции для подписок."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..errors import forbidden, not_found
from ..models import Subscription


def load_subscription(
    db: Session,
    user_id: int,
    subscription_id: int,
    *,
    with_payments: bool = False,
) -> Subscription:
    """Загружает подписку и проверяет права владельца."""
    stmt = select(Subscription).where(Subscription.id == subscription_id)
    if with_payments:
        stmt = stmt.options(selectinload(Subscription.payments))

    subscription = db.scalar(stmt)
    if subscription is None:
        raise not_found("Подписка не найдена")
    if subscription.user_id != user_id:
        raise forbidden("Доступ к подписке другого пользователя запрещен")
    return subscription
