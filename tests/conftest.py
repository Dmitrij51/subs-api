from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent
TEST_DB_PATH = BASE_DIR / "test_app.db"

# Переменные окружения должны быть заданы до импорта приложения
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret-key-for-automated-tests"
os.environ["SMTP_HOST"] = ""
os.environ["LOG_LEVEL"] = "WARNING"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def user_factory(client):
    def _create(email: str = "user@example.com", password: str = "Password123") -> dict:
        register = client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert register.status_code == 201, register.text

        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        tokens = login.json()

        return {
            "id": register.json()["id"],
            "email": email,
            "password": password,
            "tokens": tokens,
            "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
        }

    return _create


@pytest.fixture()
def auth_headers(user_factory) -> dict[str, str]:
    return user_factory()["headers"]


def subscription_payload(**overrides) -> dict:
    payload = {
        "name": "Netflix",
        "category": "Развлечения",
        "cost": 599.00,
        "currency": "RUB",
        "period": "month",
        "first_payment_date": (date.today() + timedelta(days=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def make_subscription(client, auth_headers):
    def _create(**overrides) -> dict:
        response = client.post(
            "/api/v1/subscriptions", json=subscription_payload(**overrides), headers=auth_headers
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    engine.dispose()
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except OSError:
            pass
