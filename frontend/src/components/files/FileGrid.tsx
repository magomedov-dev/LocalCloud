import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
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

// Порог виртуализации: маленькие списки рендерятся целиком (без накладных
// расходов на измерения), большие — виртуализированно, только видимые строки.
const VIRTUALIZE_FROM = 60;
// Минимальная ширина ячейки и зазор сетки — согласованы с CSS ниже.
const GRID_CELL_MIN_PX = 130;
const GRID_GAP_PX = 12;
// Оценки высоты строк до первого измерения; точная высота снимается
// measureElement'ом виртуализатора.
const GRID_ROW_ESTIMATE_PX = 160;
const LIST_ROW_ESTIMATE_PX = 40;

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

/** Делит массив на части не больше `size`. */
function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
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
 * Используется виртуализатором и `IntersectionObserver`, чтобы работать
 * относительно внутреннего scroll-контейнера, а не окна браузера.
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
 * Большие списки (свыше `VIRTUALIZE_FROM` элементов) рендерятся
 * виртуализированно: в DOM присутствуют только видимые строки, и миниатюры
 * запрашиваются только для видимых элементов — папка на тысячи файлов не
 * создаёт тысяч DOM-узлов и батч-запросов. Также поддерживает подгрузку
 * следующей страницы.
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
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null);
  const [gridWidth, setGridWidth] = useState(0);
  const [scrollMargin, setScrollMargin] = useState(0);

  // Стабильные ссылки для React.memo дочерних элементов: пересчитываются
  // только при изменении списка/выбора, а не на каждом рендере (иначе каждое
  // обновление миниатюр перерисовывало бы все элементы).
  const sorted = useMemo(() => sortItems(items), [items]);
  const selectedItems = useMemo(
    () => (selectedIds ? items.filter((i) => selectedIds.has(i.id)) : []),
    [items, selectedIds],
  );
  const capabilitiesMap = useMemo(
    () => new Map(items.map((i) => [i.id, capabilitiesFor?.(i)])),
    [items, capabilitiesFor],
  );

  const virtualize = sorted.length > VIRTUALIZE_FROM;

  // Scroll-контейнер и ширина сетки определяются после монтирования; ширина
  // отслеживается ResizeObserver'ом для пересчёта числа колонок.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setScrollEl(
      getScrollParent(el) ?? (document.scrollingElement as HTMLElement | null),
    );
    setGridWidth(el.clientWidth);
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (typeof width === "number") setGridWidth(width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [virtualize, view, isLoading]);

  // Отступ списка от начала scroll-контейнера (заголовки страницы и т.п.):
  // виртуализатор должен учитывать его при расчёте видимого диапазона.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !scrollEl) return;
    const cRect = el.getBoundingClientRect();
    const sRect = scrollEl.getBoundingClientRect();
    setScrollMargin(Math.max(0, cRect.top - sRect.top + scrollEl.scrollTop));
  }, [scrollEl, virtualize, view]);

  const columns =
    view === "grid"
      ? Math.max(
          1,
          Math.floor((gridWidth + GRID_GAP_PX) / (GRID_CELL_MIN_PX + GRID_GAP_PX)),
        )
      : 1;
  const rows = useMemo(() => chunk(sorted, columns), [sorted, columns]);

  const virtualizer = useVirtualizer({
    count: virtualize ? rows.length : 0,
    getScrollElement: () => scrollEl,
    estimateSize: () =>
      view === "grid" ? GRID_ROW_ESTIMATE_PX : LIST_ROW_ESTIMATE_PX,
    overscan: 4,
    scrollMargin,
    // До первого измерения (и в средах без ResizeObserver) виртуализатор
    // использует этот прямоугольник — первый экран рендерится сразу.
    initialRect: { width: 1024, height: 800 },
  });
  const virtualRows = virtualize ? virtualizer.getVirtualItems() : [];

  // Миниатюры нужны только сетке (список их не показывает) и только для
  // видимых строк при виртуализации — невидимые элементы не запрашиваются.
  const visibleRangeKey = virtualRows.length
    ? `${virtualRows[0].index}:${virtualRows[virtualRows.length - 1].index}`
    : "";
  const thumbnailItems = useMemo(() => {
    if (view !== "grid") return [];
    if (!virtualize) return sorted;
    return virtualRows.flatMap((row) => rows[row.index] ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- virtualRows нестабилен по ссылке; диапазон кодируется visibleRangeKey
  }, [view, virtualize, sorted, rows, visibleRangeKey]);
  const thumbnails = useThumbnails(thumbnailItems, features.previews_enabled);
  const badges = useShareBadges(items);

  if (isLoading) return <LoadingGrid view={view} />;
  if (!items.length) return <EmptyState />;

  const renderGridItem = (item: NodeListItem) => (
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
      capabilities={capabilitiesMap.get(item.id)}
      onSelect={onSelectItem}
      onDrop={onDrop}
    />
  );

  const renderListItem = (item: NodeListItem) => (
    <FileListItem
      key={item.id}
      item={item}
      folderQueryKey={folderQueryKey}
      mimeType={item.file_mime_type}
      sizeBytes={item.file_size_bytes}
      isSelected={selectedIds?.has(item.id) ?? false}
      selectedItems={selectedItems}
      badge={badges.get(item.id)}
      capabilities={capabilitiesMap.get(item.id)}
      onSelect={onSelectItem}
      onDrop={onDrop}
    />
  );

  const footer = (
    <LoadMoreFooter
      hasNextPage={hasNextPage}
      isFetchingNextPage={isFetchingNextPage}
      onLoadMore={onLoadMore}
    />
  );

  // Виртуализированное тело: абсолютное позиционирование видимых строк внутри
  // контейнера полной высоты. Высота строк уточняется measureElement'ом.
  const virtualBody = (
    <div
      ref={containerRef}
      style={{ height: virtualizer.getTotalSize(), position: "relative" }}
    >
      {virtualRows.map((row) => (
        <div
          key={row.key}
          ref={(el) => {
            // Измеряем только элементы с реальной высотой: в средах без
            // layout (jsdom) высота 0, и измерение зациклило бы пересчёт.
            if (el && el.getBoundingClientRect().height > 0) {
              virtualizer.measureElement(el);
            }
          }}
          data-index={row.index}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            transform: `translateY(${row.start - scrollMargin}px)`,
          }}
        >
          {view === "grid" ? (
            <div
              className="grid px-1 pb-3"
              style={{
                gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                gap: GRID_GAP_PX,
              }}
            >
              {(rows[row.index] ?? []).map(renderGridItem)}
            </div>
          ) : (
            <div className="flex flex-col px-1 pb-0.5">
              {(rows[row.index] ?? []).map(renderListItem)}
            </div>
          )}
        </div>
      ))}
    </div>
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
        {virtualize ? (
          <div className="pt-1">{virtualBody}</div>
        ) : (
          <div ref={containerRef} className="flex flex-col gap-0.5 px-1 pt-1 pb-1">
            {sorted.map(renderListItem)}
          </div>
        )}
        {footer}
      </div>
    );
  }

  return (
    <div onClick={onDeselect}>
      {virtualize ? (
        <div className="pt-1">{virtualBody}</div>
      ) : (
        <div
          ref={containerRef}
          className="grid gap-3 p-1"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}
        >
          {sorted.map(renderGridItem)}
        </div>
      )}
      {footer}
    </div>
  );
}
