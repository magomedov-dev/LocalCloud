import { createElement } from "react";
import {
  Folder,
  File,
  FileImage,
  FileVideo,
  FileAudio,
  FileText,
  FileArchive,
  FileCode,
  FileSpreadsheet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Свойства иконки файла или папки.
 *
 * `nodeType` определяет тип элемента: файл или папка.
 * `mimeType` используется для выбора подходящей иконки файла.
 * `className` добавляет пользовательские CSS-классы.
 * `color` задаёт пользовательский цвет папки.
 */
interface Props {
  nodeType: "file" | "folder";
  mimeType?: string | null;
  className?: string;
  color?: string | null;
}

/**
 * Возвращает иконку файла по MIME-типу.
 *
 * Подбирает специализированные иконки для изображений, видео, аудио,
 * текстовых файлов, PDF, архивов, таблиц и файлов кода.
 * Для неизвестных типов возвращает базовую иконку файла.
 */
function iconForMime(mime: string): LucideIcon {
  if (mime.startsWith("image/")) return FileImage;
  if (mime.startsWith("video/")) return FileVideo;
  if (mime.startsWith("audio/")) return FileAudio;
  if (mime.startsWith("text/")) return FileText;
  if (mime === "application/pdf") return FileText;
  if (
    mime === "application/zip" ||
    mime === "application/x-rar-compressed" ||
    mime === "application/x-7z-compressed" ||
    mime === "application/gzip"
  )
    return FileArchive;
  if (
    mime === "application/vnd.ms-excel" ||
    mime === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  )
    return FileSpreadsheet;
  if (
    mime === "application/json" ||
    mime === "application/xml" ||
    mime.includes("javascript") ||
    mime.includes("typescript")
  )
    return FileCode;
  return File;
}

/**
 * Иконка файла или папки.
 *
 * Для папок отображает иконку `Folder` с жёлтым цветом по умолчанию
 * или с пользовательским цветом, если он передан.
 *
 * Для файлов выбирает иконку на основе MIME-типа.
 */
export function FileIcon({ nodeType, mimeType, className, color }: Props) {
  const cls = cn("shrink-0", className);
  if (nodeType === "folder") {
    return (
      <Folder
        className={cn(cls, !color && "text-yellow-500")}
        style={color ? { color } : undefined}
      />
    );
  }

  const Icon = mimeType ? iconForMime(mimeType) : File;

  return createElement(Icon, { className: cn(cls, "text-muted-foreground") });
}
