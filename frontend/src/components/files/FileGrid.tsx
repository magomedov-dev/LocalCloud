import { useEffect, useRef } from "react";
import { Folder as FolderIcon, Loader2 } from "lucide-react";
import { FileGridItem } from "./FileGridItem";
import { FileListItem } from "./FileListItem";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useThumbnails } from "@/hooks/useThumbnails";
import { useFeatures } from "@/hooks/useFeatures";
import { useShareBadges } from "@/hooks/useShareBadges";
import type { NodeListItem } from "@/types/nodes";
import type { ItemCapabilities } from "./itemCapabilities";
import { sortItems } from "./fileListUtils";

export type ViewMode = "grid" | "list";

export interface SelectOpts {
  ctrl: boolean;
  shift: boolean;
}

/**
 * Свойства компонента списка файлов.
 *
 * `items` — элементы для отображения.
 * `isLoading` включает состояние загрузки.
 * `folderQueryKey` используется дочерними элементами для обновления кеша папки.
 * `view` определяет режим отображения: сетка или список.
 * `selectedIds` хранит идентификаторы выбранных элементов.
 * `onSelectItem` вызывается при выборе элемента.
 * `onDeselect` вызывается при снятии выбора.
 * `onDrop` вызывается при перетаскивании элемента в папку.
 * `hasNextPage`, `isFetchingNextPage` и `onLoadMore` отвечают за пагинацию.
 */
interface Props {
  items: NodeListItem[];
  isLoading: boolean;
  folderQueryKey: unknown[];
  view: ViewMode;
  selectedIds?: Set<string>;
  onSelectItem?: (item: NodeListItem, opts: SelectOpts) => void;
  onDeselect?: () => void;
  onDrop?: (draggedId: string, targetFolderId: string) => void;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  onLoadMore?: () => void;
  /**
   * Возвращает ограничение действий для элемента (вкладка «Доступно мне»).
   * Если не задано — все действия доступны (собственные файлы).
   */
  capabilitiesFor?: (item: NodeListItem) => ItemCapabilities | undefined;
}

/**
 * Пустое состояние папки.
 *
 * Отображается, когда в текущей папке нет файлов и подпапок.
 */
function EmptyState() {
  return (
    <div className="text-muted-foreground flex flex-col items-center justify-center gap-3 py-20">
      <FolderIcon className="h-12 w-12 opacity-30" />
      <p className="text-sm">Папка пуста</p>
    </div>
  );
}

/**
 * Skeleton-состояние списка файлов.
 *
 * Отображает разные placeholder-элементы для режима списка и сетки.
 */
function LoadingGrid({ view }: { view: ViewMode }) {
  if (view === "list") {
    return (
      <div className="flex flex-col gap-1">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-9 rounded-lg" />
        ))}
      </div>
    );
  }
  return (
    <div
      className="grid gap-3"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}
    >
      {Array.from({ length: 12 }).map((_, i) => (
        <Skeleton key={i} className="h-27 rounded-xl" />
      ))}
    </div>
  );
}

/**
 * Находит ближайшего прокручиваемого родителя.
 *
 * Используется для `IntersectionObserver`, чтобы отслеживать появление
 * sentinel-элемента внутри внутреннего scroll-контейнера,
 * а не относительно окна браузера.
 */
function getScrollParent(node: HTMLElement | null): HTMLElement | null {
  let cur = node?.parentElement ?? null;
  while (cur) {
    const oy = getComputedStyle(cur).overflowY;
    if (oy === "auto" || oy === "scroll") return cur;
    cur = cur.parentElement;
  }
  return null;
}

/**
 * Нижняя часть списка для подгрузки следующей страницы.
 *
 * Автоматически вызывает `onLoadMore`, когда sentinel попадает в область видимости.
 * Также отображает кнопку ручной подгрузки или индикатор загрузки.
 */
function LoadMoreFooter({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  /**
   * Подключает `IntersectionObserver` для автоматической подгрузки страниц.
   *
   * Observer пересоздаётся после каждой загрузки, чтобы sentinel,
   * который всё ещё виден на экране, мог продолжить подгружать данные.
   */
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage || !onLoadMore) return;
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) onLoadMore();
      },
      { root: getScrollParent(el), rootMargin: "300px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, onLoadMore]);

  if (!hasNextPage && !isFetchingNextPage) return null;

  return (
    <div ref={ref} className="flex justify-center py-4" onClick={(e) => e.stopPropagation()}>
      {isFetchingNextPage ? (
        <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
      ) : (
        <Button variant="outline" size="sm" onClick={onLoadMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}

/**
 * Список файлов и папок.
 *
 * Поддерживает два режима отображения: сетку и список.
 * Показывает skeleton во время загрузки, пустое состояние при отсутствии элементов,
 * сортирует элементы перед выводом и передаёт дочерним компонентам данные выбора,
 * миниатюры, бейджи доступа и drag-and-drop обработчики.
 *
 * Для больших списков поддерживает подгрузку следующей страницы.
 */
export function FileGrid({
  items,
  isLoading,
  folderQueryKey,
  view,
  selectedIds,
  onSelectItem,
  onDeselect,
  onDrop,
  hasNextPage = false,
  isFetchingNextPage = false,
  onLoadMore,
  capabilitiesFor,
}: Props) {
  const features = useFeatures();
  const thumbnails = useThumbnails(items, features.previews_enabled);
  const badges = useShareBadges(items);

  if (isLoading) return <LoadingGrid view={view} />;
  if (!items.length) return <EmptyState />;

  const sorted = sortItems(items);
  const selectedItems = selectedIds ? items.filter((i) => selectedIds.has(i.id)) : [];

  const footer = (
    <LoadMoreFooter
      hasNextPage={hasNextPage}
      isFetchingNextPage={isFetchingNextPage}
      onLoadMore={onLoadMore}
    />
  );

  if (view === "list") {
    return (
      <div className="flex flex-col" onClick={onDeselect}>
        {/* Строка заголовка */}
        <div className="text-muted-foreground flex items-center gap-3 border-b px-3 pb-1.5 text-xs">
          <span className="h-4 w-4 shrink-0" />
          <span className="flex-1">Название</span>
          <span className="shrink-0">Размер</span>
          <span className="w-24 shrink-0 text-right">Изменён</span>
          <span className="h-6 w-6 shrink-0" />
        </div>
        <div className="flex flex-col gap-0.5 px-1 pt-1 pb-1">
          {sorted.map((item) => (
            <FileListItem
              key={item.id}
              item={item}
              folderQueryKey={folderQueryKey}
              mimeType={item.file_mime_type}
              sizeBytes={item.file_size_bytes}
              isSelected={selectedIds?.has(item.id) ?? false}
              selectedItems={selectedItems}
              badge={badges.get(item.id)}
              capabilities={capabilitiesFor?.(item)}
              onSelect={onSelectItem}
              onDrop={onDrop}
            />
          ))}
        </div>
        {footer}
      </div>
    );
  }

  return (
    <div onClick={onDeselect}>
      <div
        className="grid gap-3 p-1"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}
      >
        {sorted.map((item) => (
          <FileGridItem
            key={item.id}
            item={item}
            folderQueryKey={folderQueryKey}
            mimeType={item.file_mime_type}
            sizeBytes={item.file_size_bytes}
            isSelected={selectedIds?.has(item.id) ?? false}
            selectedItems={selectedItems}
            thumbnailUrl={thumbnails.get(item.id)}
            badge={badges.get(item.id)}
            capabilities={capabilitiesFor?.(item)}
            onSelect={onSelectItem}
            onDrop={onDrop}
          />
        ))}
      </div>
      {footer}
    </div>
  );
}
