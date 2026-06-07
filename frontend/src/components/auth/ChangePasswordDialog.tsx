import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import axios from "axios";
import { authApi } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/**
 * Свойства диалога смены пароля.
 *
 * `open` определяет, открыт ли диалог.
 * `onOpenChange` вызывается при изменении состояния открытия.
 */
interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}

/**
 * Диалог смены пароля пользователя.
 *
 * Позволяет ввести текущий пароль, новый пароль и подтверждение.
 * Проверяет минимальную длину нового пароля и совпадение подтверждения,
 * после чего отправляет запрос на смену пароля через API.
 *
 * Поддерживает показ/скрытие текущего и нового пароля,
 * отображает ошибки валидации и сообщение об успешном изменении.
 */
export function ChangePasswordDialog({ open, onOpenChange }: Props) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNext, setShowNext] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const change = useMutation({
    mutationFn: () => authApi.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      setSuccess(true);
      setError(null);
    },
    onError: (err) => {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : err.response?.status === 400
              ? "Неверный текущий пароль."
              : "Произошла ошибка. Попробуйте позже.",
        );
      } else {
        setError("Произошла ошибка. Попробуйте позже.");
      }
    },
  });

  /**
   * Сбрасывает поля формы и служебные состояния диалога.
   */
  function reset() {
    setCurrent("");
    setNext("");
    setConfirm("");
    setError(null);
    setSuccess(false);
  }

  /**
   * Обрабатывает открытие и закрытие диалога.
   *
   * При закрытии очищает форму и сбрасывает ошибку/успешное состояние.
   */
  function handleOpenChange(v: boolean) {
    if (!v) reset();
    onOpenChange(v);
  }

  /**
   * Обрабатывает отправку формы смены пароля.
   *
   * Проверяет минимальную длину нового пароля,
   * совпадение подтверждения и запускает мутацию смены пароля.
   */
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < 8) {
      setError("Новый пароль должен содержать не менее 8 символов.");
      return;
    }
    if (next !== confirm) {
      setError("Пароли не совпадают.");
      return;
    }
    change.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Сменить пароль</DialogTitle>
        </DialogHeader>

        {success ? (
          <div className="flex flex-col gap-4 pt-1">
            <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
              Пароль успешно изменён.
            </p>
            <Button size="sm" onClick={() => handleOpenChange(false)}>
              Закрыть
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3 pt-1">
            {/* Текущий пароль */}
            <div className="space-y-1.5">
              <Label htmlFor="cp-current">Текущий пароль</Label>
              <div className="relative">
                <Input
                  id="cp-current"
                  type={showCurrent ? "text" : "password"}
                  autoComplete="current-password"
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  disabled={change.isPending}
                  required
                  className="pr-9"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2"
                  onClick={() => setShowCurrent((v) => !v)}
                >
                  {showCurrent ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {/* Новый пароль */}
            <div className="space-y-1.5">
              <Label htmlFor="cp-new">Новый пароль</Label>
              <div className="relative">
                <Input
                  id="cp-new"
                  type={showNext ? "text" : "password"}
                  autoComplete="new-password"
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                  disabled={change.isPending}
                  required
                  minLength={8}
                  className="pr-9"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2"
                  onClick={() => setShowNext((v) => !v)}
                >
                  {showNext ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-muted-foreground text-xs">Минимум 8 символов</p>
            </div>

            {/* Подтверждение нового пароля */}
            <div className="space-y-1.5">
              <Label htmlFor="cp-confirm">Подтвердите новый пароль</Label>
              <Input
                id="cp-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={change.isPending}
                required
              />
            </div>

            {error && (
              <p className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
                {error}
              </p>
            )}

            <Button type="submit" disabled={change.isPending} className="mt-1">
              {change.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Сохранить
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
