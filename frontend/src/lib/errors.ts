/**
 * Преобразование ошибок API в человекочитаемые сообщения для UI.
 *
 * Backend возвращает ошибки в виде `{ error, message, details }`, где `error` —
 * стабильный машинный код (например `conflict_error`, `quota_exceeded`), а
 * `message` — технический русский текст («узел с таким именем…»). Этот модуль —
 * единая точка, которая по коду ошибки и контексту операции (загрузка,
 * перемещение, переименование и т. д.) подбирает понятное пользователю
 * сообщение.
 */

/**
 * Тип файловой операции, в контексте которой произошла ошибка.
 *
 * Используется, чтобы подобрать формулировку под действие пользователя
 * (например, конфликт имён при загрузке и при перемещении описывается
 * по-разному).
 */
export type FileOperation =
  | "upload"
  | "move"
  | "copy"
  | "rename"
  | "createFolder"
  | "delete"
  | "restore"
  | "download"
  | "generic";

/**
 * Контекст, уточняющий формулировку сообщения об ошибке.
 *
 * Attributes:
 *   operation: Выполняемая операция. По умолчанию `generic`.
 *   name: Имя файла или папки, к которым относится операция, если известно.
 */
export interface FriendlyErrorContext {
  operation?: FileOperation;
  name?: string;
}

/**
 * Разобранные машинно-читаемые поля ошибки.
 *
 * Attributes:
 *   isNetwork: Запрос ушёл, но ответа от сервера не получено (нет сети/таймаут).
 *   status: HTTP-статус ответа, если он был получен.
 *   code: Машинный код ошибки из тела ответа (`error`).
 *   message: Человекочитаемое сообщение от backend (`message`).
 *   details: Структурированные детали ошибки (`details`).
 */
export interface ParsedApiError {
  isNetwork: boolean;
  status?: number;
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
}

/**
 * Ошибка с заранее подготовленным сообщением для пользователя.
 *
 * В отличие от обычных `Error`, текст таких ошибок безопасно показывать в UI
 * как есть — `friendlyError` возвращает их сообщение без переформулирования.
 */
export class UserFacingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UserFacingError";
  }
}

/**
 * Форма тела ответа об ошибке от backend.
 */
interface BackendErrorBody {
  error?: unknown;
  message?: unknown;
  details?: unknown;
}

/**
 * Извлекает машинно-читаемые поля из произвольной ошибки.
 *
 * Распознаёт ошибки axios (по наличию полей `response`/`request`), сетевые сбои
 * без ответа и обычные `Error`.
 *
 * Args:
 *   err: Любая перехваченная ошибка.
 *
 * Returns:
 *   Разобранные поля ошибки.
 */
export function parseApiError(err: unknown): ParsedApiError {
  if (err && typeof err === "object" && ("response" in err || "request" in err)) {
    const e = err as {
      response?: { status?: number; data?: unknown };
      message?: unknown;
    };

    if (!e.response) {
      // Запрос отправлен, но ответа нет — сетевая ошибка или таймаут.
      return { isNetwork: true };
    }

    const data = (e.response.data ?? undefined) as BackendErrorBody | undefined;
    const details =
      data && typeof data.details === "object" && data.details !== null
        ? (data.details as Record<string, unknown>)
        : undefined;

    return {
      isNetwork: false,
      status: typeof e.response.status === "number" ? e.response.status : undefined,
      code: typeof data?.error === "string" ? data.error : undefined,
      message: typeof data?.message === "string" ? data.message : undefined,
      details,
    };
  }

  if (err instanceof Error) {
    return { isNetwork: false, message: err.message };
  }

  return { isNetwork: false };
}

/**
 * Заключает имя в кавычки-ёлочки, если оно задано.
 */
function quote(name?: string): string | undefined {
  return name ? `«${name}»` : undefined;
}

/**
 * Общая формулировка неудачи под конкретную операцию.
 */
function genericMessage(operation: FileOperation, quoted?: string): string {
  switch (operation) {
    case "upload":
      return quoted
        ? `Не удалось загрузить ${quoted}. Попробуйте ещё раз.`
        : "Не удалось загрузить файл. Попробуйте ещё раз.";
    case "move":
      return quoted
        ? `Не удалось переместить ${quoted}. Попробуйте ещё раз.`
        : "Не удалось переместить. Попробуйте ещё раз.";
    case "copy":
      return quoted
        ? `Не удалось скопировать ${quoted}. Попробуйте ещё раз.`
        : "Не удалось скопировать. Попробуйте ещё раз.";
    case "rename":
      return "Не удалось переименовать. Попробуйте ещё раз.";
    case "createFolder":
      return "Не удалось создать папку. Попробуйте ещё раз.";
    case "delete":
      return "Не удалось удалить. Попробуйте ещё раз.";
    case "restore":
      return "Не удалось восстановить. Попробуйте ещё раз.";
    case "download":
      return "Не удалось скачать. Попробуйте ещё раз.";
    default:
      return "Не удалось выполнить действие. Попробуйте ещё раз.";
  }
}

/**
 * Сообщение о конфликте имён под конкретную операцию.
 */
function conflictMessage(operation: FileOperation, quoted?: string): string {
  switch (operation) {
    case "upload":
      return quoted
        ? `Файл ${quoted} уже есть в этой папке. Переименуйте файл или загрузите его в другую папку.`
        : "Файл с таким именем уже есть в этой папке.";
    case "move":
      return quoted
        ? `В папке назначения уже есть элемент с именем ${quoted}.`
        : "В папке назначения уже есть элементы с такими именами.";
    case "copy":
      // При копировании backend сам переименовывает копию, поэтому конфликт
      // имён маловероятен — используем общую формулировку на всякий случай.
      return "Элемент с таким именем уже существует. Будет создана копия.";
    case "rename":
      return quoted
        ? `Имя ${quoted} уже занято в этой папке. Выберите другое.`
        : "Такое имя уже занято в этой папке. Выберите другое.";
    case "createFolder":
      return quoted
        ? `Папка ${quoted} уже существует в этой папке.`
        : "Папка с таким именем уже существует.";
    case "restore":
      return quoted
        ? `Не удалось восстановить ${quoted}: в исходной папке уже есть элемент с таким именем.`
        : "В исходной папке уже есть элемент с таким именем.";
    default:
      return "Элемент с таким именем уже существует.";
  }
}

/**
 * Сообщение «не найдено» под конкретную операцию.
 */
function notFoundMessage(operation: FileOperation): string {
  switch (operation) {
    case "upload":
      return "Папка для загрузки не найдена — возможно, её удалили. Обновите страницу.";
    case "move":
    case "copy":
      return "Папка назначения не найдена — возможно, её удалили. Обновите страницу.";
    case "createFolder":
      return "Папка не найдена — возможно, её удалили. Обновите страницу.";
    case "restore":
      return "Исходная папка не найдена — возможно, её удалили.";
    case "rename":
    case "delete":
      return "Элемент не найден — возможно, его уже удалили. Обновите страницу.";
    default:
      return "Не найдено — возможно, элемент уже удалён. Обновите страницу.";
  }
}

/**
 * Сообщение об отсутствии прав под конкретную операцию.
 */
function permissionMessage(operation: FileOperation): string {
  switch (operation) {
    case "upload":
      return "Недостаточно прав, чтобы загружать файлы в эту папку.";
    case "move":
      return "Недостаточно прав, чтобы переместить элемент сюда.";
    case "copy":
      return "Недостаточно прав, чтобы скопировать сюда.";
    case "rename":
      return "Недостаточно прав, чтобы переименовать этот элемент.";
    case "createFolder":
      return "Недостаточно прав, чтобы создать папку здесь.";
    case "delete":
      return "Недостаточно прав, чтобы удалить этот элемент.";
    case "restore":
      return "Недостаточно прав, чтобы восстановить этот элемент.";
    default:
      return "Недостаточно прав для этого действия.";
  }
}

/**
 * Сообщение о нехватке места под конкретную операцию.
 */
function quotaMessage(operation: FileOperation, quoted?: string): string {
  if (operation === "upload") {
    return quoted
      ? `Недостаточно места, чтобы загрузить ${quoted}. Освободите место в хранилище и попробуйте снова.`
      : "Недостаточно места в хранилище. Освободите место и попробуйте снова.";
  }
  if (operation === "copy") {
    return "Недостаточно места для копирования. Освободите место и попробуйте снова.";
  }
  return "Превышен лимит хранилища. Освободите место и попробуйте снова.";
}

/**
 * Возвращает понятное пользователю сообщение об ошибке.
 *
 * Анализирует машинный код ошибки backend и HTTP-статус, после чего подбирает
 * формулировку с учётом операции и, при наличии, имени файла или папки. Для
 * неизвестных кодов используется общая формулировка под операцию.
 *
 * Args:
 *   err: Перехваченная ошибка (axios, сетевой сбой или обычный `Error`).
 *   context: Операция и имя элемента для уточнения формулировки.
 *
 * Returns:
 *   Готовая к показу строка на русском языке.
 */
export function friendlyError(err: unknown, context: FriendlyErrorContext = {}): string {
  // Сообщения, заранее подготовленные для пользователя, показываем как есть.
  if (err instanceof UserFacingError) return err.message;

  const { operation = "generic", name } = context;
  const quoted = quote(name);
  const parsed = parseApiError(err);

  if (parsed.isNetwork) {
    return "Нет соединения с сервером. Проверьте интернет и попробуйте снова.";
  }

  const { code, status, message } = parsed;

  // Превышение квоты на загрузке приходит кодом `upload_error` с упоминанием
  // квоты в тексте, поэтому распознаём оба варианта.
  const isQuota =
    code === "quota_exceeded" ||
    (code === "upload_error" && /квот|quota/i.test(message ?? ""));

  if (code === "conflict_error" || status === 409) {
    // Конфликт-загрузка с текстом про квоту — это всё-таки нехватка места.
    if (isQuota) return quotaMessage(operation, quoted);
    return conflictMessage(operation, quoted);
  }
  if (isQuota || status === 413) {
    return quotaMessage(operation, quoted);
  }
  if (code === "not_found" || status === 404) {
    return notFoundMessage(operation);
  }
  if (code === "permission_denied" || status === 403) {
    return permissionMessage(operation);
  }
  if (code === "authentication_error" || code === "authorization_error" || status === 401) {
    return "Сессия истекла. Войдите снова, пожалуйста.";
  }
  if (code === "storage_service_error" || code === "storage_error" || code === "database_error") {
    return "Сервис временно недоступен. Подождите немного и попробуйте снова.";
  }
  if (code === "upload_error") {
    return genericMessage("upload", quoted);
  }
  // У ошибок валидации backend обычно присылает понятный конкретный текст.
  if (code === "validation_error" && message) {
    return message;
  }
  if ((typeof status === "number" && status >= 500) || code === "unexpected_error") {
    return "На сервере произошла ошибка. Мы уже разбираемся — попробуйте позже.";
  }

  // Неизвестная ошибка: общая формулировка под операцию, а для операций без
  // контекста — текст backend, если он есть.
  if (operation !== "generic") return genericMessage(operation, quoted);
  return message ?? genericMessage(operation, quoted);
}
