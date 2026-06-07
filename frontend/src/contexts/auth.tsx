import { useCallback, useEffect, useState, type ReactNode } from "react";
import { authApi } from "@/api/auth";
import { queryClient } from "@/lib/query-client";
import type { CurrentUser, LoginRequest } from "@/types";
import { AuthContext } from "./auth-context";

/**
 * Провайдер контекста аутентификации.
 *
 * Загружает текущую сессию при монтировании и предоставляет
 * данные пользователя, состояние загрузки и методы входа/выхода.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Определяем текущую сессию при монтировании.
  useEffect(() => {
    authApi
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  /**
   * Выполняет вход пользователя и сохраняет его данные в состоянии.
   */
  const login = useCallback(async (data: LoginRequest) => {
    const res = await authApi.login(data);
    setUser(res.user);
  }, []);

  /**
   * Выполняет выход пользователя, очищает кэш запросов
   * и перенаправляет на страницу входа.
   */
  const logout = useCallback(async () => {
    await authApi.logout().catch(() => {});
    setUser(null);
    queryClient.clear();
    window.location.replace("/login");
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
