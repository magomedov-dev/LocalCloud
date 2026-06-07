import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Cloud, ArrowLeft, Eye, EyeOff, Loader2 } from "lucide-react";
import axios from "axios";
import { authApi } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tokenFromUrl = params.get("token") ?? "";

  const [token, setToken] = useState(tokenFromUrl);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const confirm_ = useMutation({
    mutationFn: () => authApi.confirmPasswordReset({ token, new_password: password }),
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
              ? "Токен недействителен или истёк."
              : "Произошла ошибка. Попробуйте позже.",
        );
      } else {
        setError("Произошла ошибка. Попробуйте позже.");
      }
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token.trim()) {
      setError("Введите токен сброса пароля.");
      return;
    }
    if (password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }
    if (password !== confirm) {
      setError("Пароли не совпадают.");
      return;
    }
    confirm_.mutate();
  }

  return (
    <div className="bg-background flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm shadow-lg">
        <CardHeader className="space-y-2 text-center">
          <div className="bg-primary/10 mx-auto flex h-12 w-12 items-center justify-center rounded-full">
            <Cloud className="text-primary h-6 w-6" />
          </div>
          <CardTitle className="text-2xl font-semibold">Новый пароль</CardTitle>
          <CardDescription>
            {success ? "Пароль изменён" : "Введите новый пароль для вашей учётной записи"}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {success ? (
            <div className="space-y-4">
              <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
                Пароль успешно изменён. Теперь вы можете войти с новым паролем.
              </p>
              <Button className="w-full" onClick={() => navigate("/login")}>
                Войти
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Token — editable in case URL param is missing */}
              {!tokenFromUrl && (
                <div className="space-y-2">
                  <Label htmlFor="rp-token">Токен сброса</Label>
                  <Input
                    id="rp-token"
                    type="text"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    disabled={confirm_.isPending}
                    required
                    className="font-mono text-xs"
                    placeholder="Вставьте токен сброса"
                  />
                </div>
              )}

              {/* Новый пароль */}
              <div className="space-y-2">
                <Label htmlFor="rp-password">Новый пароль</Label>
                <div className="relative">
                  <Input
                    id="rp-password"
                    type={showPass ? "text" : "password"}
                    autoComplete="new-password"
                    autoFocus
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={confirm_.isPending}
                    required
                    minLength={8}
                    className="pr-9"
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2.5 -translate-y-1/2"
                    onClick={() => setShowPass((v) => !v)}
                  >
                    {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <p className="text-muted-foreground text-xs">Минимум 8 символов</p>
              </div>

              {/* Подтверждение */}
              <div className="space-y-2">
                <Label htmlFor="rp-confirm">Подтвердите пароль</Label>
                <Input
                  id="rp-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  disabled={confirm_.isPending}
                  required
                />
              </div>

              {error && (
                <p className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={confirm_.isPending}>
                {confirm_.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Сохранить
              </Button>

              <div className="text-center">
                <Link
                  to="/login"
                  className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Вернуться ко входу
                </Link>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
