# Changelog

Все значимые изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Documentation
- Добавлены реальные скриншоты интерфейса (вход, файловый браузер, просмотр файла,
  общий доступ, админ-панель, мобильная вёрстка) в `docs/screenshots/` и README.

## [0.1.1] — 2026-06-13

### Fixed
- Генератор `.env` (`scripts/generate_env.py`) при повторном запуске в существующий
  файл теперь **сохраняет** ранее сгенерированные секреты (`SECRET_KEY`,
  `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`, `ADMIN_PASSWORD`) вместо перезаписи. Это
  устраняет рассинхронизацию пароля роли PostgreSQL с томом `pg_data` и падение
  `api` с `InvalidPasswordError`. Принудительная ротация — флагом
  `--rotate-secrets`.

## [0.1.0] — 2026-06-06

Первый функционально полный выпуск LocalCloud — self-hosted веб-приложения для
организации личного файлового хранилища.

### Added

**Backend (FastAPI + фоновый worker)**
- Ядро приложения, инфраструктура и метаданные базы данных (SQLAlchemy 2 async + asyncpg).
- Доменные модели (18 таблиц), репозитории и Unit of Work для транзакционной работы с БД.
- Миграции схемы базы данных (Alembic).
- Слой безопасности: аутентификация и авторизация (JWT в httpOnly-cookie, ротация
  refresh-токенов, хэширование паролей bcrypt/argon2, ролевая модель и права на ресурсы).
- Интеграция с объектным S3-совместимым хранилищем (MinIO): presigned-URL, многочастичная
  загрузка, архивы, превью.
- Pydantic-схемы запросов и ответов; бизнес-сервисы; REST API `/api/v1` (15 роутеров).
- Фоновый обработчик задач (диспетчер, реестр, планировщик): архивы, генерация превью,
  очистка истёкших данных, проверка целостности, пересчёт квот.
- Точка входа FastAPI, конфигурация через переменные окружения, Docker-сборка.

**Frontend (React 19 + TypeScript, Vite)**
- TypeScript-типы, модули API-клиента (axios + silent refresh), хуки и контексты.
- Переиспользуемые UI-примитивы (Radix UI / shadcn), компоненты управления файлами,
  макета приложения, авторизации, квот и предпросмотра.
- Страницы приложения и точка входа; адаптивный интерфейс, тёмная и светлая темы.
- Docker-сборка SPA и раздача статики.

**Инфраструктура**
- Шлюз/reverse-proxy nginx (единая точка входа, проксирование `/api` и bucket-путей).
- Docker Compose для полного стека (postgres, minio, api, worker, frontend, nginx).
- Конфигурация окружения (`.env.example`), документация (README, README backend/frontend).

**Качество**
- Полный набор автоматических тестов backend (модульные и интеграционные, pytest).
- Тесты frontend (Vitest + Testing Library): компоненты, хуки, страницы, API-слой.

### Security
- Хранение паролей и refresh-токенов только в виде хэшей.
- Защита от типовых веб-уязвимостей (SQL-инъекции — параметризованные запросы;
  XSS — httpOnly-cookie и экранирование; CSRF — SameSite-cookie и единый origin).
- Журнал аудита действий пользователей и системных событий.

[Unreleased]: https://github.com/magomedov-dev/LocalCloud/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/magomedov-dev/LocalCloud/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/magomedov-dev/LocalCloud/releases/tag/v0.1.0
