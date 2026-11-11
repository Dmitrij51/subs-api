from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Отправляет письмо. Без настроенного SMTP письмо только логируется."""
    if not settings.smtp_host:
        logger.info(
            "SMTP не настроен. Письмо не отправлено.\nКому: %s\nТема: %s\n%s", to, subject, body
        )
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception:  # noqa: BLE001 - письмо не должно ломать бизнес-операцию
        logger.exception("Не удалось отправить письмо на %s", to)
        return False


def send_password_reset_email(to: str, link: str) -> None:
    send_email(
        to,
        "Восстановление пароля",
        "Для установки нового пароля перейдите по ссылке:\n"
        f"{link}\n\n"
        f"Ссылка действует {settings.password_reset_token_expire_minutes} минут. "
        "Если вы не запрашивали восстановление пароля, проигнорируйте это письмо.",
    )


def send_payment_reminder_email(
    to: str,
    subscription_name: str,
    amount: str,
    currency: str,
    due_date: str,
    days_left: int,
) -> None:
    send_email(
        to,
        f"Скоро списание по подписке «{subscription_name}»",
        f"Напоминаем: {due_date} (через {days_left} дн.) будет списано "
        f"{amount} {currency} по подписке «{subscription_name}».",
    )
