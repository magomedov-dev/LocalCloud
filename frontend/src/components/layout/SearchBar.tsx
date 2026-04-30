import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, Loader2, FileText, Folder } from "lucide-react";
import { nodesApi } from "@/api/nodes";
import { cn } from "@/lib/utils";
import type { NodeListItem } from "@/types/nodes";

/**
 * Возвращает значение с задержкой.
 *
 * Используется для debounce-поведения, чтобы не выполнять действие
 * при каждом изменении значения, а дождаться паузы во вводе.
 */
function useDebounce(value: string, ms: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

/**
 * Формирует путь для перехода по результату поиска.
 *
 * Для папки возвращает путь самой папки.
 * Для файла возвращает путь родительской папки,
 * либо корневой раздел файлов, если родителя нет.
 */
function resultHref(item: NodeListItem) {
  if (item.node_type === "folder") return `/files/folders/${item.id}`;
  return item.parent_id ? `/files/folders/${item.parent_id}` : "/files";
}

/**
 * Строка поиска по файлам и папкам.
 *
 * Выполняет поиск с debounce-задержкой, отображает выпадающий список результатов
 * и поддерживает навигацию с клавиатуры.
 *
 * Горячая клавиша `Ctrl+K` / `Cmd+K` фокусирует поле поиска.
 */
export function SearchBar() {
  const navigate = useNavigate();
  const [raw, setRaw] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const query = useDebounce(raw.trim(), 300);

  const { data, isFetching } = useQuery({
    queryKey: ["search", query],
    queryFn: () => nodesApi.search(query, { limit: 10 }),
    enabled: query.length >= 1,
    staleTime: 15_000,
  });

  const results = useMemo<NodeListItem[]>(() => data?.items ?? [], [data?.items]);

  /**
   * Открывает список при наличии поискового запроса
   * и сбрасывает активный элемент при изменении запроса или результатов.
   */
  useEffect(() => {
    if (query) setOpen(true);
    else setOpen(false);
    setCursor(-1);
  }, [query, results]);

  /**
   * Глобальный shortcut для фокуса на поиске.
   *
   * `Ctrl+K` или `Cmd+K` фокусирует поле ввода
   * и выделяет текущее значение.
   */
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  /**
   * Обрабатывает клавиатурную навигацию по результатам поиска.
   *
   * `Escape` закрывает список.
   * `ArrowDown` и `ArrowUp` перемещают курсор.
   * `Enter` выбирает активный результат.
   */
  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, -1));
    } else if (e.key === "Enter" && cursor >= 0 && results[cursor]) {
      pick(results[cursor]);
    }
  }

  /**
   * Выбирает результат поиска.
   *
   * Закрывает dropdown, очищает поле поиска и выполняет переход.
   * Для файла дополнительно передаёт `selectId` в state,
   * чтобы его можно было выделить после перехода.
   */
  function pick(item: NodeListItem) {
    setOpen(false);
    setRaw("");
    const state = item.node_type === "file" ? { selectId: item.id } : undefined;
    navigate(resultHref(item), { state });
  }

  /**
   * Прокручивает список так, чтобы активный элемент
   * оставался в видимой области.
   */
  useEffect(() => {
    if (cursor < 0 || !listRef.current) return;
    const el = listRef.current.children[cursor] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const showDropdown = open && query.length >= 1;

  return (
    <div className="relative w-full max-w-sm min-w-0">
      {/* Поле ввода */}
      <div className="relative flex items-center">
        <Search className="text-muted-foreground pointer-events-none absolute left-3 h-4 w-4" />
        {isFetching && query ? (
          <Loader2 className="text-muted-foreground pointer-events-none absolute right-3 h-3.5 w-3.5 animate-spin" />
        ) : null}
        <input
          ref={inputRef}
          type="text"
          value={raw}
          placeholder="Поиск…"
          aria-label="Поиск файлов и папок"
          className="border-input bg-background placeholder:text-muted-foreground focus:ring-ring h-8 w-full rounded-full border pr-9 pl-9 text-sm focus:ring-2 focus:outline-none"
          onChange={(e) => setRaw(e.target.value)}
          onFocus={() => {
            if (query) setOpen(true);
          }}
          // Закрываем сразу: клик по результату использует onMouseDown +
          // preventDefault, поэтому blur при выборе элемента не срабатывает.
          // Это убирает гонку и утечку таймера прежнего setTimeout(150).
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
        />
        <kbd className="border-border text-muted-foreground pointer-events-none absolute right-3 hidden rounded border px-1 py-0.5 font-mono text-[10px] select-none sm:block">
          ⌃K
        </kbd>
      </div>

      {/* Выпадающий список */}
      {showDropdown && (
        <div className="bg-popover absolute top-full right-0 left-0 z-50 mt-1.5 max-h-72 overflow-auto rounded-xl border shadow-xl">
          {results.length === 0 && !isFetching ? (
            <p className="text-muted-foreground px-4 py-3 text-sm">Ничего не найдено</p>
          ) : (
            <ul ref={listRef} role="listbox">
              {results.map((item, idx) => (
                <li
                  key={item.id}
                  role="option"
                  aria-selected={cursor === idx}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm",
                    cursor === idx ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
                  )}
                  onMouseEnter={() => setCursor(idx)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(item);
                  }}
                >
                  {item.node_type === "folder" ? (
                    <Folder className="text-muted-foreground h-4 w-4 shrink-0" />
                  ) : (
                    <FileText className="text-muted-foreground h-4 w-4 shrink-0" />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{item.name}</span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {item.path}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
