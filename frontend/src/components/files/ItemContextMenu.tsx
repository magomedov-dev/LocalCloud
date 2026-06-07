import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Download,
  Eye,
  FolderInput,
  FolderOpen,
  Info,
  Loader2,
  Palette,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { detectPreviewKind } from "@/components/preview/filePreviewKind";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { RenameDialog } from "./RenameDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { ShareDialog } from "./ShareDialog";
import { FolderColorDialog } from "./FolderColorDialog";
import { MoveDialog } from "./MoveDialog";
import { useFolderDownload } from "@/hooks/useFolderDownload";
import { useInfoPanel } from "@/contexts/infoPanel-context";
import { downloadNodeFile } from "@/lib/download";
import type { NodeListItem } from "@/types/nodes";
import type { SelectOpts } from "./FileGrid";
import type { ReactNode } from "react";

/**
 * Свойства контекстного меню элемента.
 *
 * `item` — файл или папка, для которых открывается меню.
 * `folderQueryKey` используется для обновления кеша текущей папки.
 * `folderColor` — текущий пользовательский цвет папки.
 * `onColorChange` вызывается при изменении или сбросе цвета папки.
 * `isSelected` определяет, выбран ли элемент.
 * `selectedItems` содержит список выбранных элементов для группового удаления.
 * `onSelect` вызывается при открытии меню на невыбранном элементе.
 * `onPreview` открывает предпросмотр файла, если он поддерживается.
 * `children` — элемент, по которому открывается контекстное меню.
 */
interface Props {
  item: NodeListItem;
  folderQueryKey: unknown[];
  folderColor: string | null;
  onColorChange: (color: string | null) => void;
  isSelected?: boolean;
  selectedItems?: NodeListItem[];
  onSelect?: (item: NodeListItem, opts: SelectOpts) => void;
  onPreview?: () => void;
  children: ReactNode;
}

/**
 * Контекстное меню файла или папки.
 *
 * Добавляет к дочернему элементу меню по правому клику с действиями:
 * открыть папку, предпросмотр, скачать, переименовать, переместить,
 * изменить цвет папки, поделиться, открыть информацию и удалить.
 *
 * Если меню открывается на невыбранном элементе, компонент сначала выбирает его.
 * При удалении нескольких выбранных элементов передаёт в диалог весь список выбора.
 */
export function ItemContextMenu({
  item,
  folderQueryKey,
  folderColor,
  onColorChange,
  isSelected,
  selectedItems,
  onSelect,
  onPreview,
  children,
}: Props) {
  const navigate = useNavigate();
  const { openInfo } = useInfoPanel();
  const { downloadFolder, downloading } = useFolderDownload();
  const isFolderDownloading = downloading === item.id;
  const previewKind =
    item.node_type === "file" ? detectPreviewKind(item.name, item.file_mime_type) : null;

  const [renameOpen, setRenameOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [colorOpen, setColorOpen] = useState(false);

  /**
   * Скачивает текущий элемент.
   *
   * Для папки запускает скачивание через `useFolderDownload`,
   * для файла — прямое скачивание через `downloadNodeFile`.
   */
  function handleDownload() {
    if (item.node_type === "folder") {
      downloadFolder(item.id, item.name);
    } else {
      downloadNodeFile(item.id, item.name);
    }
  }

  return (
    <>
      <ContextMenu
        onOpenChange={(open) => {
          if (open && !isSelected) onSelect?.(item, { ctrl: false, shift: false });
        }}
      >
        <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          {item.node_type === "folder" && (
            <>
              <ContextMenuItem onClick={() => navigate(`/files/folders/${item.id}`)}>
                <FolderOpen />
                Открыть
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          )}

          {previewKind && onPreview && (
            <>
              <ContextMenuItem onClick={onPreview}>
                <Eye />
                Просмотр
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          )}

          <ContextMenuItem disabled={isFolderDownloading} onClick={handleDownload}>
            {isFolderDownloading ? <Loader2 className="animate-spin" /> : <Download />}
            Скачать
          </ContextMenuItem>

          <ContextMenuSeparator />

          <ContextMenuItem onClick={() => setRenameOpen(true)}>
            <Pencil />
            Переименовать
          </ContextMenuItem>

          <ContextMenuItem onClick={() => setMoveOpen(true)}>
            <FolderInput />
            Переместить
          </ContextMenuItem>

          {item.node_type === "folder" && (
            <ContextMenuItem onClick={() => setColorOpen(true)}>
              <Palette />
              Цвет папки
            </ContextMenuItem>
          )}

          <ContextMenuItem onClick={() => setShareOpen(true)}>
            <Share2 />
            Поделиться
          </ContextMenuItem>

          <ContextMenuItem onClick={() => openInfo(item)}>
            <Info />
            Информация
          </ContextMenuItem>

          <ContextMenuSeparator />

          <ContextMenuItem
            onClick={() => setDeleteOpen(true)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 />
            Удалить
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      <RenameDialog
        open={renameOpen}
        onOpenChange={setRenameOpen}
        nodeId={item.id}
        currentName={item.name}
        folderQueryKey={folderQueryKey}
      />
      <MoveDialog
        open={moveOpen}
        onOpenChange={setMoveOpen}
        nodeIds={[item.id]}
        label={item.name}
        folderQueryKey={folderQueryKey}
      />
      <DeleteConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        items={isSelected && selectedItems && selectedItems.length > 1 ? selectedItems : [item]}
        folderQueryKey={folderQueryKey}
      />
      <ShareDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        nodeId={item.id}
        nodeName={item.name}
      />
      {item.node_type === "folder" && (
        <FolderColorDialog
          open={colorOpen}
          onOpenChange={setColorOpen}
          nodeId={item.id}
          currentColor={folderColor}
          onColorChange={onColorChange}
        />
      )}
    </>
  );
}
