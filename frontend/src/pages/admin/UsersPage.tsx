import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, ShieldCheck, ShieldOff, Check, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { usersApi } from "@/api/users";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { UserDetailSheet } from "./UserDetailSheet";
import type { UserListItem, UserStatus } from "@/types/users";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<UserStatus, string> = {
  pending: "Ожидает",
  active: "Активен",
  blocked: "Заблокирован",
  rejected: "Отклонён",
  deleted: "Удалён",
};

const STATUS_COLORS: Record<UserStatus, string> = {
  pending: "bg-amber-500 text-white dark:bg-amber-600",
  active: "bg-green-600 text-white dark:bg-green-700",
  blocked: "bg-red-600 text-white dark:bg-red-700",
  rejected: "bg-zinc-500 text-white dark:bg-zinc-600",
  deleted: "bg-zinc-400 text-white dark:bg-zinc-600",
};

// ── User row ─────────────────────────────────────────────────────────────────

function UserRow({ user, onOpen }: { user: UserListItem; onOpen: () => void }) {
  const qc = useQueryClient();

  const approve = useMutation({
    mutationFn: () => usersApi.approve(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Пользователь одобрен");
    },
    onError: () => toast.error("Не удалось одобрить"),
  });

  const unblock = useMutation({
    mutationFn: () => usersApi.unblock(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Пользователь разблокирован");
    },
    onError: () => toast.error("Не удалось разблокировать"),
  });

  const deleteUser = useMutation({
    mutationFn: () => usersApi.delete(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Пользователь удалён");
    },
    onError: () => toast.error("Не удалось удалить пользователя"),
  });

  return (
    <tr
      className="hover:bg-muted/40 cursor-pointer border-b transition-colors last:border-0"
      onClick={onOpen}
    >
      <td className="px-4 py-2 text-sm font-medium">{user.email}</td>
      <td className="text-muted-foreground px-4 py-2 text-sm">@{user.username}</td>
      <td className="px-4 py-2">
        <span
          className={cn(
            "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold",
            STATUS_COLORS[user.status],
          )}
        >
          {STATUS_LABELS[user.status]}
        </span>
      </td>
      <td className="text-muted-foreground px-4 py-2 text-xs">
        {new Date(user.created_at).toLocaleDateString("ru-RU")}
      </td>
      <td className="px-4 py-2">
        <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {user.status === "pending" && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-green-600 hover:text-green-700"
              title="Одобрить"
              disabled={approve.isPending}
              onClick={() => approve.mutate()}
            >
              {approve.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
          {user.status === "active" && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-orange-600 hover:text-orange-700"
              title="Заблокировать"
              onClick={() => onOpen()}
            >
              <ShieldOff className="h-3.5 w-3.5" />
            </Button>
          )}
          {user.status === "blocked" && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-green-600 hover:text-green-700"
              title="Разблокировать"
              disabled={unblock.isPending}
              onClick={() => unblock.mutate()}
            >
              {unblock.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
          {user.status !== "deleted" && (
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive h-7 w-7"
              title="Удалить"
              disabled={deleteUser.isPending}
              onClick={() => {
                if (confirm(`Удалить пользователя ${user.email}?`)) deleteUser.mutate();
              }}
            >
              {deleteUser.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending", label: "Ожидающие" },
  { value: "active", label: "Активные" },
  { value: "blocked", label: "Заблокированные" },
  { value: "rejected", label: "Отклонённые" },
];

export function UsersPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [selectedUser, setSelectedUser] = useState<UserListItem | null>(null);
  const LIMIT = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users", search, status, page],
    queryFn: () =>
      usersApi.list({
        search: search || undefined,
        status: status || undefined,
        limit: LIMIT,
        offset: page * LIMIT,
      }),
  });

  const users = data?.items ?? [];
  const total = data?.meta.total ?? 0;
  const pageCount = Math.ceil(total / LIMIT);

  return (
    <div className="flex flex-col gap-4">
      {/* Фильтры */}
      <div className="flex flex-wrap gap-2">
        <div className="relative">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2" />
          <Input
            placeholder="Поиск по email или имени…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="h-8 w-64 pl-7 text-sm"
          />
        </div>
        <div className="flex gap-1">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setStatus(opt.value);
                setPage(0);
              }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                status === opt.value
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
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Email</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Логин</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Статус</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Создан</th>
              <th className="text-muted-foreground px-4 py-2 text-right text-xs font-medium">
                Действия
              </th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b last:border-0">
                  {Array.from({ length: 5 }).map((__, j) => (
                    <td key={j} className="px-4 py-2">
                      <Skeleton className="h-4 rounded" />
                    </td>
                  ))}
                </tr>
              ))
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-muted-foreground px-4 py-8 text-center text-sm">
                  Пользователи не найдены.
                </td>
              </tr>
            ) : (
              users.map((u) => <UserRow key={u.id} user={u} onOpen={() => setSelectedUser(u)} />)
            )}
          </tbody>
        </table>
      </div>

      {/* Пагинация */}
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
            Стр. {page + 1} / {pageCount} · {total} польз.
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

      <UserDetailSheet user={selectedUser} onClose={() => setSelectedUser(null)} />
    </div>
  );
}
