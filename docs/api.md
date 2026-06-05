# LocalCloud — REST API

Справочник HTTP API LocalCloud. Все маршруты — под префиксом **`/api/v1`** (всего
**104** эндпоинта). Это обзорный документ; машиночитаемая спецификация и «живой»
клиент для проб запросов доступны через OpenAPI (см. ниже).

## Содержание

- [Базовый URL и версионирование](#базовый-url-и-версионирование)
- [Аутентификация](#аутентификация)
- [Права доступа](#права-доступа)
- [Формат ошибок](#формат-ошибок)
- [Постраничная навигация](#постраничная-навигация)
- [OpenAPI / Swagger](#openapi--swagger)
- [Группы эндпоинтов](#группы-эндпоинтов)
  - [auth](#auth--auth) · [registration](#registration--registration) ·
    [users](#users--users) · [quotas](#quotas--quotas) ·
    [nodes](#nodes--nodes-файлы-и-папки) · [folders](#folders--folders) ·
    [uploads](#uploads--uploads-multipart) · [downloads](#downloads--downloads) ·
    [trash](#trash--trash) · [permissions](#permissions--permissions) ·
    [public_links](#public_links--public-links) · [tasks](#tasks--tasks) ·
    [audit](#audit--audit) · [config](#config--config) · [health](#health--health)

---

## Базовый URL и версионирование

| Окружение | Базовый URL |
|---|---|
| Через шлюз nginx (Docker) | `http://localhost/api/v1` |
| Backend напрямую (dev) | `http://localhost:8000/api/v1` |

Версия API зашита в префикс пути (`/api/v1`). Несовместимые изменения вводятся
новым префиксом (`/api/v2`), старая версия некоторое время сосуществует.

## Аутентификация

Аутентификация — на **JWT в httpOnly-cookie**, токены в теле ответа не возвращаются
и в JavaScript недоступны (защита от XSS-кражи).

- `POST /auth/login` — по `email` + `password` выставляет cookie:
  `access_token` (короткоживущий) и `refresh_token` (долгоживущий, ротируется).
- `POST /auth/refresh` — по `refresh_token`-cookie выдаёт новую пару (silent
  refresh; клиент вызывает прозрачно при `401`).
- `POST /auth/logout` — отзывает refresh-сессию и чистит cookie.

Так как фронтенд и API живут на одном origin (через nginx), CSRF закрывается
`SameSite`-cookie; отдельный CSRF-токен не нужен.

## Права доступа

В таблицах ниже уровень доступа помечен значками:

| Значок | Значение |
|---|---|
| 🌐 | Публичный — без аутентификации |
| 🔑 | Любой аутентифицированный пользователь |
| 🛡️ | Только администратор (`role = admin`) |

Для операций над узлами (файлы/папки) дополнительно проверяется **право на узел**
(`read` / `download` / `write` / `delete` / `owner`) с наследованием от
родительских папок и с учётом выданных другим пользователям доступов.

## Формат ошибок

Ошибки возвращаются с соответствующим HTTP-статусом и JSON-телом:

```json
{
  "detail": "Человекочитаемое описание ошибки"
}
```

Типовые коды: `400` (валидация/бизнес-правило), `401` (нет/просрочена сессия),
`403` (нет прав), `404` (не найдено), `409` (конфликт, напр. имя занято),
`413` (превышение квоты/лимита), `422` (ошибка схемы запроса), `429` (rate limit).

## Постраничная навигация

Списочные эндпоинты принимают `limit` и `offset` (или курсор, где указано) и
возвращают объект с элементами и метаданными пагинации (`total`, `limit`,
`offset`). Конкретные поля — в OpenAPI-схеме соответствующего ответа.

## OpenAPI / Swagger

FastAPI генерирует спецификацию OpenAPI автоматически. В debug-режиме
(`DEBUG=true`) доступны:

| URL | Назначение |
|---|---|
| `…:8000/docs` | Swagger UI — интерактивные пробы запросов |
| `…:8000/redoc` | ReDoc — читаемая документация |
| `…:8000/openapi.json` | Машиночитаемая схема OpenAPI 3.1 |

В production интерактивные UI по умолчанию выключены; схему можно сгенерировать
из приложения программно.

---

## Группы эндпоинтов

### `auth` — `/auth`
| Метод | Путь | Доступ |
|---|---|---|
| POST | `/auth/login` | 🌐 |
| POST | `/auth/refresh` | 🌐 (refresh-cookie) |
| POST | `/auth/logout` | 🔑 |
| GET | `/auth/me` | 🔑 |
| POST | `/auth/password/change` | 🔑 |
| GET | `/auth/sessions` | 🔑 |
| DELETE | `/auth/sessions/{session_id}` | 🔑 |

### `registration` — `/registration`
Регистрация — по заявке с последующим одобрением администратором.

| Метод | Путь | Доступ |
|---|---|---|
| POST | `/registration/requests` | 🌐 (подать заявку) |
| POST | `/registration/requests/{request_id}/cancel` | 🌐 |
| GET | `/registration/requests` | 🛡️ |
| GET | `/registration/requests/{request_id}` | 🛡️ |
| POST | `/registration/requests/{request_id}/approve` | 🛡️ |
| POST | `/registration/requests/{request_id}/reject` | 🛡️ |

### `users` — `/users`
| Метод | Путь | Доступ |
|---|---|---|
| GET / PATCH | `/users/me` | 🔑 |
| GET | `/users/lookup` | 🔑 (поиск пользователей для шаринга) |
| GET | `/users/` | 🛡️ |
| GET / PATCH / DELETE | `/users/{user_id}` | 🛡️ |
| POST | `/users/{user_id}/approve` · `/reject` · `/block` · `/unblock` · `/change-password` | 🛡️ |

### `quotas` — `/quotas`
| Метод | Путь | Доступ |
|---|---|---|
| GET / POST | `/quotas/me` · `/quotas/check` | 🔑 |
| GET | `/quotas/server/capacity` | 🛡️ |
| GET / PUT | `/quotas/users/{user_id}` | 🛡️ |
| POST | `/quotas/recalculate` | 🛡️ |

### `nodes` — `/nodes` (файлы и папки)
Узел (node) — общее имя для файла и папки в дереве. Все требуют 🔑 и
соответствующего права на узел.

| Метод | Путь |
|---|---|
| GET | `/nodes/` · `/nodes/tree` · `/nodes/search` |
| POST | `/nodes/thumbnails/batch` |
| GET | `/nodes/{node_id}` · `/breadcrumbs` · `/content` · `/thumbnail` · `/stream` |
| PATCH | `/nodes/{node_id}` |
| POST | `/nodes/{node_id}/rename` · `/move` · `/copy` · `/download` |
| DELETE | `/nodes/{node_id}` (мягкое удаление — в корзину) |

### `folders` — `/folders`
`POST /folders/` · `GET /folders/{id}` · `PATCH /folders/{id}` ·
`GET /folders/{id}/content` · `POST /folders/{id}/archive` (упаковка в ZIP фоновой
задачей). Доступ — 🔑 + право на папку.

### `uploads` — `/uploads` (multipart)
Многочастичная загрузка напрямую в MinIO/S3 по presigned-URL. Доступ — 🔑.

`POST /uploads/` (инициировать сессию) · `GET /uploads/` · `GET /uploads/{id}` ·
`GET /uploads/{id}/progress` · `POST /uploads/{id}/parts/presigned` ·
`POST /uploads/{id}/parts/{part_number}/complete` · `POST /uploads/{id}/complete` ·
`POST /uploads/{id}/abort`.

### `downloads` — `/downloads`
`POST /downloads/archive/{task_id}` (ссылка на готовый архив) ·
`POST /downloads/bulk-archive` (архив произвольного набора узлов). Доступ — 🔑.

### `trash` — `/trash`
`GET /trash/` · `POST /trash/{trash_item_id}/restore` ·
`POST /trash/{trash_item_id}/purge` · `POST /trash/empty` (🔑) ·
`POST /trash/cleanup` (🛡️ — автоочистка истёкших элементов).

### `permissions` — `/permissions` (доступ между пользователями)
Доступ — 🔑.

`POST /permissions/grant` · `POST /permissions/revoke` · `POST /permissions/check` ·
`PATCH /permissions/{permission_id}` · `GET /permissions/nodes/{node_id}` ·
`GET /permissions/nodes/{node_id}/effective` · `GET /permissions/shared-with-me` ·
`GET /permissions/shared-by-me`.

### `public_links` — `/public-links`
**Управление** (🔑): `POST /public-links/` · `GET /public-links/` ·
`GET /public-links/node-ids` · `GET /public-links/{link_id}` ·
`PATCH /public-links/{link_id}` · `POST /public-links/{link_id}/revoke`.

**Публичный доступ по токену** (🌐, опционально под паролем):
`GET /public-links/public/{token}` ·
`POST /public-links/public/{token}/access` · `/download` · `/thumbnail` ·
`/folder-download` · `GET …/folder-download/{task_id}`.

### `tasks` — `/tasks` (фоновые задачи)
`GET /tasks/` · `GET /tasks/{id}` · `/progress` · `/result` ·
`POST /tasks/{id}/cancel` (🔑) · `POST /tasks/` · `POST /tasks/{id}/retry` (🛡️).

### `audit` — `/audit`
Доступ — 🛡️.

`GET /audit/logs` · `GET /audit/logs/{log_id}` · `GET /audit/summary` ·
`GET /audit/users/{user_id}/latest` · `POST /audit/export`.

### `config` — `/config`
`GET /config` (🌐) — публичные флаги функциональности (`FEATURE_*`) для фронтенда:
включены ли превью, просмотрщик, проигрывание медиа, редактирование.

### `health` — `/health`
`GET /health/live` · `GET /health/ready` (🌐 — пробы готовности/живости для
оркестратора) · `GET /health/` · `/database` · `/storage` (🛡️ — детальная
диагностика подсистем).

---

См. также: [`backend/README.md`](../backend/README.md) — слои приложения, схемы
данных и бизнес-логика за этими эндпоинтами.
