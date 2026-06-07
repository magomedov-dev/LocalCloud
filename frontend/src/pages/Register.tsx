import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Cloud, ArrowLeft, Eye, EyeOff, Loader2, CircleCheck } from "lucide-react";
import axios from "axios";
import { registrationApi } from "@/api/registration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => registrationApi.create({ email, username, password }),
    onError: (err) => {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        if (typeof detail === "string") {
          setError(detail);
        } else if (Array.isArray(detail)) {
          setError(detail.map((d: { msg: string }) => d.msg).join(" "));
        } else if (err.response?.status === 409) {
          setError("Пользователь с таким email или именем уже существует.");
        } else {
          setError("Произошла ошибка. Попробуйте позже.");
        }
      } else {
        setError("Произошла ошибка. Попробуйте позже.");
      }
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }
    if (password !== confirm) {
      setError("Пароли не совпадают.");
      return;
    }
    submit.mutate();
  }

  if (submit.isSuccess) {
    return (
      <div className="bg-background flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-sm shadow-lg">
          <CardHeader className="space-y-2 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
              <CircleCheck className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <CardTitle className="text-2xl font-semibold">Заявка отправлена</CardTitle>
            <CardDescription>Администратор рассмотрит вашу заявку</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
              Заявка на регистрацию отправлена. После одобрения вы сможете войти с указанными
              данными.
            </p>
            <Link to="/login">
              <Button className="w-full">Вернуться ко входу</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="bg-background flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm shadow-lg">
        <CardHeader className="space-y-2 text-center">
          <div className="bg-primary/10 mx-auto flex h-12 w-12 items-center justify-center rounded-full">
            <Cloud className="text-primary h-6 w-6" />
          </div>
          <CardTitle className="text-2xl font-semibold">Регистрация</CardTitle>
          <CardDescription>Создайте заявку на доступ к LocalCloud</CardDescription>
        </CardHeader>

        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="reg-email">Email</Label>
              <Input
                id="reg-email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submit.isPending}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="reg-username">Имя пользователя</Label>
              <Input
                id="reg-username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={submit.isPending}
                required
                minLength={3}
                maxLength={64}
                placeholder="latin.letters_123"
              />
              <p className="text-muted-foreground text-xs">
                Латинские буквы, цифры, «.», «_», «-». Минимум 3 символа.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="reg-password">Пароль</Label>
              <div className="relative">
                <Input
                  id="reg-password"
                  type={showPass ? "text" : "password"}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submit.isPending}
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
              <p className="text-muted-foreground text-xs">Минимум 8 символов.</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="reg-confirm">Подтвердите пароль</Label>
              <Input
                id="reg-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={submit.isPending}
                required
              />
            </div>

            {error && (
              <p className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" disabled={submit.isPending}>
              {submit.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Отправить заявку
            </Button>

            <div className="text-center">
              <Link
                to="/login"
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Уже есть аккаунт? Войти
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
