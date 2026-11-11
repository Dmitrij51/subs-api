from __future__ import annotations

import math
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user
from ..errors import bad_request, forbidden, not_found
from ..models import Payment, PaymentSource, User, utcnow
from ..schemas import PaymentCreate, PaymentPage, PaymentRead
from ..services.subscriptions import load_subscription

router = APIRouter(prefix="/payments", tags=["Платежи"])


@router.get("", response_model=PaymentPage, summary="История платежей")
def list_payments(
    page: int = Query(default=1, ge=1, description="Номер страницы"),
    per_page: int = Query(
        default=20, ge=1, le=100, description="Записей на странице (максимум 100)"
    ),
    date_from: date | None = Query(
        default=None, description="Начало периода (включительно)"
    ),
    date_to: date | None = Query(
        default=None, description="Конец периода (включительно)"
    ),
    subscription_id: int | None = Query(default=None, description="Фильтр по подписке"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaymentPage:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise bad_request("Дата начала периода не может быть позже даты окончания")

    conditions = [Payment.user_id == user.id]
    if date_from is not None:
        conditions.append(Payment.paid_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(Payment.paid_at <= datetime.combine(date_to, time.max))
    if subscription_id is not None:
        conditions.append(Payment.subscription_id == subscription_id)

    total = int(db.scalar(select(func.count(Payment.id)).where(*conditions)) or 0)
    stmt = (
        select(Payment)
        .options(selectinload(Payment.subscription))
        .where(*conditions)
        .order_by(Payment.paid_at.desc(), Payment.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = list(db.scalars(stmt).all())

    return PaymentPage(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total else 0,
    )


@router.post(
    "",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ручное добавление платежа",
)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Payment:
    subscription = None
    if payload.subscription_id is not None:
        subscription = load_subscription(db, user.id, payload.subscription_id)

    currency = payload.currency
    if subscription is not None and "currency" not in payload.model_fields_set:
        currency = subscription.currency
    if currency is None:
        currency = "RUB"

    payment = Payment(
        user_id=user.id,
        subscription_id=subscription.id if subscription is not None else None,
        amount=payload.amount,
        currency=currency,
        paid_at=payload.paid_at or utcnow(),
        source=PaymentSource.manual,
        note=payload.note,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Удаление платежа",
)
def delete_payment(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    payment = db.get(Payment, id)
    if payment is None:
        raise not_found("Платеж не найден")
    if payment.user_id != user.id:
        raise forbidden("Доступ к платежу другого пользователя запрещен")

    db.delete(payment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
