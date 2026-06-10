import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Pencil, ShieldCheck, ShieldOff, Trash2, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { usersApi } from "@/api/users";
import { useAuth } from "@/contexts/auth-context";
import { quotasApi } from "@/api/quotas";
import { auditApi } from "@/api/audit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { formatBytes } from "@/hooks/useQuota";
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

const RESULT_COLORS: Record<string, string> = {
  success: "bg-green-600 text-white dark:bg-green-700",
  failure: "bg-red-600 text-white dark:bg-red-700",
  denied: "bg-orange-600 text-white dark:bg-orange-700",
  warning: "bg-amber-500 text-white dark:bg-amber-600",
};

function fmtDate(iso: string | null, time = false) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(time ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-muted-foreground w-40 shrink-0">{label}</span>
      <span className="min-w-0 flex-1 font-medium">{value ?? "—"}</span>
    </div>
  );
}

function QuotaStat({
  label,
  used,
  limit,
  usedLabel,
  limitLabel,
}: {
  label: string;
  used: number;
  limit: number | null;
  usedLabel?: string;
  limitLabel?: string;
}) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">
          {usedLabel ?? used} / {limitLabel ?? (limit == null ? "∞" : limit)}
        </span>
      </div>
      {limit != null && (
        <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct >= 90 ? "bg-destructive" : "bg-primary",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-muted-foreground mb-3 text-[10px] font-semibold tracking-widest uppercase">
      {children}
    </p>
  );
}

interface Props {
  user: UserListItem | null;
  onClose: () => void;
}

export function UserDetailSheet({ user, onClose }: Props) {
  const qc = useQueryClient();
  const { user: me } = useAuth();

  // Удаление недоступно для самого себя и для первичного администратора.
  const canDelete =
    user?.status !== "deleted" && !user?.is_primary_admin && me?.id !== user?.id;
  const [showBlockInput, setShowBlockInput] = useState(false);
  const [blockReason, setBlockReason] = useState("");
  const [showPasswordInput, setShowPasswordInput] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [editQuota, setEditQuota] = useState(false);
  const [quotaForm, setQuotaForm] = useState({
    storage_gb: "",
    max_file_mb: "",
    files_limit: "",
    links_limit: "",
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["admin-user-detail", user?.id],
    queryFn: () => usersApi.get(user!.id),
    enabled: !!user,
  });

  const { data: quota, isLoading: quotaLoading } = useQuery({
    queryKey: ["quota", user?.id],
    queryFn: () => quotasApi.getByUserId(user!.id),
    enabled: !!user,
  });

  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ["admin-user-audit", user?.id],
    queryFn: () => auditApi.list({ user_id: user!.id, limit: 10 }),
    enabled: !!user,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin-users"] });
    qc.invalidateQueries({ queryKey: ["admin-user-detail", user?.id] });
  };

  const approve = useMutation({
    mutationFn: () => usersApi.approve(user!.id),
    onSuccess: () => {
      invalidate();
      toast.success("Одобрен");
    },
    onError: () => toast.error("Не удалось одобрить"),
  });

  const block = useMutation({
    mutationFn: () => usersApi.block(user!.id, blockReason || undefined),
    onSuccess: () => {
      invalidate();
      setShowBlockInput(false);
      setBlockReason("");
      toast.success("Заблокирован");
    },
    onError: () => toast.error("Не удалось заблокировать"),
  });

  const unblock = useMutation({
    mutationFn: () => usersApi.unblock(user!.id),
    onSuccess: () => {
      invalidate();
      toast.success("Разблокирован");
    },
    onError: () => toast.error("Не удалось разблокировать"),
  });

  const deleteUser = useMutation({
    mutationFn: () => usersApi.delete(user!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Пользователь удалён");
      onClose();
    },
    onError: () => toast.error("Не удалось удалить"),
  });

  const changePassword = useMutation({
    mutationFn: () => usersApi.changePassword(user!.id, newPassword),
    onSuccess: () => {
      setShowPasswordInput(false);
      setNewPassword("");
      toast.success("Пароль изменён");
    },
    onError: () => toast.error("Не удалось изменить пароль"),
  });

  const updateQuota = useMutation({
    mutationFn: () =>
      quotasApi.updateByUserId(user!.id, {
        ...(quotaForm.storage_gb && {
          storage_limit_bytes: Math.round(parseFloat(quotaForm.storage_gb) * 1024 ** 3),
        }),
        ...(quotaForm.max_file_mb && {
          max_file_size_bytes: Math.round(parseFloat(quotaForm.max_file_mb) * 1024 ** 2),
        }),
        ...(quotaForm.files_limit && { files_limit: parseInt(quotaForm.files_limit) }),
        ...(quotaForm.links_limit && { public_links_limit: parseInt(quotaForm.links_limit) }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quota", user?.id] });
      setEditQuota(false);
      setQuotaForm({ storage_gb: "", max_file_mb: "", files_limit: "", links_limit: "" });
      toast.success("Квота обновлена");
    },
    onError: () => toast.error("Не удалось обновить квоту"),
  });

  const initials = user ? (user.email[0] + (user.username?.[0] ?? "")).toUpperCase() : "";

  const formHasValues =
    quotaForm.storage_gb || quotaForm.max_file_mb || quotaForm.files_limit || quotaForm.links_limit;

  return (
    <Sheet
      open={!!user}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <SheetContent
        className="flex w-full flex-col overflow-hidden p-0 sm:max-w-[480px]"
        aria-describedby={undefined}
      >
        {/* Заголовок */}
        <div className="flex shrink-0 items-center gap-3 border-b p-5">
          <div className="bg-primary/20 text-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <SheetTitle className="min-w-0 truncate font-semibold">{user?.email}</SheetTitle>
              {user && (
                <span
                  className={cn(
                    "inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold",
                    STATUS_COLORS[user.status],
                  )}
                >
                  {STATUS_LABELS[user.status]}
                </span>
              )}
            </div>
            <span className="text-muted-foreground text-sm">@{user?.username}</span>
          </div>
        </div>

        {/* Прокручиваемое тело */}
        <div className="flex-1 divide-y overflow-y-auto">
          {/* ── Основная информация ── */}
          <div className="p-5">
            <SectionTitle>Основная информация</SectionTitle>
            {detailLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-4 rounded" />
                ))}
              </div>
            ) : detail ? (
              <div className="flex flex-col gap-2">
                <InfoRow
                  label="ID"
                  value={<span className="font-mono text-xs">{detail.id}</span>}
                />
                <InfoRow label="Зарегистрирован" value={fmtDate(detail.created_at)} />
                <InfoRow label="Последний вход" value={fmtDate(detail.last_login_at, true)} />
                {detail.approved_at && (
                  <InfoRow label="Одобрен" value={fmtDate(detail.approved_at)} />
                )}
                {detail.blocked_at && (
                  <InfoRow label="Заблокирован" value={fmtDate(detail.blocked_at)} />
                )}
                {detail.block_reason && (
                  <InfoRow
                    label="Причина блок."
                    value={<span className="text-destructive">{detail.block_reason}</span>}
                  />
                )}
                {detail.rejected_at && (
                  <InfoRow label="Отклонён" value={fmtDate(detail.rejected_at)} />
                )}
                {detail.rejection_reason && (
                  <InfoRow
                    label="Причина откл."
                    value={<span className="text-muted-foreground">{detail.rejection_reason}</span>}
                  />
                )}
              </div>
            ) : null}
          </div>

          {/* ── Квоты ── */}
          <div className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <SectionTitle>Квоты</SectionTitle>
              <Button
                variant={editQuota ? "outline" : "default"}
                size="sm"
                className={editQuota ? "text-muted-foreground h-7 text-xs" : "h-7 text-xs"}
                onClick={() => setEditQuota((v) => !v)}
              >
                {editQuota ? (
                  <>
                    <X className="mr-1.5 h-3 w-3" />
                    Отмена
                  </>
                ) : (
                  <>
                    <Pencil className="mr-1.5 h-3 w-3" />
                    Изменить квоту
                  </>
                )}
              </Button>
            </div>

            {quotaLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-5 rounded" />
                ))}
              </div>
            ) : quota ? (
              <div className="flex flex-col gap-3">
                <QuotaStat
                  label="Хранилище"
                  used={quota.storage_used_bytes}
                  limit={quota.storage_limit_bytes}
                  usedLabel={formatBytes(quota.storage_used_bytes)}
                  limitLabel={formatBytes(quota.storage_limit_bytes)}
                />
                <QuotaStat label="Файлы" used={quota.files_used} limit={quota.files_limit} />
                <QuotaStat
                  label="Публичные ссылки"
                  used={quota.public_links_used}
                  limit={quota.public_links_limit}
                />
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Макс. размер файла</span>
                  <span className="font-medium">{formatBytes(quota.max_file_size_bytes)}</span>
                </div>

                {editQuota && (
                  <div className="mt-1 flex flex-col gap-2.5 rounded-lg border p-3">
                    <p className="text-muted-foreground text-xs">
                      Оставьте поле пустым, чтобы не изменять
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="flex flex-col gap-1">
                        <label className="text-muted-foreground text-xs">Хранилище (ГБ)</label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          placeholder={String(Math.round(quota.storage_limit_bytes / 1024 ** 3))}
                          value={quotaForm.storage_gb}
                          onChange={(e) =>
                            setQuotaForm((p) => ({ ...p, storage_gb: e.target.value }))
                          }
                          className="h-7 text-xs"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-muted-foreground text-xs">Макс. файл (МБ)</label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          placeholder={String(Math.round(quota.max_file_size_bytes / 1024 ** 2))}
                          value={quotaForm.max_file_mb}
                          onChange={(e) =>
                            setQuotaForm((p) => ({ ...p, max_file_mb: e.target.value }))
                          }
                          className="h-7 text-xs"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-muted-foreground text-xs">Лимит файлов</label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          placeholder={quota.files_limit == null ? "∞" : String(quota.files_limit)}
                          value={quotaForm.files_limit}
                          onChange={(e) =>
                            setQuotaForm((p) => ({ ...p, files_limit: e.target.value }))
                          }
                          className="h-7 text-xs"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-muted-foreground text-xs">Лимит ссылок</label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          placeholder={
                            quota.public_links_limit == null
                              ? "∞"
                              : String(quota.public_links_limit)
                          }
                          value={quotaForm.links_limit}
                          onChange={(e) =>
                            setQuotaForm((p) => ({ ...p, links_limit: e.target.value }))
                          }
                          className="h-7 text-xs"
                        />
                      </div>
                    </div>
                    <Button
                      size="sm"
                      className="self-end"
                      disabled={updateQuota.isPending || !formHasValues}
                      onClick={() => updateQuota.mutate()}
                    >
                      {updateQuota.isPending && (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      )}
                      Сохранить
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">Квота не настроена.</p>
            )}
          </div>

          {/* ── Недавняя активность ── */}
          <div className="p-5">
            <SectionTitle>Последние действия</SectionTitle>
            {auditLoading ? (
              <div className="space-y-1.5">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 rounded" />
                ))}
              </div>
            ) : (auditData?.items ?? []).length === 0 ? (
              <p className="text-muted-foreground text-sm">Нет записей.</p>
            ) : (
              <div className="flex flex-col divide-y rounded-lg border text-xs">
                {(auditData?.items ?? []).map((log) => (
                  <div key={log.id} className="flex items-start gap-2 px-3 py-2">
                    <span
                      className={cn(
                        "mt-0.5 shrink-0 rounded-full px-1.5 py-0.5 font-semibold",
                        RESULT_COLORS[log.result] ?? "bg-muted text-muted-foreground",
                      )}
                    >
                      {log.result}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono">{log.action}</p>
                      {log.message && (
                        <p className="text-muted-foreground truncate">{log.message}</p>
                      )}
                    </div>
                    <span className="text-muted-foreground shrink-0 whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString("ru-RU", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Действия ── */}
          <div className="p-5">
            <SectionTitle>Действия</SectionTitle>
            <div className="flex flex-wrap gap-2">
              {user?.status === "pending" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-green-200 text-green-700 hover:text-green-700"
                  disabled={approve.isPending}
                  onClick={() => approve.mutate()}
                >
                  {approve.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Одобрить
                </Button>
              )}
              {user?.status === "active" && !showBlockInput && (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-orange-200 text-orange-700 hover:text-orange-700"
                  onClick={() => setShowBlockInput(true)}
                >
                  <ShieldOff className="mr-1.5 h-3.5 w-3.5" />
                  Заблокировать
                </Button>
              )}
              {user?.status === "blocked" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-green-200 text-green-700 hover:text-green-700"
                  disabled={unblock.isPending}
                  onClick={() => unblock.mutate()}
                >
                  {unblock.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Разблокировать
                </Button>
              )}
              {canDelete && (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/20 text-destructive hover:text-destructive"
                  disabled={deleteUser.isPending}
                  onClick={() => {
                    if (confirm(`Удалить пользователя ${user?.email}?`)) deleteUser.mutate();
                  }}
                >
                  {deleteUser.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Удалить
                </Button>
              )}
              {user?.status !== "deleted" && !showPasswordInput && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowPasswordInput(true);
                    setShowBlockInput(false);
                  }}
                >
                  <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                  Сменить пароль
                </Button>
              )}
            </div>

            {showBlockInput && (
              <div className="mt-2 flex gap-2">
                <Input
                  placeholder="Причина блокировки (необязательно)"
                  value={blockReason}
                  onChange={(e) => setBlockReason(e.target.value)}
                  className="h-8 flex-1 text-sm"
                />
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={block.isPending}
                  onClick={() => block.mutate()}
                >
                  {block.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    "Заблокировать"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowBlockInput(false);
                    setBlockReason("");
                  }}
                >
                  Отмена
                </Button>
              </div>
            )}

            {showPasswordInput && (
              <div className="mt-2 flex gap-2">
                <Input
                  type="password"
                  placeholder="Новый пароль (мин. 8 символов)"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="h-8 flex-1 text-sm"
                />
                <Button
                  size="sm"
                  disabled={changePassword.isPending || newPassword.length < 8}
                  onClick={() => changePassword.mutate()}
                >
                  {changePassword.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    "Сохранить"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowPasswordInput(false);
                    setNewPassword("");
                  }}
                >
                  Отмена
                </Button>
              </div>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
