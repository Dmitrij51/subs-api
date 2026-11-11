from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..errors import forbidden, not_found
from ..models import Notification, User
from ..schemas import NotificationRead

router = APIRouter(prefix="/notifications", tags=["Уведомления"])


@router.get(
    "",
    response_model=list[NotificationRead],
    summary="Уведомления текущего пользователя",
)
def list_notifications(
    only_unread: bool = Query(default=False, description="Только непрочитанные"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if only_unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Отметить уведомление прочитанным",
)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise not_found("Уведомление не найдено")
    if notification.user_id != user.id:
        raise forbidden("Доступ к уведомлению другого пользователя запрещен")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification
