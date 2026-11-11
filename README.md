# Сервис управления подписками — бэкенд API

REST API на FastAPI для учета регулярных платежей пользователя: подписки, история
платежей, автоматические списания, напоминания и аналитика расходов.

- формат обмена — JSON, кодировка UTF-8;
- префикс всех эндпоинтов — `/api/v1`;
- аутентификация — JWT Bearer (access-токен 15 минут, refresh-токен 30 дней);
- единственная роль — пользователь; доступ к данным ограничен владельцем;
- интерактивная документация — <http://127.0.0.1:8000/api/v1/docs>.

## Стек

| Компонент                      | Назначение                                                |
| ------------------------------ | --------------------------------------------------------- |
| FastAPI + Uvicorn              | HTTP-слой, OpenAPI/Swagger                                |
| SQLAlchemy 2.0                 | ORM, модели и запросы                                     |
| SQLite (по умолчанию)          | хранилище; `DATABASE_URL` позволяет перейти на PostgreSQL |
| Pydantic 2 / pydantic-settings | валидация схем и конфигурация                             |
| PyJWT                          | access- и refresh-токены                                  |
| bcrypt                         | хеширование паролей                                       |
| python-dateutil                | расчет дат платежей (месяц/год, конец месяца)             |
| pytest + httpx                 | автотесты                                                 |

## Запуск

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env        # Linux/macOS: cp .env.example .env

uvicorn app.main:app --reload
```

Сервис: <http://127.0.0.1:8000>, Swagger: <http://127.0.0.1:8000/api/v1/docs>,
OpenAPI: <http://127.0.0.1:8000/api/v1/openapi.json>.

Таблицы создаются автоматически при старте. Для PostgreSQL достаточно изменить
`DATABASE_URL`, например `postgresql+psycopg://user:password@localhost:5432/subscriptions`.

## Структура проекта

```
app/
  main.py              создание приложения, lifespan, подключение роутеров
  config.py            настройки из переменных окружения/.env
  database.py          движок, сессии, Base
  models.py            User, RefreshToken, PasswordResetToken, Subscription, Payment, Notification
  schemas.py           Pydantic-схемы запросов и ответов
  security.py          JWT, хеширование паролей, одноразовые токены
  deps.py              зависимость get_current_user (Bearer)
  errors.py            единый формат ошибок и обработчики исключений
  emailer.py           отправка писем (SMTP или лог в режиме разработки)
  scheduler.py         фоновый планировщик автоплатежей и напоминаний
  routers/             auth, subscriptions, payments, analytics, notifications
  services/            периодичность, биллинг, аналитика, проверка владельца
tests/                 автотесты (60 сценариев)
```

## Аутентификация

| Что                          | Срок жизни                                               |
| ---------------------------- | -------------------------------------------------------- |
| access-токен                 | 15 минут                                                 |
| refresh-токен                | 30 дней (хранится в БД, отзывается при выходе и ротации) |
| ссылка восстановления пароля | 60 минут, одноразовая                                    |

Защищенные запросы требуют заголовок:

```
Authorization: Bearer <access-токен>
```

Публичные эндпоинты: `POST /auth/register`, `POST /auth/login`, а также
`POST /auth/forgot-password` и `POST /auth/reset-password` (восстановление пароля
физически не может требовать действующий токен).

Пароль: не менее 8 символов, минимум одна буква и одна цифра. Адрес электронной
почты проверяется на формат и уникальность.

## Состав API

| Метод  | Путь                                | Назначение                                                    | Успех |
| ------ | ----------------------------------- | ------------------------------------------------------------- | ----- |
| POST   | `/api/v1/auth/register`             | Регистрация пользователя                                      | 201   |
| POST   | `/api/v1/auth/login`                | Вход, выдача access- и refresh-токенов                        | 200   |
| POST   | `/api/v1/auth/refresh`              | Обновление access-токена (с ротацией refresh)                 | 200   |
| POST   | `/api/v1/auth/logout`               | Выход, отзыв refresh-токена                                   | 204   |
| POST   | `/api/v1/auth/forgot-password`      | Запрос ссылки восстановления пароля                           | 200   |
| POST   | `/api/v1/auth/reset-password`       | Установка нового пароля по ссылке                             | 200   |
| GET    | `/api/v1/auth/me`                   | Профиль текущего пользователя                                 | 200   |
| GET    | `/api/v1/subscriptions`             | Список подписок (`category`, `status`, `sort`, `order`)       | 200   |
| POST   | `/api/v1/subscriptions`             | Создание подписки                                             | 201   |
| GET    | `/api/v1/subscriptions/{id}`        | Подписка с историей платежей                                  | 200   |
| PATCH  | `/api/v1/subscriptions/{id}`        | Изменение параметров подписки                                 | 200   |
| POST   | `/api/v1/subscriptions/{id}/pause`  | Приостановка подписки                                         | 200   |
| POST   | `/api/v1/subscriptions/{id}/resume` | Возобновление подписки                                        | 200   |
| DELETE | `/api/v1/subscriptions/{id}`        | Отмена подписки (данные сохраняются)                          | 204   |
| GET    | `/api/v1/payments`                  | История платежей (`page`, `per_page`, `date_from`, `date_to`) | 200   |
| POST   | `/api/v1/payments`                  | Ручное добавление платежа                                     | 201   |
| DELETE | `/api/v1/payments/{id}`             | Удаление платежа                                              | 204   |
| GET    | `/api/v1/analytics/summary`         | Суммарные, средние, минимальные и максимальные расходы        | 200   |
| GET    | `/api/v1/analytics/by-category`     | Распределение расходов по категориям                          | 200   |
| GET    | `/api/v1/analytics/forecast`        | Прогноз расходов на следующий период                          | 200   |
| GET    | `/api/v1/analytics/export`          | Выгрузка отчета (`format=csv\|json`)                          | 200   |
| GET    | `/api/v1/notifications`             | Напоминания о предстоящих списаниях                           | 200   |
| POST   | `/api/v1/notifications/{id}/read`   | Отметить уведомление прочитанным                              | 200   |
| GET    | `/api/v1/health`                    | Проверка работоспособности                                    | 200   |

`GET /api/v1/subscriptions/{id}` возвращает подписку вместе с массивом `payments`.

## Примеры запросов

### Регистрация и вход

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Password123"}'

curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "Password123"}'
```

Ответ входа:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### Создание подписки

```bash
curl -X POST http://127.0.0.1:8000/api/v1/subscriptions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Netflix",
    "category": "Развлечения",
    "cost": 599.00,
    "currency": "RUB",
    "period": "month",
    "first_payment_date": "2025-03-01"
  }'
```

Ответ `201` содержит `id` и рассчитанную `next_payment_date` — ближайшую дату
списания не раньше сегодняшнего дня (даты считаются от `first_payment_date`,
поэтому конец месяца не «съезжает»: 31.01 → 28.02 → 31.03).

### Список подписок

```bash
curl "http://127.0.0.1:8000/api/v1/subscriptions?category=Развлечения&status=active&sort=cost&order=desc" \
  -H "Authorization: Bearer $TOKEN"
```

### Платежи

```bash
# история с пагинацией и фильтром по периоду
curl "http://127.0.0.1:8000/api/v1/payments?page=1&per_page=20&date_from=2026-01-01&date_to=2026-12-31" \
  -H "Authorization: Bearer $TOKEN"

# ручное добавление
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"subscription_id": 1, "amount": 599, "paid_at": "2026-02-01", "note": "Оплата вручную"}'
```

Ответ списка платежей:

```json
{
  "items": [
    {
      "id": 1,
      "subscription_id": 1,
      "subscription_name": "Netflix",
      "category": "Развлечения",
      "amount": 599.0,
      "currency": "RUB",
      "paid_at": "2026-02-01T00:00:00",
      "source": "manual"
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 20,
  "pages": 1
}
```

### Аналитика

```bash
curl "http://127.0.0.1:8000/api/v1/analytics/summary?date_from=2026-01-01&date_to=2026-12-31" \
  -H "Authorization: Bearer $TOKEN"

curl "http://127.0.0.1:8000/api/v1/analytics/by-category" -H "Authorization: Bearer $TOKEN"
curl "http://127.0.0.1:8000/api/v1/analytics/forecast?horizon_days=30&history_days=90" \
  -H "Authorization: Bearer $TOKEN"
curl -OJ "http://127.0.0.1:8000/api/v1/analytics/export?format=csv" -H "Authorization: Bearer $TOKEN"
```

`summary` дополнительно возвращает разбивку `by_currency`; `forecast` — сумму
запланированных списаний (`scheduled_total`), прогноз по истории
(`history_based_forecast`) и список ближайших списаний (`upcoming`). CSV
отдается в UTF-8 с BOM и разделителем `;`, чтобы файл корректно открывался в Excel.

## Планировщик

При старте приложения запускается фоновая задача (`app/scheduler.py`), которая
раз в `SCHEDULER_INTERVAL_SECONDS` (по умолчанию час) и сразу после запуска:

1. регистрирует платежи по всем активным подпискам, у которых наступила
   `next_payment_date`, и сдвигает дату следующего платежа (при пропуске нескольких
   периодов создается платеж за каждый из них);
2. создает уведомление и отправляет письмо, если до списания осталось ровно
   `notify_days_before` дней (значение задается при создании подписки, по умолчанию 3).

Уведомления сохраняются в БД и доступны через `GET /api/v1/notifications`.
Планировщик отключается переменной `SCHEDULER_ENABLED=false` (например, в тестах).

Письма отправляются через SMTP, если задан `SMTP_HOST`. Без SMTP ссылка
восстановления пароля и напоминания пишутся в лог приложения (режим разработки).

## Формат ошибок

Все ошибки возвращаются в едином виде:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Поле 'cost' должно быть больше 0"
}
```

| Код HTTP | `code`             | Когда возникает                                             |
| -------- | ------------------ | ----------------------------------------------------------- |
| 400      | `BAD_REQUEST`      | некорректный запрос, неверный период, недопустимое действие |
| 401      | `UNAUTHORIZED`     | нет токена, токен истек или отозван                         |
| 403      | `FORBIDDEN`        | обращение к подписке/платежу другого пользователя           |
| 404      | `NOT_FOUND`        | ресурс не найден                                            |
| 409      | `CONFLICT`         | дубликат email, повторная приостановка/возобновление        |
| 422      | `VALIDATION_ERROR` | ошибка валидации тела или параметров запроса                |
| 500      | `INTERNAL_ERROR`   | внутренняя ошибка сервера                                   |

## Тесты

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Покрыты: регистрация/вход/обновление и отзыв токенов, сброс пароля, CRUD подписок,
фильтры и сортировка, пагинация платежей, разграничение доступа (403), аналитика,
экспорт CSV/JSON, планировщик и расчет дат платежей, контракт OpenAPI.

## Ограничения

- Аналитика суммирует суммы без конвертации валют; для корректных итогов
  используйте фильтр `currency` или разбивку `by_currency`. Прогноз считается
  в основной валюте пользователя (наибольшее число платежей).
- Планировщик работает в процессе приложения; при нескольких воркерах
  `uvicorn` его следует вынести в отдельный процесс или отключить на лишних
  экземплярах (`SCHEDULER_ENABLED=false`).
