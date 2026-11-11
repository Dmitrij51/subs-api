from __future__ import annotations

import json
from datetime import date, timedelta


def _add_payment(client, headers, amount, paid_at, subscription_id=None):
    payload = {"amount": amount, "paid_at": paid_at}
    if subscription_id is not None:
        payload["subscription_id"] = subscription_id
    response = client.post("/api/v1/payments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_summary(client, auth_headers, make_subscription):
    subscription = make_subscription(cost=300)
    today = date.today()
    _add_payment(client, auth_headers, 300, (today - timedelta(days=1)).isoformat(), subscription["id"])
    _add_payment(client, auth_headers, 100, (today - timedelta(days=2)).isoformat(), subscription["id"])
    _add_payment(client, auth_headers, 200, (today - timedelta(days=3)).isoformat())

    response = client.get(
        f"/api/v1/analytics/summary?date_from={(today - timedelta(days=10)).isoformat()}"
        f"&date_to={today.isoformat()}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["payments_count"] == 3
    assert data["total"] == 600.0
    assert data["average"] == 200.0
    assert data["min"] == 100.0
    assert data["max"] == 300.0
    assert data["by_currency"] == [{"currency": "RUB", "total": 600.0, "count": 3}]


def test_summary_empty_period(client, auth_headers):
    response = client.get("/api/v1/analytics/summary", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["payments_count"] == 0
    assert data["total"] == 0.0
    assert data["average"] == 0.0


def test_summary_invalid_period(client, auth_headers):
    response = client.get(
        "/api/v1/analytics/summary?date_from=2026-05-01&date_to=2026-01-01",
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_by_category(client, auth_headers, make_subscription):
    music = make_subscription(name="Spotify", category="Музыка", cost=200)
    movies = make_subscription(name="Netflix", category="Кино", cost=600)
    today = date.today()

    _add_payment(client, auth_headers, 200, today.isoformat(), music["id"])
    _add_payment(client, auth_headers, 600, today.isoformat(), movies["id"])
    _add_payment(client, auth_headers, 200, today.isoformat())

    response = client.get("/api/v1/analytics/by-category", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1000.0

    categories = {item["category"]: item for item in data["categories"]}
    assert categories["Музыка"]["total"] == 200.0
    assert categories["Кино"]["total"] == 600.0
    assert categories["Без категории"]["total"] == 200.0
    assert categories["Кино"]["share"] == 60.0
    assert round(sum(item["share"] for item in data["categories"]), 2) == 100.0


def test_forecast(client, auth_headers, make_subscription):
    subscription = make_subscription(cost=300)
    today = date.today()
    _add_payment(
        client, auth_headers, 900, (today - timedelta(days=30)).isoformat(), subscription["id"]
    )

    response = client.get(
        "/api/v1/analytics/forecast?horizon_days=30&history_days=90", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "RUB"
    assert data["history_total"] == 900.0
    assert data["history_based_forecast"] == 300.0
    assert data["forecast_total"] == 300.0
    assert data["scheduled_total"] == 300.0
    assert len(data["upcoming"]) == 1
    assert data["upcoming"][0]["name"] == "Netflix"
    assert data["period_from"] == today.isoformat()


def test_forecast_without_history_uses_schedule(client, auth_headers, make_subscription):
    make_subscription(cost=250)

    response = client.get("/api/v1/analytics/forecast", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["history_total"] == 0.0
    assert data["forecast_total"] == 250.0
    assert data["by_category"][0]["category"] == "Развлечения"


def test_export_csv(client, auth_headers, make_subscription):
    subscription = make_subscription()
    _add_payment(client, auth_headers, 599, date.today().isoformat(), subscription["id"])

    response = client.get("/api/v1/analytics/export?format=csv", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    assert "Netflix" in text
    assert "599.00" in text


def test_export_json(client, auth_headers, make_subscription):
    subscription = make_subscription()
    _add_payment(client, auth_headers, 599, date.today().isoformat(), subscription["id"])

    response = client.get("/api/v1/analytics/export?format=json", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["total_amount"] == 599.0
    assert data["items"][0]["subscription_name"] == "Netflix"


def test_export_invalid_format(client, auth_headers):
    response = client.get("/api/v1/analytics/export?format=xml", headers=auth_headers)
    assert response.status_code == 422


def test_analytics_only_current_user_data(client, user_factory):
    first = user_factory(email="afirst@example.com")
    second = user_factory(email="asecond@example.com")

    client.post("/api/v1/payments", json={"amount": 500}, headers=first["headers"])

    response = client.get("/api/v1/analytics/summary", headers=second["headers"])
    assert response.json()["total"] == 0.0

    response = client.get("/api/v1/analytics/export?format=json", headers=second["headers"])
    assert response.json()["total"] == 0
    assert json.dumps(response.json())  # тело всегда валидный JSON
