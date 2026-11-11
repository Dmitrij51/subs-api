from __future__ import annotations

import pytest

REQUIRED_ENDPOINTS = [
    ("/api/v1/auth/register", "post"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/refresh", "post"),
    ("/api/v1/auth/logout", "post"),
    ("/api/v1/subscriptions", "get"),
    ("/api/v1/subscriptions", "post"),
    ("/api/v1/subscriptions/{id}", "get"),
    ("/api/v1/subscriptions/{id}", "patch"),
    ("/api/v1/subscriptions/{id}/pause", "post"),
    ("/api/v1/subscriptions/{id}/resume", "post"),
    ("/api/v1/subscriptions/{id}", "delete"),
    ("/api/v1/payments", "get"),
    ("/api/v1/payments", "post"),
    ("/api/v1/payments/{id}", "delete"),
    ("/api/v1/analytics/summary", "get"),
    ("/api/v1/analytics/by-category", "get"),
    ("/api/v1/analytics/forecast", "get"),
    ("/api/v1/analytics/export", "get"),
]


def test_openapi_contains_all_required_endpoints(client):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    for path, method in REQUIRED_ENDPOINTS:
        assert path in paths, f"Отсутствует путь {path}"
        assert method in paths[path], f"Отсутствует метод {method.upper()} {path}"


def test_openapi_declares_bearer_security(client):
    spec = client.get("/api/v1/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    assert any(scheme.get("scheme") == "bearer" for scheme in schemes.values())


def test_swagger_ui_available(client):
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_error_format_for_unknown_route(client):
    response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "NOT_FOUND"


def test_error_format_for_validation(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "bad", "password": "short"}
    )
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/subscriptions"),
        ("get", "/api/v1/payments"),
        ("get", "/api/v1/analytics/summary"),
        ("get", "/api/v1/analytics/by-category"),
        ("get", "/api/v1/analytics/forecast"),
        ("get", "/api/v1/analytics/export"),
    ],
)
def test_all_read_endpoints_require_auth(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
