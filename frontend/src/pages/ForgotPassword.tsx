import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Cloud, ArrowLeft, Copy, Check, Loader2 } from "lucide-react";
import axios from "axios";
import { authApi } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const request = useMutation({
    mutationFn: () => authApi.requestPasswordReset({ email }),
    onSuccess: (data) => {
      setToken(data.reset_token);
      setError(null);
    },
    onError: (err) => {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Произошла ошибка. Попробуйте позже.");
      } else {
        setError("Произошла ошибка. Попробуйте позже.");
      }
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    request.mutate();
  }

  function handleCopy() {
    if (!token) return;
    navigator.clipboard.writeText(token).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="bg-background flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm shadow-lg">
        <CardHeader className="space-y-2 text-center">
          <div className="bg-primary/10 mx-auto flex h-12 w-12 items-center justify-center rounded-full">
            <Cloud className="text-primary h-6 w-6" />
          </div>
          <CardTitle className="text-2xl font-semibold">Сброс пароля</CardTitle>
          <CardDescription>
            {token
              ? "Токен сброса сгенерирован"
              : "Введите email, чтобы получить ссылку для сброса"}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {!token ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="fp-email">Email</Label>
                <Input
                  id="fp-email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={request.isPending}
                  required
                />
              </div>

              {error && (
                <p className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={request.isPending}>
                {request.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Отправить
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
          ) : (
            <div className="space-y-4">
              <p className="rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400">
                Email-сервер не настроен. Скопируйте токен ниже и используйте его для сброса пароля.
              </p>

              <div className="space-y-1.5">
                <Label>Токен сброса</Label>
                <div className="flex items-center gap-2">
                  <Input readOnly value={token} className="h-8 font-mono text-xs" />
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={handleCopy}
                    title="Копировать"
                  >
                    {copied ? (
                      <Check className="h-3.5 w-3.5 text-green-600" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </div>
              </div>

              <Button
                className="w-full"
                onClick={() => navigate(`/reset-password?token=${encodeURIComponent(token)}`)}
              >
                Установить новый пароль
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
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
