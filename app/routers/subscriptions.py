from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..errors import bad_request, conflict
from ..models import Subscription, SubscriptionStatus, User, utcnow
from ..schemas import (
    SubscriptionCreate,
    SubscriptionDetail,
    SubscriptionRead,
    SubscriptionUpdate,
)
from ..services.periods import occurrence_on_or_after
from ..services.subscriptions import load_subscription

router = APIRouter(prefix="/subscriptions", tags=["Подписки"])


@router.get(
    "",
    response_model=list[SubscriptionRead],
    summary="Список подписок текущего пользователя",
)
def list_subscriptions(
    category: str | None = Query(default=None, description="Фильтр по категории"),
    status_filter: SubscriptionStatus | None = Query(
        default=None, alias="status", description="Фильтр по статусу"
    ),
    sort: Literal["next_payment_date", "cost"] = Query(
        default="next_payment_date", description="Поле сортировки"
    ),
    order: Literal["asc", "desc"] = Query(
        default="asc", description="Направление сортировки"
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Subscription]:
    stmt = select(Subscription).where(Subscription.user_id == user.id)
    if category:
        stmt = stmt.where(Subscription.category == category)
    if status_filter is not None:
        stmt = stmt.where(Subscription.status == status_filter)

    column = Subscription.cost if sort == "cost" else Subscription.next_payment_date
    stmt = stmt.order_by(
        column.desc() if order == "desc" else column.asc(), Subscription.id.asc()
    )
    return list(db.scalars(stmt).all())


@router.post(
    "",
    response_model=SubscriptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание подписки",
)
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription:
    subscription = Subscription(
        user_id=user.id,
        name=payload.name.strip(),
        category=payload.category.strip(),
        cost=payload.cost,
        currency=payload.currency,
        period=payload.period,
        first_payment_date=payload.first_payment_date,
        status=SubscriptionStatus(payload.status),
        notify_days_before=payload.notify_days_before,
    )
    subscription.next_payment_date = occurrence_on_or_after(
        subscription.first_payment_date, subscription.period, date.today()
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@router.get(
    "/{id}",
    response_model=SubscriptionDetail,
    summary="Подписка с историей платежей",
)
def get_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription:
    return load_subscription(db, user.id, id, with_payments=True)


@router.patch(
    "/{id}",
    response_model=SubscriptionRead,
    summary="Изменение параметров подписки",
)
def update_subscription(
    id: int,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription:
    subscription = load_subscription(db, user.id, id)
    if subscription.status is SubscriptionStatus.canceled:
        raise bad_request("Отмененную подписку нельзя изменить")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise bad_request("Не передано ни одного параметра для изменения")

    date_changed = "first_payment_date" in changes or "period" in changes

    for field, value in changes.items():
        if field == "status":
            subscription.status = SubscriptionStatus(value)
        elif field in {"name", "category"}:
            setattr(subscription, field, str(value).strip())
        else:
            setattr(subscription, field, value)

    if date_changed or (
        subscription.status is SubscriptionStatus.active
        and subscription.next_payment_date < date.today()
    ):
        subscription.next_payment_date = occurrence_on_or_after(
            subscription.first_payment_date, subscription.period, date.today()
        )

    subscription.updated_at = utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


@router.post(
    "/{id}/pause",
    response_model=SubscriptionRead,
    summary="Приостановка подписки",
)
def pause_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription:
    subscription = load_subscription(db, user.id, id)
    if subscription.status is SubscriptionStatus.canceled:
        raise bad_request("Нельзя приостановить отмененную подписку")
    if subscription.status is SubscriptionStatus.paused:
        raise conflict("Подписка уже приостановлена")

    subscription.status = SubscriptionStatus.paused
    subscription.updated_at = utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


@router.post(
    "/{id}/resume",
    response_model=SubscriptionRead,
    summary="Возобновление подписки",
)
def resume_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subscription:
    subscription = load_subscription(db, user.id, id)
    if subscription.status is SubscriptionStatus.canceled:
        raise bad_request("Отмененную подписку нельзя возобновить")
    if subscription.status is SubscriptionStatus.active:
        raise conflict("Подписка уже активна")

    subscription.status = SubscriptionStatus.active
    subscription.next_payment_date = occurrence_on_or_after(
        subscription.first_payment_date, subscription.period, date.today()
    )
    subscription.updated_at = utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Отмена подписки (данные сохраняются)",
)
def cancel_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    subscription = load_subscription(db, user.id, id)
    if subscription.status is not SubscriptionStatus.canceled:
        subscription.status = SubscriptionStatus.canceled
        subscription.canceled_at = utcnow()
        subscription.updated_at = utcnow()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
