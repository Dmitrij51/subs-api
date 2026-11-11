from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .errors import unauthorized
from .models import User
from .security import TokenError, decode_token

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT access-токен, полученный при входе или обновлении токена",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Проверяет Bearer access-токен и возвращает текущего пользователя."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Отсутствует заголовок Authorization: Bearer <access-токен>")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise unauthorized(str(exc)) from exc

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise unauthorized("Некорректный идентификатор пользователя в токене") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("Пользователь не найден или заблокирован")
    return user
