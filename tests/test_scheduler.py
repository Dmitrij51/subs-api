from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.database import SessionLocal
from app.models import (
    Notification,
    Payment,
    Period,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.security import hash_password
from app.services.billing import process_due_payments, process_upcoming_notifications


def _create_subscription(
    *,
    status: SubscriptionStatus = SubscriptionStatus.active,
    period: Period = Period.month,
    first_payment_date: date | None = None,
    next_payment_date: date | None = None,
    notify_days_before: int = 3,
    cost: str = "100.00",
) -> int:
    today = date.today()
    with SessionLocal() as db:
        user = User(email=f"user{date.today().toordinal()}@example.com", password_hash=hash_password("Password123"))
        db.add(user)
        db.flush()

        subscription = Subscription(
            user_id=user.id,
            name="Test subscription",
            category="Тест",
            cost=Decimal(cost),
            currency="RUB",
            period=period,
            first_payment_date=first_payment_date or today,
            next_payment_date=next_payment_date or today,
            status=status,
            notify_days_before=notify_days_before,
        )
        db.add(subscription)
        db.commit()
        return subscription.id


def test_due_payments_are_registered_and_date_advances():
    today = date.today()
    first_payment = today - relativedelta(months=2)
    subscription_id = _create_subscription(
        first_payment_date=first_payment, next_payment_date=first_payment
    )

    with SessionLocal() as db:
        created = process_due_payments(db, today)
        assert len(created) == 3
        assert sum(payment.amount for payment in created) == Decimal("300.00")

    with SessionLocal() as db:
        subscription = db.get(Subscription, subscription_id)
        assert subscription is not None
        assert subscription.next_payment_date > today

        payments = db.query(Payment).filter(Payment.subscription_id == subscription_id).all()
        assert len(payments) == 3
        assert all(payment.source.value == "auto" for payment in payments)
        assert {payment.paid_at.date() for payment in payments} == {
            first_payment,
            first_payment + relativedelta(months=1),
            first_payment + relativedelta(months=2),
        }


def test_paused_subscription_is_not_charged():
    subscription_id = _create_subscription(status=SubscriptionStatus.paused)

    with SessionLocal() as db:
        created = process_due_payments(db, date.today())
        assert created == []

    with SessionLocal() as db:
        assert db.query(Payment).filter(Payment.subscription_id == subscription_id).count() == 0


def test_notification_created_once():
    today = date.today()
    subscription_id = _create_subscription(
        next_payment_date=today + timedelta(days=3), notify_days_before=3
    )

    with SessionLocal() as db:
        created = process_upcoming_notifications(db, today)
        assert len(created) == 1
        assert "Test subscription" in created[0].message

    with SessionLocal() as db:
        again = process_upcoming_notifications(db, today)
        assert again == []
        assert db.query(Notification).filter(Notification.subscription_id == subscription_id).count() == 1


def test_notification_not_created_before_time():
    today = date.today()
    _create_subscription(next_payment_date=today + timedelta(days=10), notify_days_before=3)

    with SessionLocal() as db:
        assert process_upcoming_notifications(db, today) == []


def test_notifications_endpoint(client, user_factory, auth_headers):
    today = date.today()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "user@example.com").one()
        subscription = Subscription(
            user_id=user.id,
            name="Notify me",
            category="Тест",
            cost=Decimal("50.00"),
            currency="RUB",
            period=Period.month,
            first_payment_date=today,
            next_payment_date=today + timedelta(days=3),
            status=SubscriptionStatus.active,
            notify_days_before=3,
        )
        db.add(subscription)
        db.commit()
        process_upcoming_notifications(db, today)

    response = client.get("/api/v1/notifications", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["is_read"] is False

    response = client.post(f"/api/v1/notifications/{items[0]['id']}/read", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["is_read"] is True
