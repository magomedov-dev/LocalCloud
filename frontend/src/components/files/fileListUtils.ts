import type { NodeListItem } from "@/types/nodes";

export type FileFilter = "all" | "folder" | "image" | "document" | "video" | "audio" | "archive";

/**
 * Применяет фильтр к списку файлов и папок.
 *
 * Возвращает только те элементы, которые соответствуют выбранному типу:
 * все элементы, папки, изображения, документы, видео, аудио или архивы.
 */
export function applyFilter(items: NodeListItem[], filter: FileFilter): NodeListItem[] {
  if (filter === "all") return items;
  if (filter === "folder") return items.filter((i) => i.node_type === "folder");
  if (filter === "image") return items.filter((i) => i.file_mime_type?.startsWith("image/"));
  if (filter === "document") {
    return items.filter((i) => {
      const m = i.file_mime_type ?? "";
      return (
        m.startsWith("text/") ||
        m === "application/pdf" ||
        m.includes("msword") ||
        m.includes("ms-excel") ||
        m.includes("ms-powerpoint") ||
        m.includes("officedocument")
      );
    });
  }
  if (filter === "video") return items.filter((i) => i.file_mime_type?.startsWith("video/"));
  if (filter === "audio") return items.filter((i) => i.file_mime_type?.startsWith("audio/"));
  if (filter === "archive") {
    return items.filter((i) => {
      const m = i.file_mime_type ?? "";
      return (
        m.includes("zip") ||
        m.includes("rar") ||
        m.includes("7z") ||
        m.includes("gzip") ||
        m.includes("tar")
      );
    });
  }
  return items;
}

/**
 * Сортирует список файлов и папок.
 *
 * Папки всегда отображаются перед файлами.
 * Элементы одного типа сортируются по имени с учётом русской локали.
 */
export function sortItems(items: NodeListItem[]): NodeListItem[] {
  return [...items].sort((a, b) => {
    if (a.node_type !== b.node_type) return a.node_type === "folder" ? -1 : 1;
    return a.name.localeCompare(b.name, "ru");
  });
}
