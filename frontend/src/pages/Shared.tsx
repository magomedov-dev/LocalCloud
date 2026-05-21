import { useEffect, useMemo, useRef, useState } from "react";
import { LayoutGrid, LayoutList, Users } from "lucide-react";
import { useSharedWithMe } from "@/hooks/useSharedWithMe";
import { useBreadcrumb } from "@/contexts/breadcrumb-context";
import { FileGrid, type ViewMode } from "@/components/files/FileGrid";
import { SHARED_QUERY_KEY } from "@/hooks/useSharedWithMe";
import { toNodeListItem } from "@/lib/sharedNode";
import type { ItemCapabilities } from "@/components/files/itemCapabilities";
import type { NodeListItem } from "@/types/nodes";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const VIEW_KEY = "shared-view-mode";

/**
 * Страница «Доступно мне».
 *
 * Показывает файлы и папки, к которым другие пользователи выдали текущему
 * пользователю доступ, в той же рабочей области, что и «Файлы» (тот же
 * `FileGrid` с режимами сетки/списка). Действия над каждым элементом
 * ограничены выданным уровнем доступа.
 */
export function SharedPage() {
  const { setCrumbs } = useBreadcrumb();
  const { items, isLoading, error, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useSharedWithMe();
  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem(VIEW_KEY) as ViewMode) || "grid",
  );

  useEffect(() => {
    setCrumbs([{ label: "Доступно мне" }]);
  }, [setCrumbs]);

  function changeView(next: ViewMode) {
    setView(next);
    localStorage.setItem(VIEW_KEY, next);
  }

  // Элементы для FileGrid и быстрый доступ к правам по id.
  const nodeItems = useMemo<NodeListItem[]>(() => items.map(toNodeListItem), [items]);
  const sharedById = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  const capabilitiesFor = useMemo(
    () =>
      (item: NodeListItem): ItemCapabilities | undefined => {
        const shared = sharedById.get(item.id);
        if (!shared) return undefined;
        return {
          canWrite: shared.can_write,
          canDelete: shared.can_delete,
          canShare: shared.can_share,
        };
      },
    [sharedById],
  );

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <Users className="text-muted-foreground h-5 w-5" />
        <h1 className="flex-1 text-lg font-semibold">Доступно мне</h1>
        {/* Переключатель вида — как в «Файлах» */}
        <div className="bg-muted/50 flex items-center gap-0.5 rounded-lg p-0.5">
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-7 w-7", view === "grid" && "bg-background shadow-sm")}
            onClick={() => changeView("grid")}
            title="Сетка"
          >
            <LayoutGrid className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-7 w-7", view === "list" && "bg-background shadow-sm")}
            onClick={() => changeView("list")}
            title="Список"
          >
            <LayoutList className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-destructive py-20 text-center text-sm">
          Не удалось загрузить список доступа.
        </p>
      ) : !isLoading && nodeItems.length === 0 ? (
        <div className="text-muted-foreground flex flex-col items-center justify-center gap-3 py-20">
          <Users className="h-12 w-12 opacity-30" />
          <p className="text-sm">Вам пока ничего не предоставили</p>
        </div>
      ) : (
        <>
          <FileGrid
            items={nodeItems}
            isLoading={isLoading}
            folderQueryKey={SHARED_QUERY_KEY as unknown as unknown[]}
            view={view}
            capabilitiesFor={capabilitiesFor}
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            onLoadMore={fetchNextPage}
          />
          <div ref={sentinelRef} />
        </>
      )}
    </div>
  );
}
