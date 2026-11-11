from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .errors import register_exception_handlers
from .routers import analytics, auth, notifications, payments, subscriptions
from .scheduler import scheduler_loop

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DESCRIPTION = """
Бэкенд-сервис управления подписками пользователя.

Возможности:
* регистрация и аутентификация по JWT (access-токен 15 минут, refresh-токен 30 дней);
* восстановление пароля по одноразовой ссылке;
* учет подписок: создание, изменение, приостановка, возобновление и отмена;
* история платежей с постраничной выдачей и фильтрацией по периоду;
* автоматические списания и напоминания о предстоящих платежах (встроенный планировщик);
* аналитика расходов: сводка, категории, прогноз и выгрузка отчета в CSV/JSON.

Все эндпоинты имеют префикс `/api/v1`. Доступ к данным ограничен владельцем:
каждый пользователь видит только свои подписки и платежи.

Для защищенных запросов передавайте заголовок:
`Authorization: Bearer <access-токен>`.
"""

TAGS_METADATA = [
    {
        "name": "Аутентификация",
        "description": "Регистрация, вход, обновление и отзыв токенов, сброс пароля.",
    },
    {"name": "Подписки", "description": "Управление подписками текущего пользователя."},
    {"name": "Платежи", "description": "История платежей и ручное добавление записей."},
    {
        "name": "Аналитика",
        "description": "Сводные показатели, категории, прогноз и выгрузка отчета.",
    },
    {"name": "Уведомления", "description": "Напоминания о предстоящих списаниях."},
    {"name": "Служебные", "description": "Проверка работоспособности сервиса."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    task: asyncio.Task | None = None
    if settings.scheduler_enabled:
        task = asyncio.create_task(scheduler_loop(), name="billing-scheduler")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=f"{settings.api_prefix}/docs/oauth2-redirect",
        lifespan=lifespan,
        swagger_ui_parameters={
            "persistAuthorization": True,
            "displayRequestDuration": True,
        },
        contact={"name": "NLP-Core-Team"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    for router in (
        auth.router,
        subscriptions.router,
        payments.router,
        analytics.router,
        notifications.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)

    service_router = APIRouter(tags=["Служебные"])

    @service_router.get("/health", summary="Проверка работоспособности")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(service_router, prefix=settings.api_prefix)
    return app


app = create_app()
