# LocalCloud — Frontend

SPA на React 19 + TypeScript: файловый менеджер с постраничной подгрузкой, multipart-загрузкой
файлов напрямую в MinIO, публичными ссылками, корзиной и административной панелью.

> Часть монорепозитория [LocalCloud](../README.md). Backend и схема всего стека — в корневом
> `README.md`. История изменений — в [`CHANGELOG.md`](../CHANGELOG.md).

---

## Содержание

1. [Стек и версии](#стек-и-версии)
2. [Архитектура](#архитектура)
3. [Структура проекта](#структура-проекта)
4. [Установка и запуск](#установка-и-запуск)
5. [Конфигурация](#конфигурация)
6. [Маршрутизация](#маршрутизация)
7. [API-слой](#api-слой)
8. [Аутентификация](#аутентификация)
9. [Загрузка файлов](#загрузка-файлов)
10. [Файловый браузер](#файловый-браузер)
11. [Оптимистичные обновления кеша](#оптимистичные-обновления-кеша)
12. [Миниатюры](#миниатюры)
13. [Архивирование и скачивание](#архивирование-и-скачивание)
14. [Контексты](#контексты)
15. [Хуки](#хуки)
16. [Компоненты](#компоненты)
17. [Страницы](#страницы)
18. [Типы](#типы)
19. [Темизация](#темизация)
20. [Константы](#константы)
21. [Разработка](#разработка)

---

## Стек и версии

| Пакет | Версия | Назначение |
|---|---|---|
| **react** | 19.2.6 | UI-фреймворк |
| **typescript** | 6.0.2 | Статическая типизация |
| **vite** | 8.0.12 | Сборщик и dev-сервер |
| **react-router-dom** | 7.15.1 | Клиентская маршрутизация |
| **@tanstack/react-query** | 5.100.14 | Серверное состояние, кеш, пагинация |
| **axios** | 1.16.1 | HTTP-клиент с interceptor-ом для silent refresh |
| **tailwindcss** | 4.3.0 | CSS-фреймворк (v4, конфиг через `@theme`) |
| **@tailwindcss/vite** | 4.3.0 | Интеграция Tailwind с Vite |
| **next-themes** | 0.4.6 | Dark/light-переключение без мигания |
| **sonner** | 2.0.7 | Toast-уведомления |
| **lucide-react** | 1.16.0 | SVG-иконки |
| **react-markdown** | 10.1.0 | Рендеринг Markdown в превью-режиме |
| **remark-gfm** | 4.0.1 | GitHub Flavored Markdown (таблицы, чеклисты) |
| **class-variance-authority** | 0.7.1 | Типизированные варианты компонентов (CVA) |
| **clsx** | 2.1.1 | Условная конкатенация CSS-классов |
| **tailwind-merge** | 3.6.0 | Разрешение конфликтов Tailwind-классов |

**Radix UI primitives** (через shadcn/ui): `avatar`, `context-menu`, `dialog`,
`dropdown-menu`, `label`, `progress`, `separator`, `slot`, `tooltip`.

**Dev**: `eslint` 10.3, `prettier` 3.8, `playwright` 1.60.

---

## Архитектура

```
┌───────────────────────────────────────────────────────────────────┐
│  Browser                                                          │
│                                                                   │
│  React Router                                                     │
│  ├── /login, /register, /forgot-password, /reset-password        │
│  ├── /share/:token            (публичный просмотр, без auth)      │
│  └── ProtectedRoute                                               │
│      └── AppShell                                                 │
│          ├── /files, /files/folders/:nodeId                       │
│          ├── /trash                                               │
│          └── /admin/*                                             │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  React Query  (серверное состояние)                      │    │
│  │  useInfiniteQuery  useQuery  useMutation                 │    │
│  └──────────────────────┬───────────────────────────────────┘    │
│                         │                                         │
│  ┌──────────────────────▼───────────────────────────────────┐    │
│  │  API-слой  src/api/*                                     │    │
│  │  axios  baseURL=/api/v1  +  silent refresh interceptor   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Контексты (React Context)                                        │
│  AuthContext · UploadContext · BreadcrumbContext · InfoPanel      │
└───────────────────────────────────────────────────────────────────┘
                         │
                         ▼ HTTP (proxied /api → :8000)
              ┌──────────────────────┐
              │  FastAPI backend     │
              └──────────────────────┘
```

Серверное состояние живёт полностью в React Query: список файлов, данные папки, квоты,
аудит. Клиентское состояние — очередь загрузок, выбранный в InfoPanel элемент, хлебные крошки —
в React Context. Синхронизировать их вручную не нужно: React Query инвалидирует нужные ключи
после мутаций, а Context-провайдеры просто хранят локальный UI-стейт.

---

## Структура проекта

```
frontend/
├── index.html                  # Шаблон: title, favicon, инлайн-скрипт антивспышки темы
├── public/
│   ├── favicon.svg             # Логотип — облако + стрелка вверх, цвет #D97757
│   └── icons.svg               # SVG-спрайт: иконки соцсетей и UI-иконки
│
├── src/
│   ├── main.tsx                # React root + порядок провайдеров
│   ├── App.tsx                 # Маршруты: публичные / защищённые / административные
│   ├── index.css               # Tailwind @theme: палитра, шрифт, радиусы, scrollbar
│   │
│   ├── api/                    # Axios-обёртки; один файл на ресурс
│   │   ├── index.ts            # Реэкспорт всех API-модулей
│   │   ├── audit.ts
│   │   ├── auth.ts
│   │   ├── downloads.ts
│   │   ├── folders.ts
│   │   ├── nodes.ts
│   │   ├── permissions.ts
│   │   ├── public-links.ts
│   │   ├── quotas.ts
│   │   ├── registration.ts
│   │   ├── tasks.ts
│   │   ├── trash.ts
│   │   ├── uploads.ts
│   │   └── users.ts
│   │
│   ├── lib/
│   │   ├── api.ts              # Глобальный axios-клиент + interceptor для 401
│   │   ├── constants.ts        # Числовые константы (чанки, таймауты, TTL)
│   │   ├── download.ts         # downloadBlobFromUrl
│   │   ├── folderCache.ts      # Оптимистичные обновления InfiniteQuery-кеша
│   │   ├── query-client.ts     # Глобальный QueryClient (staleTime, gcTime, retry)
│   │   ├── theme.tsx           # ThemeProvider (next-themes)
│   │   ├── thumbnailCache.ts   # sessionStorage-кеш для presigned thumbnail URL
│   │   └── utils.ts            # cn() — clsx + tailwind-merge
│   │
│   ├── hooks/
│   │   ├── useArchiveDownload.ts   # Фоновое архивирование + polling + скачивание
│   │   ├── useBulkDownload.ts      # Скачивание набора элементов одним ZIP
│   │   ├── useFileBrowser.ts       # InfiniteQuery содержимого папки
│   │   ├── useFolderDownload.ts    # Скачивание папки ZIP-архивом
│   │   ├── useFolderUpload.ts      # Загрузка папки с сохранением структуры
│   │   ├── useQuota.ts             # useMyQuota() + formatBytes
│   │   ├── useShareBadges.ts       # Индикаторы публичного доступа для узлов
│   │   └── useThumbnails.ts        # Batch-загрузка миниатюр с двухуровневым кешем
│   │
│   ├── contexts/
│   │   ├── auth-context.ts         # Типы + useAuth()
│   │   ├── auth.tsx                # AuthProvider
│   │   ├── breadcrumb-context.ts   # Типы + useBreadcrumb()
│   │   ├── breadcrumb.tsx          # BreadcrumbProvider
│   │   ├── infoPanel-context.ts    # Типы + useInfoPanel()
│   │   ├── infoPanel.tsx           # InfoPanelProvider
│   │   ├── upload-context.ts       # Типы + useUpload()
│   │   └── upload.tsx              # UploadProvider — очередь и выполнение загрузок
│   │
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx        # Основная оболочка: сайдбар + контент
│   │   │   ├── Sidebar.tsx         # Боковая навигация (сворачиваемая)
│   │   │   ├── TopBar.tsx          # Верхняя панель: хлебные крошки, поиск, меню
│   │   │   ├── NavItem.tsx         # Элемент навигации
│   │   │   ├── SearchBar.tsx       # Поисковая строка с выпадающими результатами
│   │   │   ├── ThemeToggle.tsx     # Кнопка переключения темы
│   │   │   └── UserMenu.tsx        # Выпадающее меню профиля пользователя
│   │   │
│   │   ├── files/
│   │   │   ├── FileGrid.tsx            # Основная таблица/сетка с infinite scroll
│   │   │   ├── FileGridItem.tsx        # Карточка файла/папки в grid-виде
│   │   │   ├── FileListItem.tsx        # Строка файла/папки в list-виде
│   │   │   ├── FileIcon.tsx            # MIME-тип → иконка
│   │   │   ├── FileActionBar.tsx       # Тулбар при одиночном выборе
│   │   │   ├── FileMultiActionBar.tsx  # Тулбар при мультивыборе
│   │   │   ├── FileFilterBar.tsx       # Фильтры (все / файлы / папки / тип)
│   │   │   ├── ItemActions.tsx         # Меню действий (используется и в барах, и в контекстном меню)
│   │   │   ├── ItemContextMenu.tsx     # Контекстное меню по правой кнопке мыши
│   │   │   ├── DropZone.tsx            # Зона drag-and-drop
│   │   │   ├── CreateFolderDialog.tsx  # Диалог создания папки
│   │   │   ├── RenameDialog.tsx        # Диалог переименования
│   │   │   ├── DeleteConfirmDialog.tsx # Диалог подтверждения удаления
│   │   │   ├── MoveDialog.tsx          # Диалог перемещения
│   │   │   ├── ShareDialog.tsx         # Диалог управления публичной ссылкой
│   │   │   ├── FolderColorDialog.tsx   # Диалог выбора цвета папки
│   │   │   ├── NodeInfoPanel.tsx       # Боковая панель метаданных выбранного элемента
│   │   │   ├── UploadPanel.tsx         # Прогресс-панель активных загрузок (снизу справа)
│   │   │   ├── fileListUtils.ts        # applyFilter, sortItems
│   │   │   └── folderColors.ts         # getFolderColor, setFolderColor (localStorage)
│   │   │
│   │   ├── preview/
│   │   │   ├── FilePreviewModal.tsx    # Полноэкранный просмотр файлов
│   │   │   └── filePreviewKind.ts      # detectPreviewKind(name, mimeType)
│   │   │
│   │   ├── auth/
│   │   │   ├── ProtectedRoute.tsx      # Охранник маршрутов
│   │   │   └── ChangePasswordDialog.tsx
│   │   │
│   │   ├── ui/                         # shadcn/ui-компоненты (генерируются)
│   │   │   ├── button.tsx, input.tsx, dialog.tsx, sheet.tsx
│   │   │   ├── card.tsx, badge.tsx, avatar.tsx, progress.tsx
│   │   │   ├── breadcrumb.tsx, separator.tsx, skeleton.tsx, tooltip.tsx
│   │   │   ├── checkbox.tsx, context-menu.tsx, dropdown-menu.tsx, label.tsx
│   │   │   ├── button-variants.ts, badge-variants.ts  # CVA-варианты
│   │   │   └── sonner.tsx              # Конфигурированный Toaster
│   │   │
│   │   ├── TopLoadingBar.tsx           # Полоска прогресса при refetch
│   │   └── ErrorBoundary.tsx           # Отлов ошибок рендера
│   │
│   ├── pages/
│   │   ├── Files.tsx                   # Главный файловый браузер
│   │   ├── Trash.tsx                   # Корзина
│   │   ├── Login.tsx
│   │   ├── Register.tsx
│   │   ├── ForgotPassword.tsx
│   │   ├── ResetPassword.tsx
│   │   ├── Share.tsx                   # Публичная страница по токену ссылки
│   │   └── admin/
│   │       ├── AdminLayout.tsx
│   │       ├── UsersPage.tsx
│   │       ├── RegistrationPage.tsx
│   │       ├── AuditPage.tsx
│   │       ├── TasksPage.tsx
│   │       └── UserDetailSheet.tsx     # Выезжающая боковая панель с деталями пользователя
│   │
│   └── types/                          # TypeScript-типы доменных сущностей
│       ├── index.ts                    # Re-export всех типов
│       ├── common.ts                   # PageResponse, PageMeta
│       ├── auth.ts, nodes.ts, files.ts, folders.ts
│       ├── uploads.ts, trash.ts, public-links.ts
│       ├── permissions.ts, quotas.ts, users.ts
│       ├── tasks.ts, audit.ts, registration.ts
│       └── (и т. д.)
│
├── vite.config.ts          # React + Tailwind + alias @ + proxy /api → :8000
├── tsconfig.json           # Project references
├── tsconfig.app.json       # Основной TS-конфиг для src/
├── components.json         # shadcn/ui: стиль, иконки, пути алиасов
└── package.json
```

---

## Установка и запуск

Требуется **Node.js 20+**. Backend должен работать на `http://localhost:8000` — dev-сервер
Vite проксирует на него все запросы по пути `/api`.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

| Команда | Действие |
|---|---|
| `npm run dev` | Dev-сервер с HMR (proxy `/api` → `:8000`) |
| `npm run build` | Проверка типов (`tsc -b`) + production-сборка в `dist/` |
| `npm run preview` | Статический сервер для `dist/` |
| `npm run lint` | ESLint |

### Docker

`frontend/Dockerfile` собирает SPA командой `npm run build` и кладёт `dist/` под `nginx`.
`frontend/nginx.conf` настраивает history-fallback для клиентских маршрутов — без него
прямой переход на `/files/folders/abc` вернул бы 404. Nginx-контейнер фронтенда работает
за шлюзом из корневого `docker-compose.yml`; подробности — в корневом `README.md`.

---

## Конфигурация

### vite.config.ts

```ts
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true }
    }
  }
})
```

В dev-режиме браузер обращается к `http://localhost:5173/api/v1/...`, Vite прозрачно
проксирует их на backend. В production фронтенд и backend живут за одним nginx-шлюзом —
URL не меняется, отдельного адреса API не нужно.

### tsconfig.app.json

- `target: ES2023`, `module: esnext`, `moduleResolution: bundler`
- `jsx: react-jsx`
- `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`,
  `erasableSyntaxOnly`, `verbatimModuleSyntax`
- Path alias `@/*` → `./src/*`

### components.json (shadcn/ui)

```json
{
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": { "baseColor": "neutral", "cssVariables": true },
  "iconLibrary": "lucide",
  "aliases": { "components": "@/components", "utils": "@/lib/utils" }
}
```

---

## Маршрутизация

```
/login                           # Форма входа
/register                        # Регистрация (создаёт заявку)
/forgot-password                 # Запрос сброса пароля
/reset-password                  # Подтверждение сброса по токену
/share/:token                    # Публичная страница по ссылке (без auth)

[ProtectedRoute]
  [AppShell]
    /                            # → redirect /files
    /files                       # Корень файлового дерева
    /files/folders/:nodeId       # Содержимое папки
    /trash                       # Корзина
    /admin                       # → redirect /admin/users (AdminLayout)
    /admin/users                 # Управление пользователями
    /admin/registration          # Заявки на регистрацию
    /admin/audit                 # Журнал аудита
    /admin/tasks                 # Фоновые задачи

/*                               # 404
```

`ProtectedRoute` (`src/components/auth/ProtectedRoute.tsx`): пока `isLoading` — показывает
спиннер; если пользователь не аутентифицирован — `Navigate` на `/login` с сохранением
`state.from`. Отдельного guard по роли `admin` в маршрутизации нет — админ-маршруты вложены в
общий `AppShell` через `AdminLayout`.

Провайдеры. `AuthProvider` оборачивает всё приложение в `src/App.tsx`. Контекстные
провайдеры файловой зоны (`BreadcrumbProvider`, `UploadProvider`, `InfoPanelProvider`)
находятся внутри `AppShell` (`src/components/layout/AppShell.tsx`); там же рендерятся
`UploadPanel` и (при выбранном элементе) `NodeInfoPanel`.

```tsx
// src/App.tsx
<AuthProvider>
  ...маршруты...
  <ProtectedRoute>
    <AppShell>          {/* внутри: Breadcrumb/Upload/InfoPanel-провайдеры, */}
      <Outlet />        {/* страница, UploadPanel, NodeInfoPanel */}
    </AppShell>
  </ProtectedRoute>
</AuthProvider>
```

---

## API-слой

### Глобальный Axios-клиент (`src/lib/api.ts`)

Единственный экземпляр axios с:

```ts
baseURL: "/api/v1"
withCredentials: true         // отправлять cookies в кросс-доменных запросах
headers: { "Content-Type": "application/json" }
```

#### Interceptor для silent refresh

Когда access-токен истекает, все активные запросы получают `401 Unauthorized`. Interceptor
обрабатывает это прозрачно для вызывающего кода:

```
Запрос → 401
│
├─ Уже был повтор (_retry = true)?          → отклонить
├─ Это сам /auth/refresh?                    → отклонить (избегаем бесконечной петли)
│
├─ Уже идёт refresh (isRefreshing = true)?
│  └─ Поставить в очередь (waitQueue)
│     Дождаться окончания refresh → повторить запрос
│
└─ Нет active refresh → начать refresh
   ├─ POST /auth/refresh
   │  ├─ Успех → isRefreshing = false
   │  │          drainQueue() → повторить все ожидавшие запросы
   │  │          Повторить текущий запрос
   │  └─ Ошибка → isRefreshing = false
   │              waitQueue = [] (очередь очищается)
   │              window.dispatchEvent(new Event("auth:session-expired"))
```

> Примечание: событие `auth:session-expired` диспатчится перехватчиком, но отдельного
> слушателя в коде нет; фактический выход выполняется в `AuthProvider.logout()` через
> `window.location.replace("/login")`. При провале refresh очередь ожидавших запросов
> просто очищается (`waitQueue = []`).

Благодаря флагу `isRefreshing` и очереди `waitQueue` при одновременных нескольких 401
отправляется ровно один refresh-запрос, а не несколько.

### Модули API (`src/api/`)

Каждый модуль — объект-синглтон с методами. Все методы возвращают `Promise<T>`, где `T` —
соответствующий TypeScript-тип из `src/types/`.

| Модуль | Ключевые методы |
|---|---|
| **authApi** | `login`, `logout`, `me`, `changePassword`, `requestPasswordReset`, `confirmPasswordReset` |
| **nodesApi** | `list`, `content`, `rename`, `download`, `thumbnail`, `thumbnailsBatch`, `softDelete`, `search`, `move`, `streamUrl` |
| **foldersApi** | `create`, `archive` |
| **uploadsApi** | `create`, `getPresignedParts`, `completePart`, `complete`, `abort` |
| **trashApi** | `list`, `restore`, `purge`, `empty` |
| **publicLinksApi** | `create`, `list`, `listForNode`, `get`, `getPublic`, `download`, `revoke`, `startFolderArchive`, `pollFolderArchive` |
| **quotasApi** | `me`, `getByUserId`, `updateByUserId`, `serverStorage`, `listIncreaseRequests`, `approveIncreaseRequest`, `rejectIncreaseRequest` |
| **usersApi** | `list`, `get`, `block`, `unblock`, `approve`, `reject`, `delete`, `changePassword` |
| **permissionsApi** | `grant`, `listForNode`, `revoke` |
| **tasksApi** | `list`, `get`, `cancel` |
| **downloadsApi** | `archiveUrl`, `bulkArchive` |
| **auditApi** | `list` |
| **registrationApi** | `create`, `list`, `approve`, `reject` |

---

## Аутентификация

### AuthProvider (`src/contexts/auth.tsx`)

При монтировании вызывает `authApi.me()` для восстановления сессии. До завершения запроса
`isLoading = true` — `ProtectedRoute` ждёт, не делая redirect, чтобы не мигать страницей
входа при обычном открытии вкладки.

```ts
interface AuthState {
  user: CurrentUser | null
  isLoading: boolean
  isAuthenticated: boolean     // user !== null && !isLoading
}

interface AuthActions {
  login(data: LoginRequest): Promise<void>
  logout(): Promise<void>
}
```

**Вход:** `authApi.login` → backend устанавливает `access_token` и `refresh_token` в
`HttpOnly`-cookies → клиент сохраняет объект `CurrentUser` в стейте.

**Выход:** `authApi.logout` → backend отзывает refresh-токен, удаляет cookies → клиент
сбрасывает `user` в `null`, вызывает `queryClient.clear()` (очищает весь кеш) и делает
`window.location.replace("/login")` (полная замена истории, кнопка «назад» не вернёт на
защищённую страницу).

**Принудительный выход по истечении сессии:** при неудачном refresh interceptor из
`src/lib/api.ts` диспатчит событие `auth:session-expired` и очищает очередь ожидавших
запросов. Сам выход (очистка состояния и переход на `/login`) выполняется методом
`logout()` в `AuthProvider` через `window.location.replace("/login")`.

---

## Загрузка файлов

### Архитектура

Файлы не проходят через API-сервер — браузер загружает части **напрямую в MinIO** по
presigned PUT URL. API создаёт сессию, раздаёт подписанные URL и финализирует upload, не
касаясь байтов файла.

### Последовательность

```
UploadProvider                   API                         MinIO
      │                           │                            │
      │  POST /uploads/           │                            │
      │  { filename, size_bytes,  │                            │
      │    parts_count, mime_type}│                            │
      │ ────────────────────────→ │                            │
      │                           │  initiate_multipart_upload │
      │                           │ ─────────────────────────→ │
      │ ←─── UploadSession ─────  │                            │
      │                           │                            │
      │  GET /uploads/{id}/       │                            │
      │      presigned-urls       │                            │
      │ ────────────────────────→ │                            │
      │                           │  get_presigned_part_url    │
      │                           │  × N частей                │
      │ ←─── [url1, url2, …] ──── │                            │
      │                           │                            │
      │  PUT url_1                │                            │
      │  (байты части 1)          │                            │
      │ ──────────────────────────────────────────────────────→│
      │ ←──────────────────────────────────────── ETag ────── │
      │                           │                            │
      │  POST /uploads/{id}/parts │                            │
      │  { part_number, etag }    │                            │
      │ ────────────────────────→ │                            │
      │                           │                            │
      │  (× N частей)             │                            │
      │                           │                            │
      │  POST /uploads/{id}/      │                            │
      │       complete            │                            │
      │  { parts: [...] }         │                            │
      │ ────────────────────────→ │                            │
      │                           │  complete_multipart_upload │
      │                           │ ─────────────────────────→ │
      │ ←─── { node_id } ──────── │                            │
```

После получения `node_id` provider немедленно вставляет новый файл в кеш папки
(`insertNodeIntoFolderCache`) — файл появляется в списке без ожидания refetch.
Инвалидация кеша папки и квоты откладывается до завершения **всей пачки** загрузок, чтобы
рефетч не конкурировал с активными PUT-запросами за connection pool браузера.

### Обработка ошибок

При любой ошибке после создания сессии вызывается `uploadsApi.abort(sessionId)`, чтобы
освободить слот активной сессии в квоте. Если вызов abort не удался — ничего страшного:
worker на backend периодически убирает истёкшие сессии.

### Повтор при квоте

Если backend возвращает ошибку с упоминанием `"quota"`, клиент повторяет создание сессии
до `UPLOAD_RETRY_MAX = 4` раз с нарастающей задержкой:

```ts
delay = (attempt + 1) * UPLOAD_RETRY_BASE_MS  // 1500, 3000, 4500, 6000 мс
```

Это нужно потому, что параллельная загрузка могла ещё не освободить свой слот к моменту,
когда следующий файл пробует занять его.

### Параллелизм

Одновременно выполняется не более `MAX_CONCURRENT_UPLOADS = 5` загрузок. Остальные ждут
в очереди и автоматически стартуют по мере завершения активных.

### Загрузка папки (`src/hooks/useFolderUpload.ts`)

При drag-and-drop или выборе через `<input webkitdirectory>`:

1. Из `file.webkitRelativePath` извлекаются все уникальные директории.
2. Директории создаются на backend последовательно (от верхнего уровня вниз),
   `Map<dirPath, nodeId>` обновляется после каждого ответа.
3. Файлы группируются по целевой папке и передаются в `enqueue()`.

---

## Файловый браузер

### useFileBrowser (`src/hooks/useFileBrowser.ts`)

Бесконечная пагинация содержимого папки через `useInfiniteQuery`:

```ts
useFileBrowser(nodeId?: string): {
  data: FileBrowserData | undefined
  isLoading: boolean
  error: Error | null
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage(): Promise<void>
}

interface FileBrowserData {
  items: NodeListItem[]        // объединённые элементы всех загруженных страниц
  total: number                // полное количество в папке (из API)
  folder: FolderRead | null    // текущая папка; null = корень
  breadcrumbs: NodeListItem[]  // путь от корня
}
```

**Ключ запроса:**

```ts
nodeId ? ["nodes", nodeId, "content"] : ["nodes", "root"]
```

Тот же ключ используют все helper-функции из `lib/folderCache.ts` для оптимистичных обновлений.

**Параметры:** `FOLDER_PAGE_SIZE = 100` элементов на страницу. Следующая страница
запрашивается, когда `loadedCount < total && lastPage.items.length > 0`. Дополнительная
проверка на непустую последнюю страницу защищает от бесконечного цикла, если `total`
в API и реальные строки разошлись.

**Refetch-индикатор:** `TopLoadingBar` реагирует на `isFetching` именно папочного ключа —
фоновые запросы (миниатюры, значки, prefetch) его не активируют.

---

## Оптимистичные обновления кеша

`src/lib/folderCache.ts` содержит функции для прямой работы с `InfiniteData<FileBrowserPage>`
в React Query:

```ts
// Добавить элемент в последнюю загруженную страницу
insertNodeIntoFolderCache(qc: QueryClient, key: unknown[], item: NodeListItem): void

// Удалить элементы из всех страниц, уменьшить total
removeNodesFromFolderCache(qc: QueryClient, key: unknown[], ids: string[]): void

// Поверхностно обновить поля элемента во всех страницах
patchNodeInFolderCache(qc: QueryClient, key: unknown[], id: string, patch: Partial<NodeListItem>): void

// Удалить + вернуть rollback-функцию
optimisticallyRemoveNodes(qc, key, ids): () => void

// Обновить + вернуть rollback-функцию
optimisticallyPatchNode(qc, key, id, patch): () => void
```

Типичный паттерн мутации:

```ts
const rollback = optimisticallyRemoveNodes(qc, folderKey, [item.id]);
try {
  await nodesApi.softDelete(item.id);
  // после settle — инвалидировать запрос для синхронизации с сервером
  qc.invalidateQueries({ queryKey: folderKey });
} catch {
  rollback();  // восстановить прежнее состояние
  toast.error("Не удалось удалить файл");
}
```

---

## Миниатюры

`src/hooks/useThumbnails.ts` загружает presigned thumbnail URL батч-запросом и кеширует
их на двух уровнях:

1. **React Query in-memory** — мгновенный доступ внутри сессии; сбрасывается при refresh.
2. **sessionStorage** — переживает обновление страницы; очищается при закрытии вкладки.

TTL обоих уровней — `THUMBNAIL_URL_TTL_MS = 12 минут`. Значение выбрано с запасом ниже
срока жизни presigned URL на backend (1 час), чтобы `<img>` никогда не получал `403`.

Семантика возвращаемого `Map<nodeId, string | null>`:

| Значение | Смысл | Что показывает UI |
|---|---|---|
| Ключ отсутствует | Ещё загружается | Skeleton |
| `null` | Миниатюры нет | Иконка по типу файла |
| `string` (URL) | Готово | `<img src={url}>` |

---

## Архивирование и скачивание

### useArchiveDownload (`src/hooks/useArchiveDownload.ts`)

Универсальный хук для любых операций «создать архив → дождаться → скачать»:

```ts
useArchiveDownload(): {
  run(options: RunOptions): Promise<void>
  active: boolean
  status: string
  progress: number      // 0–100
  activeId: string | null
}

interface RunOptions {
  requestTask(): Promise<string>   // создаёт задачу, возвращает taskId
  filename: string                  // имя архива (без .zip)
  activeId?: string | null          // id элемента (для блокировки повторного нажатия)
  onSuccess?(): void
}
```

Внутренняя логика:

1. Вызвать `requestTask()` → получить `taskId`.
2. Показать live-toast с прогрессом.
3. Polling `tasksApi.get(taskId)` каждые `ARCHIVE_POLL_MS = 2000` мс.
4. Когда статус `completed` — вызвать `downloadsApi.archiveUrl(taskId)` → presigned URL.
5. `downloadBlobFromUrl(url, filename + ".zip")`.
6. Таймаут: `ARCHIVE_TIMEOUT_MS = 15 минут`; по истечении — toast с ошибкой.

### useBulkDownload (`src/hooks/useBulkDownload.ts`)

Оборачивает `useArchiveDownload` для случая нескольких выбранных элементов:
вызывает `downloadsApi.bulkArchive(nodeIds)` как `requestTask`.

### useFolderDownload (`src/hooks/useFolderDownload.ts`)

То же, но для папки: получает содержимое узла через `nodesApi.content(nodeId)`, берёт
`content.folder.id`, затем запускает `foldersApi.archive(content.folder.id, folderName)`.

### downloadBlobFromUrl (`src/lib/download.ts`)

```ts
downloadBlobFromUrl(url: string, filename?: string): void
```

Создаёт временный `<a href={url} download={filename}>`, программно кликает и удаляет из DOM.
Работает с presigned URL и не требует прав на открытие нового окна.

---

## Контексты

Все контексты разделены на два файла: `-context.ts` (типы + хук) и `.tsx` (Provider).
Это позволяет импортировать типы без подтягивания React-зависимостей туда, где они не нужны.

### AuthContext

```ts
interface AuthContextValue {
  user: CurrentUser | null
  isLoading: boolean
  isAuthenticated: boolean
  login(data: LoginRequest): Promise<void>
  logout(): Promise<void>
}
```

### BreadcrumbContext

```ts
interface BreadcrumbContextValue {
  crumbs: BreadcrumbItem[]                  // { label: string; href?: string }
  setCrumbs(crumbs: BreadcrumbItem[]): void
}
```

Страницы вызывают `setCrumbs` в `useEffect` при каждом изменении текущей папки.
`TopBar` читает `crumbs` и отрисовывает `<Breadcrumb>`.

### InfoPanelContext

```ts
interface InfoPanelContextValue {
  selectedItem: NodeListItem | null
  openInfo(item: NodeListItem): void
  closeInfo(): void
}
```

Клик на кнопку «ℹ» в `FileActionBar` вызывает `openInfo`. `NodeInfoPanel` читает
`selectedItem` и рисует метаданные файла/папки в боковой панели.

### UploadContext

```ts
interface UploadContextValue {
  tasks: UploadTask[]
  enqueue(files: File[], parentNodeId: string | null, folderQueryKey: unknown[]): void
  dismiss(id: string): void
  dismissAllDone(): void
}

interface UploadTask {
  id: string
  filename: string
  progress: number        // 0–100
  status: "pending" | "uploading" | "done" | "error"
  error: string | null
}
```

`UploadPanel` отображает `tasks` в правом нижнем углу экрана.

---

## Хуки

| Хук | Сигнатура | Возвращает |
|---|---|---|
| `useFileBrowser` | `(nodeId?: string)` | `{ data, isLoading, error, hasNextPage, isFetchingNextPage, fetchNextPage }` |
| `useThumbnails` | `(items: NodeListItem[])` | `Map<string, string \| null>` |
| `useShareBadges` | `(items: NodeListItem[])` | `Map<string, ShareBadge>` |
| `useMyQuota` | `()` | `UseQueryResult<UserQuota>` |
| `useArchiveDownload` | `()` | `{ run, active, status, progress, activeId }` |
| `useBulkDownload` | `()` | `{ downloadItems, active, status, progress }` |
| `useFolderDownload` | `()` | `{ downloadFolder, downloading }` |
| `useFolderUpload` | `()` | `{ uploadFolder(files, parentNodeId, folderQueryKey) }` |
| `useAuth` | `()` | `AuthContextValue` |
| `useBreadcrumb` | `()` | `BreadcrumbContextValue` |
| `useInfoPanel` | `()` | `InfoPanelContextValue` |
| `useUpload` | `()` | `UploadContextValue` |

**`useShareBadges`** подгружает все активные публичные ссылки пользователя постранично
(до `MAX_LINK_PAGES = 20` страниц по 100 ссылок) и фильтрует их на клиенте по id элементов
текущей папки. Такой подход убирает прежнее ограничение первой страницы и избегает
N×2 запросов (по одному на каждый элемент папки).

**`formatBytes`** экспортируется из `useQuota.ts` как отдельная утилита:

```ts
formatBytes(0)          // "0 Б"
formatBytes(1023)       // "1023 Б"
formatBytes(1024)       // "1 КБ"
formatBytes(1048576)    // "1 МБ"
```

---

## Компоненты

### Файловый браузер

**FileGrid** — главный компонент файлового браузера. Поддерживает два вида (`grid` / `list`),
infinite scroll через `IntersectionObserver` (sentinel-элемент в конце списка), drag-and-drop
для перемещения и загрузки, мультивыбор через Ctrl+Click и Shift+Click.

**FileGridItem / FileListItem** — карточка и строка. Показывают:
- Превью (миниатюра из `useThumbnails` или иконка из `FileIcon`).
- Значки общего доступа (из `useShareBadges`): замок для приватных, иконка ссылки для
  публичных.
- Контекстное меню по правой кнопке мыши (`ItemContextMenu`).
- Drag handle для перемещения.

**FileActionBar / FileMultiActionBar** — тулбары, появляющиеся при выборе одного или
нескольких элементов. Список доступных действий зависит от типа (файл / папка) и прав.

**NodeInfoPanel** — боковая панель с метаданными выбранного элемента: имя, размер, тип,
дата изменения, превью, публичные ссылки, выданные права. На мобильных — выдвижная шторка
(`Sheet`), на десктопе — фиксированный блок справа.

**FilePreviewModal** — полноэкранный просмотр. Поддерживаемые типы определяются через
`detectPreviewKind(name, mimeType)`:

| Тип | Условие |
|---|---|
| `image` | MIME начинается с `image/` |
| `video` | MIME начинается с `video/` |
| `audio` | MIME начинается с `audio/` |
| `pdf` | `application/pdf` |
| `markdown` | `.md`, `.mdx` |
| `text` | Расширение в `TEXT_EXTENSIONS` (`.py`, `.ts`, `.go`, `.json`, `.yaml`, …) |

Для `.ts`-файлов расширение проверяется раньше MIME, чтобы не спутать TypeScript с
`video/mp2t`.

**DropZone** — оборачивает область браузера, принимает `dragover` / `drop`. При drop файлов
вызывает `enqueue()`; при drop папки — `uploadFolder()`.

**MoveDialog** — показывает дерево папок с возможностью навигации. Загружает дочерние папки
лениво по нажатию.

**ShareDialog** — управление публичной ссылкой для одного узла. Отображает существующую
активную ссылку, позволяет создать новую, скопировать URL или отозвать.

### Layout

**AppShell** — сетка `flex` с фиксированным сайдбаром (на десктопе) и вертикальным
overflow-контейнером для контента. На мобильных сайдбар скрыт, открывается через гамбургер
в `TopBar`.

**SearchBar** — при фокусе раскрывается выпадающий список с последними результатами.
Дебаунс 300 мс на ввод, поиск через `nodesApi.search`.

---

## Страницы

| Страница | Маршрут | Описание |
|---|---|---|
| **Files** | `/files`, `/files/folders/:nodeId` | Файловый браузер: переключение вид grid/list, фильтры, загрузка, создание папки, drag-and-drop, предпросмотр по пробелу |
| **Trash** | `/trash` | Список удалённых элементов: восстановление, окончательное удаление, очистка корзины целиком |
| **Login** | `/login` | Форма входа. Если пользователь уже авторизован, сразу перенаправляет на `/files` |
| **Register** | `/register` | Создаёт заявку на регистрацию; после отправки предлагает дождаться одобрения администратором |
| **ForgotPassword** | `/forgot-password` | Ввод email для запроса токена сброса |
| **ResetPassword** | `/reset-password` | Новый пароль + подтверждение. Токен берётся из query-параметра `?token=...` |
| **Share** | `/share/:token` | Публичная страница: показывает имя файла/папки, размер, кнопку скачивания. Для папок — запуск и ожидание архивирования |
| **UsersPage** | `/admin/users` | Таблица пользователей с поиском, фильтрацией по статусу. Массовые действия: блокировка, одобрение, отклонение |
| **RegistrationPage** | `/admin/registration` | Заявки на регистрацию; одобрение создаёт аккаунт, отклонение указывает причину |
| **AuditPage** | `/admin/audit` | Журнал событий с фильтрами по действию, ресурсу, пользователю, датам |
| **TasksPage** | `/admin/tasks` | Таблица фоновых задач worker'а; можно отменить активную задачу |
| **UserDetailSheet** | `(боковая панель)` | Детали пользователя: статус, квота, последние действия, управление |

**Files** — самая сложная страница. Ключевые детали:

- Выбор хранится в локальном `useState`, но синхронизируется с актуальными данными
  InfiniteQuery после каждой мутации (чтобы переименование сразу отразилось в InfoPanel).
- Клавиша `Space` открывает `FilePreviewModal`, если выбран ровно один предпросмотриваемый файл.
- При перетаскивании: если перетаскиваемый элемент входит в текущий выбор — перемещается
  весь выбор; если нет — только перетаскиваемый.
- `TopLoadingBar` активируется на `isFetching` именно текущего папочного ключа, игнорируя
  фоновые запросы.

---

## Типы

Все TypeScript-типы — в `src/types/`. Экспортируются из `index.ts`.

```ts
// Пагинация (types/common.ts)
interface PageMeta {
  limit: number; offset: number; total: number; count: number
  has_next: boolean; has_previous: boolean; page: number; pages: number
}
interface PageResponse<T> { items: T[]; meta: PageMeta }

// Файловая система (types/nodes.ts)
type NodeType = "file" | "folder"
type NodeVisibility = "private" | "shared" | "public"

interface NodeListItem {
  id: string; owner_id: string; parent_id: string | null
  name: string; node_type: NodeType; visibility: NodeVisibility
  path: string; depth: number
  created_at: string; updated_at: string
  is_deleted: boolean
  file_size_bytes?: number; file_mime_type?: string
}

// Аутентификация (types/auth.ts)
interface LoginRequest { email_or_username: string; password: string }
interface CurrentUser { id: string; email: string; username: string; roles: string[] }

// Загрузка (types/uploads.ts)
interface UploadSessionCreateRequest {
  parent_node_id: string | null; filename: string
  file_size_bytes: number; parts_count: number
  mime_type: string; part_size_bytes: number
}
interface PresignedPartsResponse {
  parts: Array<{ part_number: number; url: string; headers: Record<string, string> }>
}
```

---

## Темизация

### Предотвращение мигания (FOUC)

В `index.html` перед загрузкой JS встроен инлайн-скрипт, который читает `localStorage.theme`
и сразу добавляет класс `dark` или `light` на `<html>`. К моменту рендера React тема уже
применена — страница не мигает при загрузке.

### ThemeProvider (`src/lib/theme.tsx`)

Обёртка над `next-themes`:

```ts
<NextThemesProvider
  attribute="class"         // переключение через класс на <html>
  defaultTheme="system"     // авто по системной теме
  themes={["light", "dark"]}
  storageKey="theme"        // ключ в localStorage
>
```

`ThemeToggle` вызывает `useTheme().setTheme(next)` — переключает класс и сохраняет выбор.

### Палитра (`src/index.css`)

Tailwind v4 использует `@theme`-директиву вместо `tailwind.config.js`. CSS-переменные имеют
префикс `--color-*`. Тёмная тема — значения по умолчанию в `@theme`; светлая тема
переопределяется селектором `html.light`:

**Тёмная тема:**

| Переменная | Значение | Использование |
|---|---|---|
| `--color-background` | `#1f1f1e` | Основной фон |
| `--color-foreground` | `#f0f0f0` | Основной текст |
| `--color-primary` | `#d97757` | Акцент (оранжевый) |
| `--color-destructive` | `#d95f5f` | Опасные действия |
| `--color-panel` | `#2c2c2a` | Фон сайдбара/топбара |
| `--color-border` | `#3b3b37` | Цвет рамок |

**Светлая тема (`html.light`):**

| Переменная | Значение |
|---|---|
| `--color-background` | `#f8f8f6` |
| `--color-foreground` | `#373734` |
| `--color-panel` | `#ffffff` |
| `--color-border` | `#d7d7d4` |

Радиусы: `--radius-sm: 5px`, `--radius-md: 8px`, `--radius-lg: 12px` (а также `--radius` 7px,
`--radius-xl` 16px, `--radius-2xl` 20px, `--radius-3xl` 24px, `--radius-full`).
Шрифт: DM Sans с системным fallback.
Кастомный брейкпоинт `xs: 480px` добавлен к стандартным Tailwind.

---

## Константы

**`src/lib/constants.ts`:**

| Константа | Значение | Назначение |
|---|---|---|
| `UPLOAD_PART_SIZE` | `8 × 1024 × 1024` (8 МБ) | Размер одной части multipart upload; совпадает с настройкой backend |
| `MAX_CONCURRENT_UPLOADS` | `5` | Максимум одновременных end-to-end загрузок; контролирует нагрузку на DB-пул и MinIO |
| `UPLOAD_RETRY_MAX` | `4` | Максимум повторов создания сессии при ошибке квоты |
| `UPLOAD_RETRY_BASE_MS` | `1500` | Базовая задержка повтора: `(attempt + 1) × 1500` мс |
| `ARCHIVE_POLL_MS` | `2000` | Интервал polling при ожидании архива |
| `ARCHIVE_TIMEOUT_MS` | `15 × 60 × 1000` (15 мин) | Максимальное время ожидания архива |
| `THUMBNAIL_URL_TTL_MS` | `12 × 60 × 1000` (12 мин) | TTL presigned thumbnail URL в sessionStorage |

**`src/lib/query-client.ts`:**

| Настройка | Значение | Назначение |
|---|---|---|
| `staleTime` | `2 × 60 × 1000` (2 мин) | Данные считаются свежими 2 минуты; нет лишних refetch при навигации |
| `gcTime` | `5 × 60 × 1000` (5 мин) | Неактивный кеш хранится 5 минут |
| `retry` | функция | Повтор до 2 раз на любой ошибке, кроме 401 (им управляет interceptor) |

---

## Разработка

### Запуск

```bash
npm install
npm run dev     # http://localhost:5173, hot reload, прокси /api → :8000
```

### Линт и форматирование

```bash
npm run lint              # ESLint
npx prettier --write .    # форматирование
```

### Добавление shadcn-компонента

```bash
npx shadcn@latest add <component>
# Пример:
npx shadcn@latest add table
```

Компоненты добавляются в `src/components/ui/` и сразу доступны через `@/components/ui/...`.

### Добавление нового API-модуля

1. Создать `src/api/<resource>.ts` по образцу существующих (объект с методами, типы из
   `src/types/`).
2. Добавить тип запроса/ответа в `src/types/<resource>.ts`.
3. Экспортировать из `src/types/index.ts`.

### Добавление нового маршрута

1. Создать страницу в `src/pages/`.
2. Добавить `<Route>` в `src/App.tsx` — внутри `ProtectedRoute`/`AppShell` (для защищённых
   страниц) или вне его (для публичных).
