# LocalCloud — Frontend

SPA на **React 19 + TypeScript + Vite**: файловый менеджер с multipart-загрузкой
напрямую в объектное хранилище, превью, общим доступом по ссылкам и пользователям,
корзиной и админ-панелью. Общается с backend по `/api/v1`, а с хранилищем — по
presigned-URL.

Часть монорепозитория **LocalCloud** — общий обзор и запуск всего стека в
[корневом README](../README.md).

---

## Содержание

- [Стек и зависимости](#стек-и-зависимости)
- [Скрипты](#скрипты)
- [Структура каталогов](#структура-каталогов)
- [Маршрутизация](#маршрутизация)
- [Страницы](#страницы)
- [API-слой](#api-слой)
- [Состояние и данные](#состояние-и-данные)
- [Компоненты](#компоненты)
- [Ключевые механики](#ключевые-механики)
- [Конфигурация и константы](#конфигурация-и-константы)
- [Тесты](#тесты)
- [Docker](#docker)

---

## Стек и зависимости

- **React 19** + React DOM, **TypeScript 6** (strict).
- **Vite 8** (`@vitejs/plugin-react`) — сборка и dev-сервер с HMR.
- **React Router 7** — клиентская маршрутизация.
- **TanStack Query 5** — серверное состояние (кэш, инвалидация, infinite query).
- **Axios** — HTTP-клиент с silent-refresh при `401`.
- **Tailwind CSS v4** (`@tailwindcss/vite`) + **Radix UI / shadcn** — UI-примитивы.
- **lucide-react** — иконки; **sonner** — тосты; **next-themes** — тема.
- **react-markdown** + **remark-gfm** — рендер Markdown в просмотрщике.
- **Тесты** — Vitest + Testing Library + jsdom; Playwright (E2E).
- **Качество** — ESLint (flat config) + Prettier (с `prettier-plugin-tailwindcss`).

Точные версии — в [`package.json`](./package.json).

---

## Скрипты

| Команда | Действие |
|---|---|
| `npm run dev` | Dev-сервер Vite (`http://localhost:5173`), проксирует `/api` на `:8000`. |
| `npm run build` | `tsc -b` (проверка типов) + `vite build` → `dist/`. |
| `npm run preview` | Локальный предпросмотр собранного бандла. |
| `npm run lint` | ESLint по всему проекту. |
| `npm test` | Vitest (однократный прогон). |
| `npm run test:watch` | Vitest в watch-режиме. |
| `npm run test:coverage` | Прогон с отчётом покрытия (v8). |

---

## Структура каталогов

```
frontend/
├── public/              статика (favicon, иконки)
├── src/
│   ├── api/             API-клиенты по доменам (axios)
│   ├── components/      UI: ui/ (примитивы), files/, preview/, layout/, auth/
│   ├── contexts/        React-контексты (auth, upload, breadcrumb, infoPanel)
│   ├── hooks/           кастомные хуки (browser, upload, thumbnails, features…)
│   ├── lib/             axios, query-client, тема, константы, утилиты, кэши
│   ├── pages/           страницы-маршруты (+ admin/)
│   ├── types/           TypeScript-типы API и состояния
│   ├── App.tsx          маршруты
│   └── main.tsx         точка входа (провайдеры)
├── tests/               Vitest-тесты (pages, hooks, contexts, components)
├── Dockerfile           multi-stage: сборка → nginx
├── nginx.conf           SPA-сервер (history-fallback, кэш /assets)
├── vite.config.ts       алиас @ → src, dev-proxy /api → :8000
└── vitest.config.ts     jsdom, setup, пороги покрытия
```

### `src/` подробнее

| Каталог | Содержимое |
|---|---|
| `api/` | По модулю на домен: `auth`, `users`, `nodes`, `folders`, `uploads`, `downloads`, `trash`, `permissions`, `public-links`, `quotas`, `registration`, `tasks`, `audit`, `config` (+ `index.ts`). |
| `components/ui/` | shadcn/Radix-примитивы: button, dialog, dropdown-menu, context-menu, tooltip, avatar, badge, breadcrumb, card, checkbox, progress, separator, sheet, skeleton, sonner и др. |
| `components/files/` | Файловый браузер и действия: `FileGrid`, `FileGridItem`, `FileListItem`, `FileIcon`, `ItemActions`, `ItemContextMenu`, `ShareDialog`, `UserShareTab`, `RenameDialog`, `MoveDialog`, `DeleteConfirmDialog`, `CreateFolderDialog`, `FolderColorDialog`, `UploadPanel`, `DropZone`, `FileActionBar`, `FileMultiActionBar`, `FileFilterBar`, `NodeInfoPanel` (+ утилиты). |
| `components/preview/` | `FilePreviewModal` (просмотр/проигрывание/редактирование) и `filePreviewKind.ts` (определение типа). |
| `components/layout/` | `AppShell`, `Sidebar`, `TopBar`, `NavItem`, `SearchBar`, `UserMenu`, `ThemeToggle`. |
| `components/auth/` | `ProtectedRoute`, `ChangePasswordDialog`. |
| `contexts/` | `auth`, `upload`, `breadcrumb`, `infoPanel`. |
| `hooks/` | `useFileBrowser`, `useThumbnails`, `useFeatures`, `useQuota`, `useShareBadges`, `useSharedWithMe`, `useFolderUpload`, `useArchiveDownload`, `useBulkDownload`, `useFolderDownload`. |
| `lib/` | `api.ts` (axios + refresh), `query-client.ts`, `theme.tsx`, `constants.ts`, `utils.ts`, `preview.ts`, `download.ts`, `errors.ts`, `accessLevels.ts`, `folderCache.ts`, `thumbnailCache.ts`, `sharedNode.ts`. |

---

## Маршрутизация

`src/App.tsx` (React Router 7). Публичные маршруты — без оболочки; защищённые —
внутри `AppShell` (через `ProtectedRoute`).

| Путь | Компонент | Доступ |
|---|---|---|
| `/login` | `LoginPage` | 🌐 |
| `/register` | `RegisterPage` | 🌐 |
| `/share/:token` | `SharePage` | 🌐 (публичная ссылка) |
| `/` → `/files` | — | 🔑 |
| `/files` | `FilesPage` | 🔑 |
| `/files/folders/:nodeId` | `FilesPage` | 🔑 |
| `/shared` | `SharedPage` | 🔑 |
| `/trash` | `TrashPage` | 🔑 |
| `/admin` → `/admin/users` | `AdminLayout` | 🔑 |
| `/admin/users` | `UsersPage` | 🛡️ |
| `/admin/registration` | `RegistrationPage` | 🛡️ |
| `/admin/audit` | `AuditPage` | 🛡️ |
| `/admin/tasks` | `TasksPage` | 🛡️ |
| `*` | 404 | — |

**Оболочка.** `AppShell` = `Sidebar` + `TopBar` + `Outlet`, обёрнутый в провайдеры
`BreadcrumbProvider`, `UploadProvider`, `InfoPanelProvider`. `AdminLayout` —
вложенная вкладочная навигация. Глобальные провайдеры (`main.tsx`):
`ThemeProvider` → `QueryClientProvider` → `TooltipProvider` → `BrowserRouter` →
`App` (с `AuthProvider`).

---

## Страницы

| Страница | Файл | Описание |
|---|---|---|
| Files | `pages/Files.tsx` | Главный браузер: infinite-scroll, grid/list, создание папки, загрузка (файл/папка drag-drop), действия (переименование, перемещение, копирование, удаление, шаринг), фильтр/сортировка, превью, инфо-панель. |
| Login | `pages/Login.tsx` | Форма входа (email/username + пароль). |
| Register | `pages/Register.tsx` | Заявка на регистрацию (одобряет администратор). |
| Shared | `pages/Shared.tsx` | «Доступно мне» — узлы, к которым выдали доступ, с учётом уровня прав. |
| Share | `pages/Share.tsx` | Публичная страница по токену (без auth): просмотр/скачивание, архив папки с опросом, ввод пароля при защите. |
| Trash | `pages/Trash.tsx` | Корзина: восстановление/окончательное удаление, массовые действия. |
| Admin | `pages/admin/*` | `AdminLayout` (вкладки) + `UsersPage`, `RegistrationPage`, `AuditPage`, `TasksPage`, `UserDetailSheet`. |

---

## API-слой

`src/lib/api.ts` — единый axios-инстанс:

- `baseURL: "/api/v1"`, `withCredentials: true` (сессия в httpOnly-cookie).
- **Silent-refresh:** на `401` вызывает `POST /auth/refresh` и повторяет исходный
  запрос; параллельные `401` ставятся в очередь, чтобы не было гонки рефрешей; сам
  `/auth/refresh` из ретрая исключён. При неудаче — событие `auth:session-expired`
  (его слушает `AuthProvider` и разлогинивает).

Каждый домен — отдельный модуль в `src/api/` (`auth`, `users`, `nodes`, `folders`,
`uploads`, `downloads`, `trash`, `permissions`, `public-links`, `quotas`,
`registration`, `tasks`, `audit`, `config`). Методы — тонкие обёртки над
эндпоинтами backend; **полный перечень эндпоинтов с правами доступа — в
[`backend/README.md`](../backend/README.md#api)**.

Типы запросов/ответов — в `src/types/` (по доменам, `common.ts` содержит
`PageResponse<T>` для пагинации).

---

## Состояние и данные

**Серверное состояние — TanStack Query** (`src/lib/query-client.ts`):
`staleTime` 2 мин, `gcTime` 5 мин, retry до 2 раз (кроме `401`). Мутации
оптимистично обновляют кэш папки (`lib/folderCache.ts`:
`insert/remove/updateNodeInFolderCache`), чтобы UI реагировал мгновенно.

**UI-состояние — React Context** (`src/contexts/`):

| Контекст | Назначение |
|---|---|
| `auth` | Текущий пользователь, `login`/`logout`, загрузка профиля, реакция на истечение сессии. |
| `upload` | Очередь загрузок, прогресс, ограничение параллелизма. |
| `breadcrumb` | Хлебные крошки (путь по дереву папок). |
| `infoPanel` | Выбранный элемент для боковой инфо-панели. |

**Тема** — `lib/theme.tsx` (next-themes): класс на `<html>`, хранение в
localStorage; инлайн-скрипт в `index.html` применяет тему до гидратации (без FOUC).

**Кастомные хуки** (`src/hooks/`):

| Хук | Назначение |
|---|---|
| `useFileBrowser` | Infinite query содержимого папки/корня (страницы по 100), крошки, total. |
| `useThumbnails` | Батч-загрузка presigned URL миниатюр (≤100 id), кэш в sessionStorage, опрос «не готовых» с backoff (4→30 с, до 8 раз), пауза на фоне вкладки. Учитывает флаг `previews_enabled`. |
| `useFeatures` | Грузит `GET /config` один раз; отдаёт флаги функциональности (дефолт — всё включено). |
| `useShareBadges` | Лёгкие DISTINCT-запросы id узлов с активной ссылкой и выданным доступом (бейджи). |
| `useSharedWithMe` | Infinite query узлов, к которым выдали доступ. |
| `useQuota` | Квота пользователя + `formatBytes`. |
| `useFolderUpload` | Разбор `webkitRelativePath`, создание недостающих папок, постановка файлов по целевым папкам. |
| `useArchiveDownload` / `useBulkDownload` / `useFolderDownload` | Создание архива с опросом задачи и получением presigned-URL. |

---

## Компоненты

- **`ui/`** — примитивы shadcn/Radix (кнопки, диалоги, меню, тултипы, бейджи,
  скелетоны, прогресс, тосты и т.д.).
- **`files/`** — `FileGrid` (grid/list, выбор, фильтр/сортировка, drag-drop),
  `FileGridItem`/`FileListItem` (карточка/строка с миниатюрой, бейджами доступа,
  действиями), `ShareDialog` (публичная ссылка + выдача доступа пользователю),
  `UploadPanel` (очередь с прогрессом), диалоги переименования/перемещения/
  удаления/создания папки, панели массовых действий и фильтров, `NodeInfoPanel`.
- **`preview/`** — `FilePreviewModal`: изображения, видео, аудио, PDF, текст и
  Markdown; полноэкранный режим, зум, проигрывание и редактирование текста.
  Возможности гейтятся флагами (`file_viewer`, `media_playback`, `file_editing`).
- **`layout/`** — `AppShell` (sidebar + topbar + контент + панели загрузки/инфо),
  `Sidebar` (Файлы / Доступно мне / Корзина / Админ), `TopBar` (крошки, поиск,
  меню пользователя, индикатор загрузки), `ThemeToggle`.
- **`auth/`** — `ProtectedRoute`, `ChangePasswordDialog`.

---

## Ключевые механики

**Multipart-загрузка** (`contexts/upload.tsx`, `hooks/useFolderUpload.ts`):
файл → `POST /uploads/` (сессия) → `POST /uploads/{id}/parts/presigned`
(presigned PUT на части по 8 МБ) → загрузка частей напрямую в MinIO →
`POST /uploads/{id}/parts/{n}/complete` → `POST /uploads/{id}/complete`. Очередь
ограничивает параллелизм (`MAX_CONCURRENT_UPLOADS = 5`), есть ретраи создания
сессии. Папки drag-drop разбираются по `webkitRelativePath` с созданием структуры.

**Файловый браузер**: infinite query, мульти-выбор (Ctrl/Shift), фильтр по типу,
сортировка, переключение grid/list (сохраняется в localStorage), оптимистичные
обновления кэша при create/rename/delete/move.

**Миниатюры**: один батч-запрос на видимые узлы, позитивный кэш в sessionStorage,
короткий кэш для «не готовых» и опрос с экспоненциальным backoff, пауза при
неактивной вкладке.

**Флаги функциональности**: `useFeatures()` читает `GET /config` и прячет
недоступные возможности (миниатюры, просмотрщик, проигрывание, редактирование) —
для слабых/ограниченных серверов. По умолчанию всё включено.

**Публичный доступ** (`pages/Share.tsx`): по токену без авторизации — просмотр,
скачивание, архив папки с опросом, запрос пароля при защите.

---

## Конфигурация и константы

SPA **не требует build-time переменных окружения** — вся конфигурация деплоя
приходит в рантайме из `GET /api/v1/config`. Связь с backend — same-origin через
шлюз nginx (`/api/v1`), в dev — через Vite-proxy (`/api → http://localhost:8000`,
см. `vite.config.ts`). Алиас `@ → src`.

Числовые параметры клиента собраны в `src/lib/constants.ts`:

| Константа | Значение | Назначение |
|---|---|---|
| `UPLOAD_PART_SIZE` | 8 МБ | Размер части multipart (= backend). |
| `MAX_CONCURRENT_UPLOADS` | 5 | Параллельных загрузок end-to-end. |
| `UPLOAD_RETRY_MAX` / `UPLOAD_RETRY_BASE_MS` | 4 / 1500 | Ретраи создания сессии. |
| `ARCHIVE_POLL_MS` / `ARCHIVE_TIMEOUT_MS` | 2000 / 15 мин | Опрос фоновой сборки архива. |
| `THUMBNAIL_URL_TTL_MS` | 12 мин | TTL presigned URL миниатюры в sessionStorage. |
| `THUMBNAIL_NEGATIVE_TTL_MS` | 45 с | Короткий кэш «превью пока нет». |

Уровни доступа для UI — `src/lib/accessLevels.ts`.

---

## Тесты

Vitest + Testing Library + jsdom (`vitest.config.ts`: `environment: "jsdom"`,
`setupFiles: ./tests/setup.ts`). Покрываются страницы, хуки, контексты и
компоненты. Пороги покрытия: **statements/lines/functions 85%, branches 80%**.

```bash
npm test                 # однократный прогон
npm run test:watch       # watch-режим
npm run test:coverage    # отчёт покрытия (./coverage)
```

---

## Docker

[`Dockerfile`](./Dockerfile) — multi-stage: сборка SPA в Node, затем раздача
статики через nginx. [`nginx.conf`](./nginx.conf) этого образа отдаёт `dist/` с
длинным кэшем `/assets/` и history-fallback на `/index.html` (клиентская
маршрутизация). Снаружи стек закрыт общим шлюзом `nginx/` (см. корневой README) —
этот контейнер обслуживает только статику SPA.
