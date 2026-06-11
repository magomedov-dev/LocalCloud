import { useState } from "react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { NodeListItem } from "@/types/nodes";
import type { SelectOpts } from "./FileGrid";
import type { ShareBadge } from "@/hooks/useShareBadges";
import type { ItemCapabilities } from "./itemCapabilities";
import { cn } from "@/lib/utils";
import { thumbnailSupported } from "@/lib/preview";
import { queryClient } from "@/lib/query-client";
import { nodesApi } from "@/api/nodes";
import { FOLDER_PAGE_SIZE, folderQueryKey } from "@/hooks/useFileBrowser";

/**
 * Предзагружает первую страницу содержимого папки при наведении.
 *
 * Форма данных должна совпадать со структурой infinite-query из `useFileBrowser`,
 * иначе прогретая запись кеша будет несовместимой и не сможет переиспользоваться.
 */
function prefetchFolder(id: string) {
  queryClient.prefetchInfiniteQuery({
    queryKey: folderQueryKey(id),
    initialPageParam: 0,
    queryFn: () =>
      nodesApi.content(id, { limit: FOLDER_PAGE_SIZE, offset: 0 }).then((c) => ({
        items: c.items,
        total: c.total,
        folder: c.folder,
        breadcrumbs: c.breadcrumbs,
      })),
    staleTime: 30_000,
  });
}

/**
 * Свойства элемента файловой сетки.
 *
 * `item` — файл или папка для отображения.
 * `mimeType` и `sizeBytes` используются для иконки, превью и метаданных файла.
 * `folderQueryKey` нужен для обновления кеша текущей папки.
 * `isSelected` определяет, выбран ли элемент.
 * `selectedItems` содержит список выбранных элементов для групповых действий.
 * `thumbnailUrl` хранит состояние миниатюры изображения.
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
  /** undefined = still loading | null = failed | string = presigned URL */
  thumbnailUrl?: string | null;
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
 * Элемент файловой сетки.
 *
 * Отображает файл или папку в виде карточки с иконкой, миниатюрой,
 * названием, метаданными, бейджами общего доступа и меню действий.
 *
 * Поддерживает выбор, двойной клик для открытия папки или предпросмотра файла,
 * drag-and-drop перемещение в папку и предзагрузку содержимого папки при наведении.
 */
export function FileGridItem({
  item,
  mimeType,
  sizeBytes,
  folderQueryKey,
  isSelected,
  selectedItems,
  thumbnailUrl,
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
  const hasThumbnail =
    features.previews_enabled &&
    item.node_type === "file" &&
    thumbnailSupported(mimeType ?? item.file_mime_type);
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
            "group relative flex flex-col overflow-hidden rounded-xl text-center",
            "cursor-pointer transition-all duration-150 select-none hover:shadow-md",
            "border-border border",
            isSelected ? "bg-primary/10 ring-primary/50 ring-2" : "bg-card hover:bg-accent",
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
          {/* Область предпросмотра / иконки */}
          <div className="bg-muted/30 relative flex h-24 w-full items-center justify-center">
            {hasThumbnail ? (
              thumbnailUrl === undefined ? (
                <Skeleton className="h-full w-full rounded-none" />
              ) : thumbnailUrl ? (
                <img
                  src={thumbnailUrl}
                  alt={item.name}
                  className="h-full w-full object-cover"
                  draggable={false}
                />
              ) : (
                <FileIcon
                  nodeType={item.node_type}
                  mimeType={mimeType}
                  className="h-10 w-10"
                  color={folderColor}
                />
              )
            ) : (
              <FileIcon
                nodeType={item.node_type}
                mimeType={mimeType}
                className="h-10 w-10"
                color={folderColor}
              />
            )}

            {/* Значки общего доступа */}
            {(badge?.hasPublicLink || badge?.hasSharedAccess) && (
              <div className="absolute bottom-1 left-1 flex items-center gap-0.5">
                {badge.hasPublicLink && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-sky-500 shadow-sm">
                        <Link2 className="h-2.5 w-2.5 text-white" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="right">Публичная ссылка</TooltipContent>
                  </Tooltip>
                )}
                {badge.hasSharedAccess && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-violet-500 shadow-sm">
                        <Users className="h-2.5 w-2.5 text-white" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="right">Доступ выдан</TooltipContent>
                  </Tooltip>
                )}
              </div>
            )}
          </div>

          {/* Имя и метаданные */}
          <div className="flex flex-col gap-0.5 px-2 py-2">
            <span
              className="line-clamp-2 text-xs leading-tight font-medium break-words"
              title={item.name}
            >
              {item.name}
            </span>
            <span className="text-muted-foreground text-[10px]">
              {item.node_type === "file" && sizeBytes != null
                ? formatBytes(sizeBytes)
                : formatDate(item.updated_at)}
            </span>
          </div>

          {/* Кнопка действий */}
          <div
            className={cn(
              "absolute top-1 right-1 transition-opacity",
              menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100",
            )}
            onClick={(e) => e.stopPropagation()}
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
