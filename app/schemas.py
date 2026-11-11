from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
)

from .config import settings
from .constants import ISO_4217
from .models import NotificationKind, PaymentSource, Period, SubscriptionStatus


# --------------------------------------------------------------------------- #
# Общие типы
# --------------------------------------------------------------------------- #
def _validate_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Пароль должен содержать не менее 8 символов")
    if len(value) > 128:
        raise ValueError("Пароль должен содержать не более 128 символов")
    if not re.search(r"[^\W\d_]", value, flags=re.UNICODE):
        raise ValueError("Пароль должен содержать хотя бы одну букву")
    if not re.search(r"\d", value):
        raise ValueError("Пароль должен содержать хотя бы одну цифру")
    return value


Password = Annotated[str, Field(max_length=128, examples=["Password123"]), AfterValidator(_validate_password)]


def _validate_currency(value: str) -> str:
    code = value.strip().upper()
    if code not in ISO_4217:
        raise ValueError(f"Неизвестный код валюты ISO 4217: {value}")
    return code


CurrencyCode = Annotated[
    str,
    Field(min_length=3, max_length=3, description="Код валюты ISO 4217", examples=["RUB"]),
    AfterValidator(_validate_currency),
]

Money = Annotated[
    Decimal,
    Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Положительная сумма, не более 2 знаков после запятой",
        examples=[599.00],
    ),
    PlainSerializer(lambda value: float(value), return_type=float, when_used="json"),
]


def _normalize_datetime(value: object) -> object:
    """Принимает дату без времени и приводит время к наивному UTC."""
    if isinstance(value, str) and len(value.strip()) == 10:
        value = datetime.fromisoformat(value.strip())
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return value


PaidAt = Annotated[datetime, BeforeValidator(_normalize_datetime)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Аутентификация
# --------------------------------------------------------------------------- #
class UserRead(ORMModel):
    id: int
    email: EmailStr
    created_at: datetime


class RegisterRequest(BaseModel):
    email: EmailStr = Field(examples=["user@example.com"])
    password: Password


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["user@example.com"])
    password: str = Field(min_length=1, max_length=128, examples=["Password123"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Время жизни access-токена в секундах")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, description="Одноразовый токен из письма")
    new_password: Password


class MessageResponse(BaseModel):
    message: str


# --------------------------------------------------------------------------- #
# Подписки
# --------------------------------------------------------------------------- #
class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Netflix"])
    category: str = Field(min_length=1, max_length=80, examples=["Развлечения"])
    cost: Money
    currency: CurrencyCode = "RUB"
    period: Period = Period.month
    first_payment_date: date = Field(examples=["2025-03-01"])
    status: Literal["active", "paused"] = "active"
    notify_days_before: int = Field(
        default_factory=lambda: settings.default_notify_days_before,
        ge=0,
        le=90,
        description="За сколько дней уведомлять о списании (0 - не уведомлять)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Netflix",
                "category": "Развлечения",
                "cost": 599.00,
                "currency": "RUB",
                "period": "month",
                "first_payment_date": "2025-03-01",
            }
        }
    )


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    cost: Money | None = None
    currency: CurrencyCode | None = None
    period: Period | None = None
    first_payment_date: date | None = None
    status: Literal["active", "paused"] | None = None
    notify_days_before: int | None = Field(default=None, ge=0, le=90)


class SubscriptionRead(ORMModel):
    id: int
    name: str
    category: str
    cost: Money
    currency: str
    period: Period
    first_payment_date: date
    next_payment_date: date
    status: SubscriptionStatus
    notify_days_before: int
    created_at: datetime
    updated_at: datetime
    canceled_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Платежи
# --------------------------------------------------------------------------- #
class PaymentCreate(BaseModel):
    subscription_id: int | None = Field(
        default=None, description="Подписка, к которой относится платеж (необязательно)"
    )
    amount: Money
    currency: CurrencyCode | None = Field(
        default=None, description="Валюта; по умолчанию валюта подписки или RUB"
    )
    paid_at: PaidAt | None = Field(
        default=None, description="Дата и время платежа (UTC); по умолчанию текущий момент"
    )
    note: str | None = Field(default=None, max_length=255)


class PaymentRead(ORMModel):
    id: int
    subscription_id: int | None
    subscription_name: str | None = None
    category: str | None = None
    amount: Money
    currency: str
    paid_at: datetime
    source: PaymentSource
    note: str | None = None
    created_at: datetime


class PaymentPage(BaseModel):
    items: list[PaymentRead]
    total: int
    page: int
    per_page: int
    pages: int


class SubscriptionDetail(SubscriptionRead):
    payments: list[PaymentRead] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Уведомления
# --------------------------------------------------------------------------- #
class NotificationRead(ORMModel):
    id: int
    subscription_id: int | None
    kind: NotificationKind
    due_date: date
    message: str
    is_read: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Аналитика
# --------------------------------------------------------------------------- #
class CurrencyTotal(BaseModel):
    currency: str
    total: float
    count: int


class SummaryResponse(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    payments_count: int
    total: float
    average: float
    min: float
    max: float
    by_currency: list[CurrencyTotal] = Field(default_factory=list)


class CategoryTotal(BaseModel):
    category: str
    total: float
    count: int
    share: float = Field(description="Доля категории в общих расходах, %")


class ByCategoryResponse(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    total: float
    categories: list[CategoryTotal] = Field(default_factory=list)


class ForecastCategory(BaseModel):
    category: str
    forecast: float


class UpcomingPayment(BaseModel):
    subscription_id: int
    name: str
    category: str
    amount: float
    currency: str
    date: date


class ForecastResponse(BaseModel):
    generated_at: datetime
    period_from: date
    period_to: date
    horizon_days: int
    history_days: int
    currency: str
    history_total: float
    history_based_forecast: float
    scheduled_total: float
    forecast_total: float
    by_category: list[ForecastCategory] = Field(default_factory=list)
    upcoming: list[UpcomingPayment] = Field(default_factory=list)
