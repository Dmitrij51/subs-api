from __future__ import annotations


def test_register_normalizes_email_and_hides_password(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "User@Example.com", "password": "Password123"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@example.com", "password": "Password123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201

    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_register_weak_password_returns_422(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "8 символов" in body["message"]


def test_register_password_without_digits_returns_422(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "nodigit@example.com", "password": "OnlyLetters"}
    )
    assert response.status_code == 422
    assert "цифру" in response.json()["message"]


def test_register_invalid_email_returns_422(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "Password123"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_login_wrong_password_returns_401(client, user_factory):
    user_factory(email="login@example.com")
    response = client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "WrongPass123"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_protected_endpoint_requires_token(client):
    response = client.get("/api/v1/subscriptions")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

    response = client.get(
        "/api/v1/subscriptions", headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == 401


def test_access_token_lifetime_is_15_minutes(client, user_factory):
    tokens = user_factory()["tokens"]
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60


def test_refresh_rotation_and_logout(client, user_factory):
    tokens = user_factory(email="refresh@example.com")["tokens"]

    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # старый refresh-токен отозван ротацией
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401

    # выход отзывает refresh-токен
    response = client.post(
        "/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert response.status_code == 204

    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert response.status_code == 401


def test_password_reset_flow(client, user_factory, monkeypatch):
    user = user_factory(email="reset@example.com")
    captured: dict[str, str] = {}

    def fake_send(to: str, link: str) -> None:
        captured["to"] = to
        captured["link"] = link

    monkeypatch.setattr("app.routers.auth.send_password_reset_email", fake_send)

    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "reset@example.com"}
    )
    assert response.status_code == 200
    assert captured["to"] == "reset@example.com"
    token = captured["link"].split("token=")[1]

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "NewPassword456"},
    )
    assert response.status_code == 200

    # старый пароль больше не подходит
    response = client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": "Password123"}
    )
    assert response.status_code == 401

    # новый пароль работает
    response = client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": "NewPassword456"}
    )
    assert response.status_code == 200

    # ссылка одноразовая
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "Another12345"},
    )
    assert response.status_code == 400

    # старые сессии сброшены
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": user["tokens"]["refresh_token"]}
    )
    assert response.status_code == 401


def test_forgot_password_unknown_email_returns_same_response(client):
    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "unknown@example.com"}
    )
    assert response.status_code == 200
    assert "Если адрес зарегистрирован" in response.json()["message"]
