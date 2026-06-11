import { memo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link2, Users } from "lucide-react";
import { FileIcon } from "./FileIcon";
import { ItemActions } from "./ItemActions";
import { ItemContextMenu } from "./ItemContextMenu";
import { FilePreviewModal } from "@/components/preview/FilePreviewModal";
import { detectPreviewKind } from "@/components/preview/filePreviewKind";
import { getFolderColor, setFolderColor } from "./folderColors";
import { formatBytes } from "@/hooks/useQuota";
import { useFeatures } from "@/hooks/useFeatures";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { NodeListItem } from "@/types/nodes";
import type { SelectOpts } from "./FileGrid";
import type { ShareBadge } from "@/hooks/useShareBadges";
import type { ItemCapabilities } from "./itemCapabilities";
import { cn } from "@/lib/utils";
import { queryClient } from "@/lib/query-client";
import { nodesApi } from "@/api/nodes";

/**
 * Предзагружает содержимое папки при наведении.
 *
 * Прогревает кеш React Query, чтобы переход в папку был быстрее
 * и данные могли отобразиться без лишней задержки.
 */
function prefetchFolder(id: string) {
  queryClient.prefetchQuery({
    queryKey: ["nodes", id, "content"],
    queryFn: () =>
      nodesApi.content(id).then((c) => ({
        items: c.items,
        total: c.total,
        folder: c.folder,
        breadcrumbs: c.breadcrumbs,
      })),
    staleTime: 30_000,
  });
}

/**
 * Свойства элемента файлового списка.
 *
 * `item` — файл или папка для отображения.
 * `mimeType` и `sizeBytes` используются для иконки и метаданных файла.
 * `folderQueryKey` нужен для обновления кеша текущей папки.
 * `isSelected` определяет, выбран ли элемент.
 * `selectedItems` содержит список выбранных элементов для групповых действий.
 * `badge` описывает признаки общего доступа.
 * `onSelect` вызывается при выборе элемента.
 * `onDrop` вызывается при перетаскивании элемента в папку.
 */
interface Props {
  item: NodeListItem;
  mimeType?: string | null;
  sizeBytes?: number | null;
  folderQueryKey: unknown[];
  isSelected?: boolean;
  selectedItems?: NodeListItem[];
  badge?: ShareBadge;
  capabilities?: ItemCapabilities;
  onSelect?: (item: NodeListItem, opts: SelectOpts) => void;
  onDrop?: (draggedId: string, targetFolderId: string) => void;
}

/**
 * Форматирует ISO-дату в короткий русский формат.
 */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Элемент файлового списка.
 *
 * Отображает файл или папку в строковом режиме: иконку, название,
 * бейджи общего доступа, размер, дату изменения и меню действий.
 *
 * Поддерживает выбор, двойной клик для открытия папки или предпросмотра файла,
 * drag-and-drop перемещение в папку и предзагрузку содержимого папки при наведении.
 *
 * Обёрнут в `React.memo`: обновление выбора или бейджей перерисовывает
 * только затронутые строки, а не весь список.
 */
function FileListItemComponent({
  item,
  mimeType,
  sizeBytes,
  folderQueryKey,
  isSelected,
  selectedItems,
  badge,
  capabilities,
  onSelect,
  onDrop,
}: Props) {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [folderColor, setFolderColorState] = useState<string | null>(() =>
    item.node_type === "folder" ? getFolderColor(item.id) : null,
  );

  const features = useFeatures();
  const canPreview =
    features.file_viewer_enabled &&
    item.node_type === "file" &&
    !!detectPreviewKind(item.name, mimeType ?? item.file_mime_type);

  /**
   * Обновляет локальный цвет папки и сохраняет его в хранилище цветов.
   */
  function handleColorChange(color: string | null) {
    setFolderColor(item.id, color);
    setFolderColorState(color);
  }

  /**
   * Обрабатывает выбор элемента.
   *
   * Поддерживает множественный выбор через `Ctrl` / `Cmd`
   * и диапазонный выбор через `Shift`.
   */
  function handleClick(e: React.MouseEvent) {
    e.stopPropagation();
    onSelect?.(item, { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey });
  }

  /**
   * Обрабатывает двойной клик по элементу.
   *
   * Для папки выполняет переход внутрь.
   * Для файла открывает предпросмотр, если тип файла поддерживается.
   */
  function handleDoubleClick() {
    if (item.node_type === "folder") {
      navigate(`/files/folders/${item.id}`);
    } else if (canPreview) {
      setPreviewOpen(true);
    }
  }

  return (
    <>
      <ItemContextMenu
        item={item}
        folderQueryKey={folderQueryKey}
        folderColor={folderColor}
        onColorChange={handleColorChange}
        isSelected={isSelected ?? false}
        selectedItems={selectedItems}
        onSelect={onSelect}
        onPreview={canPreview ? () => setPreviewOpen(true) : undefined}
        capabilities={capabilities}
      >
        <div
          className={cn(
            "group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 select-none",
            "hover:bg-accent transition-colors",
            isSelected && "bg-primary/10 ring-primary/40 ring-1 ring-inset",
            isDragging && "opacity-40",
            isDragOver && "ring-primary bg-primary/10 ring-2",
          )}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData("application/localcloud-node", item.id);
            e.dataTransfer.effectAllowed = "move";
            setIsDragging(true);
          }}
          onDragEnd={() => setIsDragging(false)}
          onDragOver={(e) => {
            if (item.node_type !== "folder") return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = "move";
            if (!isDragOver) setIsDragOver(true);
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragOver(false);
          }}
          onDrop={(e) => {
            if (item.node_type !== "folder") return;
            e.preventDefault();
            e.stopPropagation();
            setIsDragOver(false);
            const draggedId = e.dataTransfer.getData("application/localcloud-node");
            if (draggedId && draggedId !== item.id) onDrop?.(draggedId, item.id);
          }}
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onMouseEnter={() => {
            if (item.node_type === "folder") prefetchFolder(item.id);
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onSelect?.(item, { ctrl: false, shift: false });
          }}
        >
          <FileIcon
            nodeType={item.node_type}
            mimeType={mimeType}
            className="h-4 w-4 shrink-0"
            color={folderColor}
          />

          <span className="min-w-0 flex-1 truncate text-sm font-medium" title={item.name}>
            {item.name}
          </span>

          {/* Значки общего доступа */}
          {(badge?.hasPublicLink || badge?.hasSharedAccess) && (
            <div className="flex shrink-0 items-center gap-1">
              {badge.hasPublicLink && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-sky-500">
                      <Link2 className="h-2 w-2 text-white" />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Публичная ссылка</TooltipContent>
                </Tooltip>
              )}
              {badge.hasSharedAccess && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-violet-500">
                      <Users className="h-2 w-2 text-white" />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Доступ выдан</TooltipContent>
                </Tooltip>
              )}
            </div>
          )}

          <span className="text-muted-foreground shrink-0 text-xs">
            {item.node_type === "file" && sizeBytes != null ? formatBytes(sizeBytes) : ""}
          </span>

          <span className="text-muted-foreground w-24 shrink-0 text-right text-xs">
            {formatDate(item.updated_at)}
          </span>

          <div
            onClick={(e) => e.stopPropagation()}
            className={cn(!menuOpen && "opacity-0 group-hover:opacity-100")}
          >
            <ItemActions
              item={item}
              folderQueryKey={folderQueryKey}
              folderColor={folderColor}
              onColorChange={handleColorChange}
              onOpenChange={setMenuOpen}
              onPreview={canPreview ? () => setPreviewOpen(true) : undefined}
              capabilities={capabilities}
            />
          </div>
        </div>
      </ItemContextMenu>

      {canPreview && (
        <FilePreviewModal
          item={item}
          mimeType={mimeType}
          open={previewOpen}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </>
  );
}

export const FileListItem = memo(FileListItemComponent);
