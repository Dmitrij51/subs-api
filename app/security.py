from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import InvalidTokenError

from .config import settings


class TokenError(Exception):
    """Ошибка разбора или проверки JWT."""


def _prehash(password: str) -> bytes:
    """Предварительное хеширование: bcrypt ограничен 72 байтами входа."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, token_type: str, expires_delta: timedelta) -> tuple[str, str, datetime]:
    """Возвращает (токен, jti, срок действия в UTC без tzinfo)."""
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at.astimezone(timezone.utc).replace(tzinfo=None)


def create_access_token(user_id: int) -> tuple[str, str, datetime]:
    return create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    return create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str | None = None) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise TokenError("Недействительный или истекший токен") from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise TokenError("Неверный тип токена")
    if not payload.get("sub"):
        raise TokenError("Некорректное содержимое токена")
    return payload


def create_password_reset_token() -> tuple[str, str]:
    """Возвращает (одноразовый токен для ссылки, его sha256-хеш для хранения)."""
    token = secrets.token_urlsafe(32)
    return token, hash_reset_token(token)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
