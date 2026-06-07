/**
 * Тонкая неопределённая полоса загрузки, закреплённая сверху
 * относительно ближайшего родителя с `position: relative`.
 *
 * Используйте компонент вместе с `useIsFetching` или состоянием мутации,
 * чтобы показать, что рабочая область обновляется,
 * не блокируя взаимодействие с интерфейсом.
 */
export function TopLoadingBar({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="bg-primary/10 pointer-events-none absolute inset-x-0 top-0 z-30 h-0.5 overflow-hidden">
      <div
        className="bg-primary h-full w-1/4 rounded-full"
        style={{ animation: "lc-indeterminate 1.1s ease-in-out infinite" }}
      />
    </div>
  );
}
