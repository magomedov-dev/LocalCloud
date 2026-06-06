export const FOLDER_COLORS: { label: string; value: string }[] = [
  { label: "Жёлтый", value: "#eab308" },
  { label: "Оранжевый", value: "#f97316" },
  { label: "Красный", value: "#ef4444" },
  { label: "Розовый", value: "#ec4899" },
  { label: "Фиолетовый", value: "#a855f7" },
  { label: "Синий", value: "#3b82f6" },
  { label: "Голубой", value: "#06b6d4" },
  { label: "Зелёный", value: "#22c55e" },
  { label: "Серый", value: "#6b7280" },
];

const STORAGE_KEY = "folder-colors";

/**
 * Возвращает сохранённый цвет папки.
 *
 * Читает карту цветов из `localStorage` и возвращает цвет,
 * связанный с переданным идентификатором папки.
 *
 * Если цвет не задан или чтение из `localStorage` завершилось ошибкой,
 * возвращает `null`.
 */
export function getFolderColor(nodeId: string): string | null {
  try {
    const map = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, string>;
    return map[nodeId] ?? null;
  } catch {
    return null;
  }
}

/**
 * Сохраняет или сбрасывает цвет папки.
 *
 * Если передан цвет, записывает его в карту цветов в `localStorage`.
 * Если передан `null`, удаляет сохранённый цвет для указанной папки.
 *
 * Ошибки работы с `localStorage` игнорируются.
 */
export function setFolderColor(nodeId: string, color: string | null) {
  try {
    const map = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, string>;
    if (color === null) {
      delete map[nodeId];
    } else {
      map[nodeId] = color;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // игнорируем
  }
}
