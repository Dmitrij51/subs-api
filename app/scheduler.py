"""Фоновый планировщик автоплатежей и напоминаний."""

from __future__ import annotations

import asyncio
import logging

from .config import settings
from .database import SessionLocal
from .services.billing import process_due_payments, process_upcoming_notifications

logger = logging.getLogger(__name__)


def run_once() -> dict[str, int]:
    """Один проход планировщика: платежи и уведомления."""
    with SessionLocal() as db:
        payments = process_due_payments(db)
        notifications = process_upcoming_notifications(db)
    return {"payments": len(payments), "notifications": len(notifications)}


async def scheduler_loop() -> None:
    logger.info("Планировщик запущен, интервал опроса: %s с", settings.scheduler_interval_seconds)
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if result["payments"] or result["notifications"]:
                logger.info("Планировщик: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - планировщик не должен падать
            logger.exception("Ошибка в работе планировщика")
        await asyncio.sleep(settings.scheduler_interval_seconds)
