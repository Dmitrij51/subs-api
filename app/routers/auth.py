from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..emailer import send_password_reset_email
from ..errors import bad_request, conflict, forbidden, unauthorized
from ..models import PasswordResetToken, RefreshToken, User, utcnow
from ..schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserRead,
)
from ..security import (
    TokenError,
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_reset_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    """Выдает пару токенов и сохраняет refresh-токен для возможности отзыва."""
    access_token, _, _ = create_access_token(user.id)
    refresh_token, jti, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация пользователя",
    responses={409: {"description": "Адрес электронной почты уже зарегистрирован"}},
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise conflict("Пользователь с таким адресом электронной почты уже зарегистрирован")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход, выдача access- и refresh-токенов",
    responses={401: {"description": "Неверная пара email/пароль"}},
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise unauthorized("Неверный адрес электронной почты или пароль")
    if not user.is_active:
        raise forbidden("Учетная запись заблокирована")
    return _issue_tokens(db, user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access-токена",
    responses={401: {"description": "Refresh-токен недействителен или отозван"}},
)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise unauthorized(str(exc)) from exc

    record = db.scalar(select(RefreshToken).where(RefreshToken.jti == token_payload.get("jti")))
    if record is None:
        raise unauthorized("Refresh-токен не найден")
    if record.revoked_at is not None:
        raise unauthorized("Refresh-токен отозван")
    if record.expires_at <= utcnow():
        raise unauthorized("Срок действия refresh-токена истек")

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise unauthorized("Пользователь не найден или заблокирован")

    # Ротация: старый refresh-токен отзывается, выдается новая пара
    record.revoked_at = utcnow()
    return _issue_tokens(db, user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Выход, отзыв refresh-токена",
)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> Response:
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise unauthorized(str(exc)) from exc

    record = db.scalar(select(RefreshToken).where(RefreshToken.jti == token_payload.get("jti")))
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Запрос ссылки для восстановления пароля",
)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is not None and user.is_active:
        token, token_hash = create_password_reset_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=utcnow() + timedelta(minutes=settings.password_reset_token_expire_minutes),
            )
        )
        db.commit()
        send_password_reset_email(user.email, f"{settings.frontend_reset_url}?token={token}")

    # Одинаковый ответ, чтобы нельзя было проверить наличие адреса в системе
    return MessageResponse(
        message="Если адрес зарегистрирован, на него отправлена ссылка для восстановления пароля"
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Установка нового пароля по одноразовой ссылке",
    responses={400: {"description": "Ссылка недействительна или истекла"}},
)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_reset_token(payload.token)
        )
    )
    if record is None or record.used_at is not None or record.expires_at <= utcnow():
        raise bad_request("Ссылка для восстановления пароля недействительна или истекла")

    user = db.get(User, record.user_id)
    if user is None:
        raise bad_request("Ссылка для восстановления пароля недействительна или истекла")

    user.password_hash = hash_password(payload.new_password)
    record.used_at = utcnow()
    # Все активные сессии сбрасываются
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
    return MessageResponse(message="Пароль успешно изменен")


@router.get("/me", response_model=UserRead, summary="Профиль текущего пользователя")
def read_me(user: User = Depends(get_current_user)) -> User:
    return user
