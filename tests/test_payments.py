from __future__ import annotations

from datetime import date, timedelta


def test_create_payment_inherits_subscription_currency(
    client, auth_headers, make_subscription
):
    subscription = make_subscription(currency="USD", cost=10)

    response = client.post(
        "/api/v1/payments",
        json={"subscription_id": subscription["id"], "amount": 10.5},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["currency"] == "USD"
    assert data["source"] == "manual"
    assert data["subscription_name"] == "Netflix"
    assert data["category"] == "Развлечения"


def test_create_payment_without_subscription(client, auth_headers):
    response = client.post(
        "/api/v1/payments",
        json={
            "amount": 150,
            "paid_at": (date.today() - timedelta(days=1)).isoformat(),
            "note": "Разовая покупка",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["subscription_id"] is None
    assert data["currency"] == "RUB"
    assert data["note"] == "Разовая покупка"


def test_create_payment_validation(client, auth_headers):
    response = client.post("/api/v1/payments", json={"amount": 0}, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"

    response = client.post(
        "/api/v1/payments", json={"amount": 100, "currency": "ABC"}, headers=auth_headers
    )
    assert response.status_code == 422


def test_pagination_and_filters(client, auth_headers, make_subscription):
    subscription = make_subscription()
    today = date.today()

    for offset in range(3):
        response = client.post(
            "/api/v1/payments",
            json={
                "subscription_id": subscription["id"],
                "amount": 100 + offset,
                "paid_at": (today - timedelta(days=offset)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

    response = client.get("/api/v1/payments?page=1&per_page=2", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    response = client.get("/api/v1/payments?page=2&per_page=2", headers=auth_headers)
    assert len(response.json()["items"]) == 1

    response = client.get("/api/v1/payments?per_page=101", headers=auth_headers)
    assert response.status_code == 422

    response = client.get(
        f"/api/v1/payments?date_from={today.isoformat()}&date_to={today.isoformat()}",
        headers=auth_headers,
    )
    assert response.json()["total"] == 1

    response = client.get(
        f"/api/v1/payments?date_from={today.isoformat()}&date_to={(today - timedelta(days=5)).isoformat()}",
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_delete_payment(client, auth_headers, make_subscription):
    subscription = make_subscription()
    payment = client.post(
        "/api/v1/payments",
        json={"subscription_id": subscription["id"], "amount": 100},
        headers=auth_headers,
    ).json()

    response = client.delete(f"/api/v1/payments/{payment['id']}", headers=auth_headers)
    assert response.status_code == 204

    response = client.get("/api/v1/payments", headers=auth_headers)
    assert response.json()["total"] == 0

    response = client.delete(f"/api/v1/payments/{payment['id']}", headers=auth_headers)
    assert response.status_code == 404


def test_payment_of_another_user_is_forbidden(client, user_factory):
    first = user_factory(email="pfirst@example.com")
    second = user_factory(email="psecond@example.com")

    payment = client.post(
        "/api/v1/payments", json={"amount": 100}, headers=first["headers"]
    ).json()

    response = client.delete(f"/api/v1/payments/{payment['id']}", headers=second["headers"])
    assert response.status_code == 403

    response = client.get("/api/v1/payments", headers=second["headers"])
    assert response.json()["total"] == 0


def test_payment_for_foreign_subscription_is_forbidden(client, user_factory):
    first = user_factory(email="sfirst@example.com")
    second = user_factory(email="ssecond@example.com")

    subscription = client.post(
        "/api/v1/subscriptions",
        json={
            "name": "Secret",
            "category": "Развлечения",
            "cost": 10,
            "currency": "RUB",
            "period": "month",
            "first_payment_date": date.today().isoformat(),
        },
        headers=first["headers"],
    ).json()

    response = client.post(
        "/api/v1/payments",
        json={"subscription_id": subscription["id"], "amount": 10},
        headers=second["headers"],
    )
    assert response.status_code == 403
