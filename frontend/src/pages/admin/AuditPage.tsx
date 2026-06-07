import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { auditApi } from "@/api/audit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuditLog } from "@/types/audit";
import { cn } from "@/lib/utils";

const RESULT_COLORS: Record<string, string> = {
  success: "bg-green-600 text-white dark:bg-green-700",
  failure: "bg-red-600 text-white dark:bg-red-700",
  denied: "bg-orange-600 text-white dark:bg-orange-700",
  warning: "bg-amber-500 text-white dark:bg-amber-600",
};

const RESULT_LABELS: Record<string, string> = {
  success: "Успех",
  failure: "Ошибка",
  denied: "Отказ",
  warning: "Предупреждение",
};

function AuditRow({ log }: { log: AuditLog }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        className="hover:bg-muted/40 cursor-pointer border-b transition-colors last:border-0"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="text-muted-foreground px-4 py-2 text-xs whitespace-nowrap">
          {new Date(log.created_at).toLocaleString("ru-RU")}
        </td>
        <td className="px-4 py-2 font-mono text-xs">{log.action}</td>
        <td className="px-4 py-2">
          <span
            className={cn(
              "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold",
              RESULT_COLORS[log.result] ?? "bg-muted text-muted-foreground",
            )}
          >
            {RESULT_LABELS[log.result] ?? log.result}
          </span>
        </td>
        <td className="text-muted-foreground px-4 py-2 text-xs">{log.resource_type ?? "—"}</td>
        <td className="max-w-xs truncate px-4 py-2 text-xs">{log.message ?? "—"}</td>
        <td className="text-muted-foreground px-4 py-2 text-xs">{log.ip_address ?? "—"}</td>
      </tr>
      {expanded && (
        <tr className="bg-muted/20 border-b">
          <td colSpan={6} className="px-4 py-2">
            <div className="text-muted-foreground space-y-1 font-mono text-xs">
              {log.user_id && (
                <p>
                  <span className="font-semibold">user_id:</span> {log.user_id}
                </p>
              )}
              {log.entity_type && (
                <p>
                  <span className="font-semibold">entity:</span> {log.entity_type} {log.entity_id}
                </p>
              )}
              {log.error_code && (
                <p>
                  <span className="font-semibold">error_code:</span> {log.error_code}
                </p>
              )}
              {log.request_id && (
                <p>
                  <span className="font-semibold">request_id:</span> {log.request_id}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

const RESULT_OPTIONS = [
  { value: "", label: "Все" },
  { value: "success", label: "Успех" },
  { value: "failure", label: "Ошибка" },
  { value: "denied", label: "Отказ" },
];

export function AuditPage() {
  const [result, setResult] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const LIMIT = 25;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-audit", result, query, page],
    queryFn: () =>
      auditApi.list({
        result: result || undefined,
        query: query || undefined,
        limit: LIMIT,
        offset: page * LIMIT,
      } as Parameters<typeof auditApi.list>[0]),
  });

  const logs = data?.items ?? [];
  const total = data?.meta.total ?? 0;
  const pageCount = Math.ceil(total / LIMIT);

  return (
    <div className="flex flex-col gap-4">
      {/* Фильтры */}
      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Поиск по сообщению…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
          className="h-8 w-64 text-sm"
        />
        <div className="flex gap-1">
          {RESULT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setResult(opt.value);
                setPage(0);
              }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                result === opt.value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border hover:bg-muted",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Таблица */}
      <div className="overflow-auto rounded-lg border">
        <table className="w-full min-w-[700px] text-left">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium whitespace-nowrap">
                Время
              </th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Действие</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Результат</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Ресурс</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Сообщение</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">IP</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-b last:border-0">
                  {Array.from({ length: 6 }).map((__, j) => (
                    <td key={j} className="px-4 py-2">
                      <Skeleton className="h-4 rounded" />
                    </td>
                  ))}
                </tr>
              ))
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-muted-foreground px-4 py-8 text-center text-sm">
                  Записей нет.
                </td>
              </tr>
            ) : (
              logs.map((log) => <AuditRow key={log.id} log={log} />)
            )}
          </tbody>
        </table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            ← Назад
          </Button>
          <span className="text-muted-foreground">
            Стр. {page + 1} / {pageCount} · {total} записей
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => p + 1)}
          >
            Вперёд →
          </Button>
        </div>
      )}
    </div>
  );
}
