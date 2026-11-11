from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
}


class APIError(StarletteHTTPException):
    """HTTP-ошибка с машинным кодом из единого формата ответа."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def bad_request(message: str) -> APIError:
    return APIError(400, "BAD_REQUEST", message)


def unauthorized(message: str = "Требуется авторизация") -> APIError:
    return APIError(401, "UNAUTHORIZED", message)


def forbidden(message: str = "Доступ к чужим данным запрещен") -> APIError:
    return APIError(403, "FORBIDDEN", message)


def not_found(message: str = "Ресурс не найден") -> APIError:
    return APIError(404, "NOT_FOUND", message)


def conflict(message: str) -> APIError:
    return APIError(409, "CONFLICT", message)


_FIELD_MESSAGES: dict[str, str] = {
    "greater_than": "должно быть больше {gt}",
    "greater_than_equal": "должно быть не меньше {ge}",
    "less_than": "должно быть меньше {lt}",
    "less_than_equal": "должно быть не больше {le}",
    "string_too_short": "длина должна быть не менее {min_length} символов",
    "string_too_long": "длина должна быть не более {max_length} символов",
    "string_type": "должно быть строкой",
    "int_parsing": "должно быть целым числом",
    "int_type": "должно быть целым числом",
    "float_parsing": "должно быть числом",
    "float_type": "должно быть числом",
    "decimal_parsing": "должно быть числом",
    "decimal_max_places": "должно содержать не более {decimal_places} знаков после запятой",
    "decimal_max_digits": "содержит слишком много цифр",
    "date_parsing": "должно быть датой в формате YYYY-MM-DD",
    "date_from_datetime_parsing": "должно быть датой в формате YYYY-MM-DD",
    "datetime_parsing": "должно быть датой и временем в формате ISO 8601",
    "datetime_from_date_parsing": "должно быть датой и временем в формате ISO 8601",
    "time_delta_parsing": "должно быть интервалом времени",
    "enum": "должно быть одним из значений: {expected}",
    "literal_error": "должно быть одним из значений: {expected}",
    "bool_parsing": "должно быть логическим значением (true/false)",
    "bool_type": "должно быть логическим значением (true/false)",
    "json_invalid": "тело запроса не является корректным JSON",
    "list_type": "должно быть списком",
    "dict_type": "должно быть объектом",
    "model_attributes_type": "должно быть объектом",
    "extra_forbidden": "недопустимое поле",
    "too_long": "содержит слишком много элементов",
}


def _translate_validation_error(error: dict[str, Any]) -> str:
    loc = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path", "header")]
    field = loc[-1] if loc else "запрос"
    error_type = str(error.get("type", ""))
    ctx = error.get("ctx") or {}

    if error_type == "missing":
        return f"Поле '{field}' обязательно для заполнения"

    if error_type == "value_error":
        text = str(ctx.get("error") or error.get("msg") or "некорректное значение")
        text = text.removeprefix("Value error, ")
        return f"Поле '{field}': {text}" if loc else text

    template = _FIELD_MESSAGES.get(error_type)
    if template is not None:
        try:
            text = template.format(**ctx)
        except (KeyError, IndexError):
            text = template
        return f"Поле '{field}' {text}"

    return f"Поле '{field}': {error.get('msg', 'некорректное значение')}"


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    messages: list[str] = []
    for error in exc.errors()[:3]:
        message = _translate_validation_error(error)
        if message not in messages:
            messages.append(message)
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "; ".join(messages) or "Некорректные данные запроса",
        },
    )


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or STATUS_CODES.get(exc.status_code, "ERROR")
    detail = exc.detail
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, list):
        message = "; ".join(str(item) for item in detail)
    else:
        message = str(detail)

    if exc.status_code == 404 and message == "Not Found":
        message = "Ресурс не найден"
    elif exc.status_code == 405:
        message = "Метод не поддерживается для данного ресурса"

    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message},
        headers=headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Необработанная ошибка при обработке %s %s", request.method, request.url.path, exc_info=exc
    )
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
