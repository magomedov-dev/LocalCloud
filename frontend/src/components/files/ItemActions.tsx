import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Copy,
  CopyPlus,
  Download,
  Eye,
  FolderInput,
  Info,
  Loader2,
  MoreVertical,
  Palette,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { detectPreviewKind } from "@/components/preview/filePreviewKind";
import { RenameDialog } from "./RenameDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { ShareDialog } from "./ShareDialog";
import { FolderColorDialog } from "./FolderColorDialog";
import { MoveDialog } from "./MoveDialog";
import { useFolderDownload } from "@/hooks/useFolderDownload";
import { useInfoPanel } from "@/contexts/infoPanel-context";
import { downloadNodeFile } from "@/lib/download";
import { nodesApi } from "@/api/nodes";
import { friendlyError } from "@/lib/errors";
import type { NodeListItem } from "@/types/nodes";
import { type ItemCapabilities, resolveCapabilities } from "./itemCapabilities";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Свойства меню действий элемента.
 *
 * `item` — файл или папка, для которых отображаются действия.
 * `folderQueryKey` используется для обновления кеша текущей папки.
 * `folderColor` — текущий пользовательский цвет папки.
 * `onColorChange` вызывается при изменении или сбросе цвета папки.
 * `onOpenChange` вызывается при открытии или закрытии dropdown-меню.
 * `onPreview` открывает предпросмотр файла, если он поддерживается.
 */
interface Props {
  item: NodeListItem;
  folderQueryKey: unknown[];
  folderColor: string | null;
  onColorChange: (color: string | null) => void;
  onOpenChange?: (open: boolean) => void;
  onPreview?: () => void;
  /**
   * Ограничение действий по выданным правам (для вкладки «Доступно мне»).
   * `undefined` — собственный файл, доступны все действия.
   */
  capabilities?: ItemCapabilities;
}

/**
 * Меню действий для файла или папки.
 *
 * Отображает выпадающее меню с операциями: просмотр, скачивание,
 * переименование, перемещение, выбор цвета папки, шаринг,
 * просмотр информации и удаление.
 *
 * Для файлов пункт предпросмотра показывается только если тип файла поддерживается.
 * Для папок доступно скачивание папки и изменение её цвета.
 */
export function ItemActions({
  item,
  folderQueryKey,
  folderColor,
  onColorChange,
  onOpenChange,
  onPreview,
  capabilities,
}: Props) {
  const caps = resolveCapabilities(capabilities);
  const queryClient = useQueryClient();
  const { downloadFolder, downloading } = useFolderDownload();
  const { openInfo } = useInfoPanel();
  const isFolderDownloading = downloading === item.id;
  const previewKind =
    item.node_type === "file" ? detectPreviewKind(item.name, item.file_mime_type) : null;
  const [menuOpen, setMenuOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [colorOpen, setColorOpen] = useState(false);
  const [duplicating, setDuplicating] = useState(false);

  /**
   * Синхронизирует состояние dropdown-меню
   * и передаёт изменение наружу через `onOpenChange`.
   */
  function handleMenuOpenChange(open: boolean) {
    setMenuOpen(open);
    onOpenChange?.(open);
  }

  /**
   * Дублирует элемент в его текущей папке.
   *
   * Имя копии не передаётся — backend сам добавит суффикс «(копия)».
   * После успеха обновляет кеш текущей папки и квоту.
   */
  async function handleDuplicate() {
    setDuplicating(true);
    try {
      await nodesApi.copy(item.id, { target_parent_id: item.parent_id });
      queryClient.invalidateQueries({ queryKey: folderQueryKey });
      queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
      toast.success("Дублировано");
    } catch (err) {
      toast.error(friendlyError(err, { operation: "copy", name: item.name }));
    } finally {
      setDuplicating(false);
    }
  }

  return (
    <>
      <DropdownMenu open={menuOpen} onOpenChange={handleMenuOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0">
            <MoreVertical className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          {item.node_type === "file" && (
            <>
              {previewKind && onPreview && (
                <DropdownMenuItem onClick={onPreview}>
                  <Eye className="mr-2 h-4 w-4" />
                  Просмотр
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => downloadNodeFile(item.id, item.name)}>
                <Download className="mr-2 h-4 w-4" />
                Скачать
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          {item.node_type === "folder" && (
            <>
              <DropdownMenuItem
                disabled={isFolderDownloading}
                onClick={() => downloadFolder(item.id, item.name)}
              >
                {isFolderDownloading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Download className="mr-2 h-4 w-4" />
                )}
                Скачать
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          {caps.canWrite && (
            <>
              <DropdownMenuItem onClick={() => setRenameOpen(true)}>
                <Pencil className="mr-2 h-4 w-4" />
                Переименовать
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setMoveOpen(true)}>
                <FolderInput className="mr-2 h-4 w-4" />
                Переместить
              </DropdownMenuItem>
              <DropdownMenuItem disabled={duplicating} onClick={handleDuplicate}>
                {duplicating ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <CopyPlus className="mr-2 h-4 w-4" />
                )}
                Дублировать
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setCopyOpen(true)}>
                <Copy className="mr-2 h-4 w-4" />
                Копировать в…
              </DropdownMenuItem>
              {item.node_type === "folder" && (
                <DropdownMenuItem onClick={() => setColorOpen(true)}>
                  <Palette className="mr-2 h-4 w-4" />
                  Цвет папки
                </DropdownMenuItem>
              )}
            </>
          )}
          {caps.canShare && (
            <DropdownMenuItem onClick={() => setShareOpen(true)}>
              <Share2 className="mr-2 h-4 w-4" />
              Поделиться
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => openInfo(item)}>
            <Info className="mr-2 h-4 w-4" />
            Информация
          </DropdownMenuItem>
          {caps.canDelete && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => setDeleteOpen(true)}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Удалить
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

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
      <MoveDialog
        mode="copy"
        open={copyOpen}
        onOpenChange={setCopyOpen}
        nodeIds={[item.id]}
        label={item.name}
        folderQueryKey={folderQueryKey}
      />
      <DeleteConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        items={[item]}
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
