import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { registrationApi } from "@/api/registration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import type { RegistrationRead, RegistrationStatus } from "@/types/registration";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<RegistrationStatus, string> = {
  pending: "Ожидает",
  approved: "Одобрена",
  rejected: "Отклонена",
  cancelled: "Отменена",
};

const STATUS_COLORS: Record<RegistrationStatus, string> = {
  pending: "bg-amber-500 text-white dark:bg-amber-600",
  approved: "bg-green-600 text-white dark:bg-green-700",
  rejected: "bg-red-600 text-white dark:bg-red-700",
  cancelled: "bg-zinc-500 text-white dark:bg-zinc-600",
};

// ── Reject dialog ─────────────────────────────────────────────────────────────

function RejectDialog({ req, onClose }: { req: RegistrationRead; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");

  const reject = useMutation({
    mutationFn: () => registrationApi.reject(req.id, { rejection_reason: reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-registration"] });
      toast.success("Заявка отклонена");
      onClose();
    },
    onError: () => toast.error("Не удалось отклонить заявку"),
  });

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Отклонить заявку — {req.email}</DialogTitle>
        </DialogHeader>
        <Input
          placeholder="Причина отклонения*"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="h-8 text-sm"
        />
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={!reason.trim() || reject.isPending}
            onClick={() => reject.mutate()}
          >
            {reject.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Отклонить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

function RegRow({ req }: { req: RegistrationRead }) {
  const qc = useQueryClient();
  const [rejectOpen, setRejectOpen] = useState(false);

  const approve = useMutation({
    mutationFn: () => registrationApi.approve(req.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-registration"] });
      toast.success("Заявка одобрена");
    },
    onError: () => toast.error("Не удалось одобрить заявку"),
  });

  return (
    <>
      <tr className="hover:bg-muted/40 border-b transition-colors last:border-0">
        <td className="px-4 py-2 text-sm font-medium">{req.email}</td>
        <td className="text-muted-foreground px-4 py-2 text-sm">@{req.username}</td>
        <td className="px-4 py-2">
          <span
            className={cn(
              "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold",
              STATUS_COLORS[req.status],
            )}
          >
            {STATUS_LABELS[req.status]}
          </span>
        </td>
        <td className="text-muted-foreground px-4 py-2 text-xs">
          {new Date(req.created_at).toLocaleDateString("ru-RU")}
        </td>
        <td className="px-4 py-2">
          {req.status === "pending" && (
            <div className="flex items-center justify-end gap-1">
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
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive hover:text-destructive h-7 w-7"
                title="Отклонить"
                onClick={() => setRejectOpen(true)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </td>
      </tr>
      {rejectOpen && <RejectDialog req={req} onClose={() => setRejectOpen(false)} />}
    </>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "Все" },
  { value: "pending", label: "Ожидающие" },
  { value: "approved", label: "Одобренные" },
  { value: "rejected", label: "Отклонённые" },
];

export function RegistrationPage() {
  const [status, setStatus] = useState("pending");
  const [page, setPage] = useState(0);
  const LIMIT = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-registration", status, page],
    queryFn: () =>
      registrationApi.list({
        status: status || undefined,
        limit: LIMIT,
        offset: page * LIMIT,
      }),
  });

  const items = data?.items ?? [];
  const total = data?.meta.total ?? 0;
  const pageCount = Math.ceil(total / LIMIT);

  return (
    <div className="flex flex-col gap-4">
      {/* Фильтры */}
      <div className="flex gap-1">
        {STATUS_FILTER_OPTIONS.map((opt) => (
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

      {/* Таблица */}
      <div className="overflow-auto rounded-lg border">
        <table className="w-full min-w-[600px] text-left">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Email</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Логин</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Статус</th>
              <th className="text-muted-foreground px-4 py-2 text-xs font-medium">Создана</th>
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
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-muted-foreground px-4 py-8 text-center text-sm">
                  Заявок нет.
                </td>
              </tr>
            ) : (
              items.map((r) => <RegRow key={r.id} req={r as RegistrationRead} />)
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
            Стр. {page + 1} / {pageCount}
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
