import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, UserPlus, X } from "lucide-react";
import { toast } from "sonner";
import { permissionsApi } from "@/api/permissions";
import { usersApi } from "@/api/users";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ACTIVE_LINKS_QUERY_KEY } from "@/hooks/useShareBadges";
import { ACCESS_LEVELS, flagsToLevel } from "@/lib/accessLevels";
import { cn } from "@/lib/utils";
import type { PermissionLevel, NodePermissionListItem } from "@/types/permissions";
import type { UserLookupItem } from "@/types/users";

/**
 * Первые две буквы имени для аватара-заглушки.
 */
function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

/**
 * Селектор уровня доступа из трёх вариантов (segmented control).
 */
function LevelPicker({
  value,
  onChange,
  disabled,
}: {
  value: PermissionLevel;
  onChange: (v: PermissionLevel) => void;
  disabled?: boolean;
}) {
  return (
    <div className="border-border flex overflow-hidden rounded-lg border">
      {ACCESS_LEVELS.map((lvl) => (
        <button
          key={lvl.value}
          type="button"
          disabled={disabled}
          title={lvl.description}
          onClick={() => onChange(lvl.value)}
          className={cn(
            "flex-1 px-2 py-1.5 text-xs transition-colors disabled:opacity-50",
            value === lvl.value
              ? "bg-primary text-primary-foreground"
              : "hover:bg-accent",
          )}
        >
          {lvl.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Строка одного выданного доступа: имя получателя, селектор уровня, отзыв.
 */
function GrantRow({ nodeId, perm }: { nodeId: string; perm: NodePermissionListItem }) {
  const qc = useQueryClient();
  const QUERY_KEY = ["permissions", "node", nodeId];

  const { data: user } = useQuery({
    queryKey: ["user", perm.user_id],
    queryFn: () => usersApi.get(perm.user_id),
    staleTime: 5 * 60 * 1000,
  });

  function invalidate() {
    qc.invalidateQueries({ queryKey: QUERY_KEY });
    qc.invalidateQueries({ queryKey: ["permissions", "shared-with-me"] });
    qc.invalidateQueries({ queryKey: ["permissions", "shared-by-me"] });
    qc.invalidateQueries({ queryKey: ACTIVE_LINKS_QUERY_KEY });
  }

  const update = useMutation({
    mutationFn: (level: PermissionLevel) => {
      const opt = ACCESS_LEVELS.find((l) => l.value === level) ?? ACCESS_LEVELS[0];
      return permissionsApi.update(perm.id, {
        permission_level: opt.value,
        ...opt.flags,
      });
    },
    onSuccess: () => {
      invalidate();
      toast.success("Уровень доступа обновлён");
    },
    onError: () => toast.error("Не удалось изменить уровень доступа"),
  });

  const revoke = useMutation({
    mutationFn: () =>
      permissionsApi.revoke({ node_id: nodeId, user_id: perm.user_id }),
    onSuccess: () => {
      invalidate();
      toast.success("Доступ отозван");
    },
    onError: () => toast.error("Не удалось отозвать доступ"),
  });

  const displayName = user?.username ?? "Пользователь";
  const currentLevel = flagsToLevel(perm);

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-2.5">
      <div className="flex items-center gap-2">
        <Avatar className="h-7 w-7 shrink-0">
          <AvatarFallback className="text-[10px]">{initials(displayName)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={displayName}>
            {displayName}
          </p>
          {user?.email && (
            <p className="text-muted-foreground truncate text-xs" title={user.email}>
              {user.email}
            </p>
          )}
        </div>
        <button
          type="button"
          disabled={revoke.isPending}
          onClick={() => revoke.mutate()}
          title="Отозвать доступ"
          className="text-muted-foreground hover:text-destructive shrink-0 transition-colors disabled:opacity-50"
        >
          {revoke.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <X className="h-4 w-4" />
          )}
        </button>
      </div>
      <LevelPicker
        value={currentLevel}
        onChange={(v) => update.mutate(v)}
        disabled={update.isPending}
      />
    </div>
  );
}

/**
 * Вкладка выдачи доступа конкретным пользователям.
 *
 * Позволяет найти пользователя автопоиском, выбрать уровень доступа и выдать
 * его, а также показывает список текущих доступов с возможностью изменить
 * уровень или отозвать.
 */
export function UserShareTab({ nodeId }: { nodeId: string }) {
  const qc = useQueryClient();
  const QUERY_KEY = ["permissions", "node", nodeId];

  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<UserLookupItem | null>(null);
  const [level, setLevel] = useState<PermissionLevel>(ACCESS_LEVELS[0].value);

  const trimmed = query.trim();
  const { data: results, isFetching } = useQuery({
    queryKey: ["users", "lookup", trimmed],
    queryFn: () => usersApi.lookup(trimmed),
    enabled: trimmed.length >= 2 && selected === null,
    staleTime: 30 * 1000,
  });

  const { data: grants, isLoading: grantsLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => permissionsApi.listForNode(nodeId, { active_only: true }),
  });

  const grant = useMutation({
    mutationFn: () => {
      const opt = ACCESS_LEVELS.find((l) => l.value === level) ?? ACCESS_LEVELS[0];
      return permissionsApi.grant({
        node_id: nodeId,
        user_id: selected!.id,
        permission_level: opt.value,
        ...opt.flags,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["permissions", "shared-with-me"] });
      qc.invalidateQueries({ queryKey: ACTIVE_LINKS_QUERY_KEY });
      toast.success(`Доступ выдан: ${selected?.username}`);
      setSelected(null);
      setQuery("");
      setLevel(ACCESS_LEVELS[0].value);
    },
    onError: () => toast.error("Не удалось выдать доступ"),
  });

  const activeGrants = grants?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      {/* Поиск и выдача доступа */}
      <div className="flex flex-col gap-2">
        {selected ? (
          <div className="bg-muted/30 flex items-center gap-2 rounded-lg border p-2">
            <Avatar className="h-7 w-7 shrink-0">
              <AvatarFallback className="text-[10px]">
                {initials(selected.username)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{selected.username}</p>
              <p className="text-muted-foreground truncate text-xs">{selected.email}</p>
            </div>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-muted-foreground hover:text-foreground shrink-0"
              title="Выбрать другого"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="relative">
            <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
            <Input
              autoFocus
              placeholder="Поиск по имени или email"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-9 pl-8"
            />
            {trimmed.length >= 2 && (
              <div className="border-border bg-popover absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-lg border shadow-md">
                {isFetching ? (
                  <div className="text-muted-foreground flex items-center gap-2 p-3 text-xs">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Поиск…
                  </div>
                ) : (results?.length ?? 0) === 0 ? (
                  <p className="text-muted-foreground p-3 text-xs">Никого не найдено</p>
                ) : (
                  results!.map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      onClick={() => {
                        setSelected(u);
                        setQuery("");
                      }}
                      className="hover:bg-accent flex w-full items-center gap-2 p-2 text-left"
                    >
                      <Avatar className="h-7 w-7 shrink-0">
                        <AvatarFallback className="text-[10px]">
                          {initials(u.username)}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <p className="truncate text-sm">{u.username}</p>
                        <p className="text-muted-foreground truncate text-xs">{u.email}</p>
                      </div>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        )}

        {selected && (
          <>
            <LevelPicker value={level} onChange={setLevel} disabled={grant.isPending} />
            <Button disabled={grant.isPending} onClick={() => grant.mutate()}>
              {grant.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="mr-2 h-4 w-4" />
              )}
              Выдать доступ
            </Button>
          </>
        )}
      </div>

      {/* Текущие доступы */}
      <div className="flex flex-col gap-2">
        <p className="text-muted-foreground text-xs font-medium">У кого есть доступ</p>
        {grantsLoading ? (
          <Skeleton className="h-14 rounded-lg" />
        ) : activeGrants.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-center text-xs">
            Пока никому не выдан доступ
          </p>
        ) : (
          activeGrants.map((perm) => (
            <GrantRow key={perm.id} nodeId={nodeId} perm={perm} />
          ))
        )}
      </div>
    </div>
  );
}
