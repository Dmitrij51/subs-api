from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..errors import bad_request
from ..models import PaymentSource, User, utcnow
from ..schemas import (
    ByCategoryResponse,
    ForecastResponse,
    SummaryResponse,
)
from ..services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["Аналитика"])


def _check_period(date_from: date | None, date_to: date | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise bad_request("Дата начала периода не может быть позже даты окончания")


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="Суммарные, средние, минимальные и максимальные расходы",
)
def get_summary(
    date_from: date | None = Query(
        default=None, description="Начало периода (включительно)"
    ),
    date_to: date | None = Query(
        default=None, description="Конец периода (включительно)"
    ),
    currency: str | None = Query(
        default=None, description="Фильтр по валюте (ISO 4217)"
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryResponse:
    _check_period(date_from, date_to)
    data = analytics_service.summary(db, user.id, date_from, date_to, currency)
    return SummaryResponse(**data)


@router.get(
    "/by-category",
    response_model=ByCategoryResponse,
    summary="Распределение расходов по категориям",
)
def get_by_category(
    date_from: date | None = Query(
        default=None, description="Начало периода (включительно)"
    ),
    date_to: date | None = Query(
        default=None, description="Конец периода (включительно)"
    ),
    currency: str | None = Query(
        default=None, description="Фильтр по валюте (ISO 4217)"
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ByCategoryResponse:
    _check_period(date_from, date_to)
    data = analytics_service.by_category(db, user.id, date_from, date_to, currency)
    return ByCategoryResponse(**data)


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    summary="Прогноз расходов на следующий период",
)
def get_forecast(
    horizon_days: int = Query(
        default=30, ge=1, le=365, description="Горизонт прогноза в днях"
    ),
    history_days: int = Query(
        default=90, ge=7, le=730, description="Глубина истории в днях"
    ),
    currency: str | None = Query(default=None, description="Валюта прогноза"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ForecastResponse:
    data = analytics_service.forecast(db, user.id, horizon_days, history_days, currency)
    return ForecastResponse(**data)


@router.get(
    "/export",
    summary="Выгрузка отчета (format=csv|json)",
    response_class=Response,
    responses={
        200: {
            "description": "Файл отчета",
            "content": {
                "text/csv": {},
                "application/json": {},
            },
        }
    },
)
def export_report(
    format: str = Query(
        default="csv", pattern="^(csv|json)$", description="csv или json"
    ),
    date_from: date | None = Query(
        default=None, description="Начало периода (включительно)"
    ),
    date_to: date | None = Query(
        default=None, description="Конец периода (включительно)"
    ),
    currency: str | None = Query(
        default=None, description="Фильтр по валюте (ISO 4217)"
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _check_period(date_from, date_to)
    payments = analytics_service.export_payments(
        db, user.id, date_from, date_to, currency
    )

    if format == "json":
        payload = {
            "generated_at": utcnow().isoformat(timespec="seconds") + "Z",
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "total": len(payments),
            "total_amount": round(
                sum(float(payment.amount) for payment in payments), 2
            ),
            "items": [
                {
                    "id": payment.id,
                    "subscription_id": payment.subscription_id,
                    "subscription_name": payment.subscription_name,
                    "category": payment.category,
                    "amount": float(payment.amount),
                    "currency": payment.currency,
                    "paid_at": payment.paid_at.isoformat(timespec="seconds") + "Z",
                    "source": payment.source.value,
                    "note": payment.note,
                }
                for payment in payments
            ],
        }
        return JSONResponse(content=payload)

    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM, чтобы Excel корректно открывал UTF-8
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "ID",
            "Подписка",
            "Категория",
            "Сумма",
            "Валюта",
            "Дата платежа",
            "Источник",
            "Примечание",
        ]
    )
    for payment in payments:
        writer.writerow(
            [
                payment.id,
                payment.subscription_name or "",
                payment.category or "",
                f"{payment.amount:.2f}",
                payment.currency,
                payment.paid_at.strftime("%Y-%m-%d %H:%M"),
                "автоматически" if payment.source is PaymentSource.auto else "вручную",
                payment.note or "",
            ]
        )

    filename = f"payments_report_{(date_to or date.today()):%Y%m%d}.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
