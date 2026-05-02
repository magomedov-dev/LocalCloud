import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useLocation } from "react-router-dom";
import { FolderPlus, FolderUp, LayoutGrid, LayoutList, Upload } from "lucide-react";
import { useQueryClient, useIsFetching } from "@tanstack/react-query";
import { toast } from "sonner";
import { useFileBrowser } from "@/hooks/useFileBrowser";
import { useFeatures } from "@/hooks/useFeatures";
import { TopLoadingBar } from "@/components/TopLoadingBar";
import { useBreadcrumb } from "@/contexts/breadcrumb-context";
import { useUpload } from "@/contexts/upload-context";
import { useFolderUpload } from "@/hooks/useFolderUpload";
import { nodesApi } from "@/api/nodes";
import { friendlyError } from "@/lib/errors";
import { FileGrid, type ViewMode, type SelectOpts } from "@/components/files/FileGrid";
import { FileFilterBar } from "@/components/files/FileFilterBar";
import { applyFilter, sortItems, type FileFilter } from "@/components/files/fileListUtils";
import { FileActionBar } from "@/components/files/FileActionBar";
import { FileMultiActionBar } from "@/components/files/FileMultiActionBar";
import { DropZone } from "@/components/files/DropZone";
import { CreateFolderDialog } from "@/components/files/CreateFolderDialog";
import { FilePreviewModal } from "@/components/preview/FilePreviewModal";
import { detectPreviewKind } from "@/components/preview/filePreviewKind";
import { Button } from "@/components/ui/button";
import { useInfoPanel } from "@/contexts/infoPanel-context";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import type { NodeListItem } from "@/types/nodes";

const VIEW_KEY = "file-view-mode";

export function FilesPage() {
  const { nodeId } = useParams<{ nodeId?: string }>();
  const location = useLocation();
  const { data, isLoading, error, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useFileBrowser(nodeId);
  const { setCrumbs } = useBreadcrumb();
  const { enqueue } = useUpload();
  const { uploadFolder } = useFolderUpload();
  const { selectedItem: infoPanelItem, openInfo } = useInfoPanel();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  // webkitdirectory is not in React's type definitions — set it imperatively
  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  const [view, setView] = useState<ViewMode>(() => {
    const saved = localStorage.getItem(VIEW_KEY);
    return saved === "list" ? "list" : "grid";
  });
  const [filter, setFilter] = useState<FileFilter>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const lastSelectedIdRef = useRef<string | null>(null);
  const [spacePreviewItem, setSpacePreviewItem] = useState<NodeListItem | null>(null);

  // Получаем выбранные элементы из актуальных данных запроса, чтобы переименования и обновления отражались немедленно
  const selectedItems = useMemo<NodeListItem[]>(
    () => (data?.items ?? []).filter((i) => selectedIds.has(i.id)),
    [selectedIds, data?.items],
  );

  // Сохраняем ref, чтобы обработчик нажатий клавиш всегда видел актуальный выбор без
  // необходимости перерегистрации при каждом изменении выбора.
  const selectedItemsRef = useRef<NodeListItem[]>([]);
  useEffect(() => {
    selectedItemsRef.current = selectedItems;
  }, [selectedItems]);

  // Ref на флаг просмотрщика, чтобы обработчик пробела видел актуальное значение
  // без перерегистрации слушателя.
  const features = useFeatures();
  const fileViewerEnabledRef = useRef(features.file_viewer_enabled);
  useEffect(() => {
    fileViewerEnabledRef.current = features.file_viewer_enabled;
  }, [features.file_viewer_enabled]);

  // Пробел — быстрый просмотр: открываем предпросмотр, если выбран ровно один файл.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== " ") return;
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (target.isContentEditable) return;
      if (target.closest('[role="dialog"]')) return;
      if (!fileViewerEnabledRef.current) return;

      const items = selectedItemsRef.current;
      if (items.length !== 1) return;
      const item = items[0];
      if (!detectPreviewKind(item.name, item.file_mime_type)) return;

      e.preventDefault();
      setSpacePreviewItem(item);
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // При каждой навигации: предварительно выбираем файл из состояния поиска или сбрасываем выбор.
  // Сброс локального выбора для синхронизации с активным маршрутом — намеренное поведение
  // (ровно один сброс на навигацию).
  useEffect(() => {
    const state = location.state as { selectId?: string } | null;
    const selectId = state?.selectId ?? null;
    setSelectedIds(selectId ? new Set([selectId]) : new Set());
    lastSelectedIdRef.current = selectId;
  }, [location.key, location.state]);

  function toggleView(v: ViewMode) {
    setView(v);
    localStorage.setItem(VIEW_KEY, v);
  }

  const folderQueryKey = useMemo(
    () => (nodeId ? ["nodes", nodeId, "content"] : ["nodes", "root"]),
    [nodeId],
  );

  // Ненавязчивый сигнал "рабочая область обновляется": активируется при каждом
  // folder is (re)fetching — navigation, and every move/delete/rename/upload
  // завершении инвалидации текущего запроса. Ограничен ключом папки, чтобы несвязанные
  // фоновые запросы (миниатюры, значки, предзагрузка при наведении) не активировали его.
  // Пропускаем самую первую загрузку, которая уже показывает скелеты.
  const isFolderFetching = useIsFetching({ queryKey: folderQueryKey }) > 0 && !isLoading;

  const parentNodeId = data?.folder?.node_id ?? null;

  useEffect(() => {
    if (!data?.folder) {
      setCrumbs([{ label: "Файлы" }]);
      return;
    }
    setCrumbs([
      { label: "Файлы", href: "/files" },
      ...data.breadcrumbs.map((b) => ({
        label: b.name,
        href: `/files/folders/${b.id}`,
      })),
      { label: data.folder.node?.name ?? data.folder.node_id },
    ]);
  }, [data, setCrumbs]);

  const handleFiles = useCallback(
    (files: File[]) => {
      enqueue(files, parentNodeId, folderQueryKey);
    },
    [enqueue, parentNodeId, folderQueryKey],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []).filter((f) => f.size > 0);
      if (files.length) handleFiles(files);
      e.target.value = "";
    },
    [handleFiles],
  );

  const handleFolderInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!parentNodeId) return;
      const captured = Array.from(e.target.files ?? []);
      e.target.value = "";
      if (captured.length) uploadFolder(captured, parentNodeId, folderQueryKey);
    },
    [uploadFolder, parentNodeId, folderQueryKey],
  );

  const handleDeselect = useCallback(() => setSelectedIds(new Set()), []);

  // useCallback: стабильная ссылка нужна React.memo элементов списка — иначе
  // каждый рендер страницы пересоздавал бы обработчик и перерисовывал все
  // карточки. Пересоздаётся только при смене данных/фильтра/инфо-панели.
  const handleSelectItem = useCallback(
    (item: NodeListItem, opts: SelectOpts) => {
      const filteredSorted = sortItems(applyFilter(data?.items ?? [], filter));

      if (opts.shift && lastSelectedIdRef.current) {
        const anchorIdx = filteredSorted.findIndex((i) => i.id === lastSelectedIdRef.current);
        const clickIdx = filteredSorted.findIndex((i) => i.id === item.id);
        if (anchorIdx !== -1 && clickIdx !== -1) {
          const [lo, hi] = anchorIdx < clickIdx ? [anchorIdx, clickIdx] : [clickIdx, anchorIdx];
          const rangeIds = filteredSorted.slice(lo, hi + 1).map((i) => i.id);
          setSelectedIds((prev) => {
            const next = new Set(prev);
            for (const id of rangeIds) next.add(id);
            return next;
          });
        }
        return;
      }

      if (opts.ctrl) {
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(item.id)) {
            next.delete(item.id);
          } else {
            next.add(item.id);
            lastSelectedIdRef.current = item.id;
          }
          return next;
        });
        return;
      }

      // Plain click — single select
      lastSelectedIdRef.current = item.id;
      setSelectedIds(new Set([item.id]));
      if (infoPanelItem !== null) {
        openInfo(item);
      }
    },
    [data?.items, filter, infoPanelItem, openInfo],
  );

  const handleDrop = useCallback(
    async (draggedId: string, targetFolderId: string) => {
      // Если перетаскиваемый элемент входит в выборку, перемещаем все выбранные; иначе только перетаскиваемый
      const idsToMove = selectedIds.has(draggedId)
        ? [...selectedIds].filter((id) => id !== targetFolderId)
        : [draggedId];

      if (!idsToMove.length) return;

      const results = await Promise.allSettled(
        idsToMove.map((id) => nodesApi.move(id, { target_parent_id: targetFolderId })),
      );

      const rejected = results.filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      const failed = rejected.length;
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: folderQueryKey });

      if (failed === idsToMove.length) {
        // Все перемещения провалились — показываем конкретную причину.
        const movedName =
          idsToMove.length === 1
            ? data?.items.find((i) => i.id === idsToMove[0])?.name
            : undefined;
        toast.error(
          friendlyError(rejected[0]?.reason, { operation: "move", name: movedName }),
        );
      } else if (failed > 0) {
        toast.error(`Не удалось переместить ${failed} из ${idsToMove.length} элементов`);
      } else {
        toast.success(
          idsToMove.length === 1 ? "Перемещено" : `Перемещено ${idsToMove.length} элементов`,
        );
      }
    },
    [selectedIds, folderQueryKey, queryClient, data],
  );

  const filteredItems = applyFilter(data?.items ?? [], filter);
  const singleSelected = selectedItems.length === 1 ? selectedItems[0] : null;

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-destructive text-sm">Не удалось загрузить файлы.</p>
      </div>
    );
  }

  return (
    <div className="relative flex h-full flex-col gap-3">
      <TopLoadingBar active={isFolderFetching} />

      {/* Панель инструментов */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">
          {data?.folder?.node?.name ?? "Файлы"}
        </h1>
        <div className="flex items-center gap-2">
          {/* Переключатель вида */}
          <div className="flex rounded-lg border p-0.5">
            <Button
              size="icon"
              variant={view === "grid" ? "secondary" : "ghost"}
              className="h-7 w-7"
              onClick={() => toggleView("grid")}
              aria-label="Сетка"
            >
              <LayoutGrid className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="icon"
              variant={view === "list" ? "secondary" : "ghost"}
              className="h-7 w-7"
              onClick={() => toggleView("list")}
              aria-label="Список"
            >
              <LayoutList className="h-3.5 w-3.5" />
            </Button>
          </div>

          <Button
            size="sm"
            variant="outline"
            onClick={() => setCreateOpen(true)}
            title="Новая папка"
          >
            <FolderPlus className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Новая папка</span>
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => folderInputRef.current?.click()}
            disabled={!parentNodeId}
            title={!parentNodeId ? "Перейдите в папку для загрузки" : "Загрузить папку"}
          >
            <FolderUp className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Папку</span>
          </Button>

          <Button
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={!parentNodeId}
            title={!parentNodeId ? "Перейдите в папку для загрузки файлов" : "Загрузить файлы"}
          >
            <Upload className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Загрузить</span>
          </Button>

          {/* Скрытые поля ввода файлов */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleInputChange}
          />
          <input
            ref={folderInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFolderInputChange}
          />
        </div>
      </div>

      {/* Панель фильтров или панель действий */}
      {selectedItems.length > 1 ? (
        <FileMultiActionBar
          items={selectedItems}
          folderQueryKey={folderQueryKey}
          onDeselect={handleDeselect}
        />
      ) : singleSelected ? (
        <FileActionBar
          item={singleSelected}
          folderQueryKey={folderQueryKey}
          onDeselect={handleDeselect}
        />
      ) : (
        <FileFilterBar active={filter} onChange={setFilter} />
      )}

      {/* Контекстное меню рабочей области оборачивает зону перетаскивания */}
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div className="flex-1 overflow-y-auto rounded-lg">
            <DropZone onDrop={handleFiles} disabled={!parentNodeId}>
              <FileGrid
                items={filteredItems}
                isLoading={isLoading}
                folderQueryKey={folderQueryKey}
                view={view}
                selectedIds={selectedIds}
                onSelectItem={handleSelectItem}
                onDeselect={handleDeselect}
                onDrop={handleDrop}
                hasNextPage={hasNextPage}
                isFetchingNextPage={isFetchingNextPage}
                onLoadMore={fetchNextPage}
              />
            </DropZone>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-52">
          <ContextMenuItem onClick={() => setCreateOpen(true)}>
            <FolderPlus />
            Создать папку
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem disabled={!parentNodeId} onClick={() => fileInputRef.current?.click()}>
            <Upload />
            Загрузить файлы
          </ContextMenuItem>
          <ContextMenuItem disabled={!parentNodeId} onClick={() => folderInputRef.current?.click()}>
            <FolderUp />
            Загрузить папку
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      <CreateFolderDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        parentNodeId={parentNodeId}
        currentNodeId={nodeId ?? null}
      />

      {spacePreviewItem && (
        <FilePreviewModal item={spacePreviewItem} open onClose={() => setSpacePreviewItem(null)} />
      )}
    </div>
  );
}
