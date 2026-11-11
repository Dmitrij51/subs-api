from __future__ import annotations

from datetime import date, timedelta


def test_create_subscription_returns_201_and_next_payment_date(client, auth_headers):
    first_payment = date.today() + timedelta(days=5)
    payload = {
        "name": "Netflix",
        "category": "Развлечения",
        "cost": 599.00,
        "currency": "RUB",
        "period": "month",
        "first_payment_date": first_payment.isoformat(),
    }
    response = client.post("/api/v1/subscriptions", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] > 0
    assert data["name"] == "Netflix"
    assert data["cost"] == 599.0
    assert data["currency"] == "RUB"
    assert data["status"] == "active"
    assert data["next_payment_date"] == first_payment.isoformat()


def test_create_subscription_with_past_first_payment_schedules_future_date(
    client, auth_headers
):
    payload = {
        "name": "Old",
        "category": "Развлечения",
        "cost": 100,
        "currency": "RUB",
        "period": "month",
        "first_payment_date": (date.today() - timedelta(days=400)).isoformat(),
    }
    response = client.post("/api/v1/subscriptions", json=payload, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["next_payment_date"] >= date.today().isoformat()


def test_create_subscription_validation_errors(client, auth_headers):
    response = client.post(
        "/api/v1/subscriptions",
        json={
            "name": "Bad",
            "category": "Развлечения",
            "cost": -10,
            "currency": "RUB",
            "period": "month",
            "first_payment_date": date.today().isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "cost" in body["message"]

    response = client.post(
        "/api/v1/subscriptions",
        json={
            "name": "Bad",
            "category": "Развлечения",
            "cost": 10,
            "currency": "ABC",
            "period": "month",
            "first_payment_date": date.today().isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "ISO 4217" in response.json()["message"]

    response = client.post(
        "/api/v1/subscriptions",
        json={
            "name": "Bad",
            "category": "Развлечения",
            "cost": 10,
            "currency": "RUB",
            "period": "week",
            "first_payment_date": date.today().isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_list_filters_and_sorting(client, auth_headers, make_subscription):
    make_subscription(name="A", category="Музыка", cost=300)
    make_subscription(name="B", category="Музыка", cost=100)
    make_subscription(name="C", category="Кино", cost=200)

    response = client.get("/api/v1/subscriptions", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 3

    response = client.get("/api/v1/subscriptions?category=Музыка", headers=auth_headers)
    assert [item["name"] for item in response.json()] == ["A", "B"]

    response = client.get(
        "/api/v1/subscriptions?sort=cost&order=desc", headers=auth_headers
    )
    assert [item["cost"] for item in response.json()] == [300.0, 200.0, 100.0]

    response = client.get(
        "/api/v1/subscriptions?sort=cost&order=asc", headers=auth_headers
    )
    assert [item["cost"] for item in response.json()] == [100.0, 200.0, 300.0]

    response = client.get("/api/v1/subscriptions?sort=invalid", headers=auth_headers)
    assert response.status_code == 422

    response = client.get("/api/v1/subscriptions?status=paused", headers=auth_headers)
    assert response.json() == []


def test_get_subscription_with_payment_history(client, auth_headers, make_subscription):
    subscription = make_subscription()
    payment = client.post(
        "/api/v1/payments",
        json={"subscription_id": subscription["id"], "amount": 599},
        headers=auth_headers,
    )
    assert payment.status_code == 201

    response = client.get(f"/api/v1/subscriptions/{subscription['id']}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == subscription["id"]
    assert len(data["payments"]) == 1
    assert data["payments"][0]["amount"] == 599.0
    assert data["payments"][0]["subscription_name"] == "Netflix"


def test_patch_subscription(client, auth_headers, make_subscription):
    subscription = make_subscription()

    response = client.patch(
        f"/api/v1/subscriptions/{subscription['id']}",
        json={"name": "Netflix Premium", "cost": 999.5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Netflix Premium"
    assert data["cost"] == 999.5

    response = client.patch(
        f"/api/v1/subscriptions/{subscription['id']}", json={}, headers=auth_headers
    )
    assert response.status_code == 400


def test_pause_resume_and_conflicts(client, auth_headers, make_subscription):
    subscription = make_subscription()
    url = f"/api/v1/subscriptions/{subscription['id']}"

    response = client.post(f"{url}/pause", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "paused"

    response = client.post(f"{url}/pause", headers=auth_headers)
    assert response.status_code == 409

    response = client.post(f"{url}/resume", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["next_payment_date"] >= date.today().isoformat()

    response = client.post(f"{url}/resume", headers=auth_headers)
    assert response.status_code == 409


def test_cancel_subscription_keeps_data(client, auth_headers, make_subscription):
    subscription = make_subscription()
    url = f"/api/v1/subscriptions/{subscription['id']}"

    client.post(
        "/api/v1/payments",
        json={"subscription_id": subscription["id"], "amount": 599},
        headers=auth_headers,
    )

    response = client.delete(url, headers=auth_headers)
    assert response.status_code == 204

    response = client.get(url, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "canceled"
    assert data["canceled_at"] is not None
    assert len(data["payments"]) == 1

    # отмененную подписку нельзя приостановить
    response = client.post(f"{url}/pause", headers=auth_headers)
    assert response.status_code == 400


def test_subscription_of_another_user_is_forbidden(client, user_factory):
    first = user_factory(email="first@example.com")
    second = user_factory(email="second@example.com")

    created = client.post(
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

    response = client.get(f"/api/v1/subscriptions/{created['id']}", headers=second["headers"])
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    response = client.patch(
        f"/api/v1/subscriptions/{created['id']}",
        json={"name": "Hack"},
        headers=second["headers"],
    )
    assert response.status_code == 403

    response = client.delete(f"/api/v1/subscriptions/{created['id']}", headers=second["headers"])
    assert response.status_code == 403


def test_subscription_not_found(client, auth_headers):
    response = client.get("/api/v1/subscriptions/9999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
