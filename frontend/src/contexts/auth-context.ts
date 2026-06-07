import { createContext, useContext } from "react";
import type { CurrentUser, LoginRequest } from "@/types";

/** Состояние аутентификации. */
interface AuthState {
  /** Текущий пользователь или null. */
  user: CurrentUser | null;
  /** Идёт ли загрузка auth-состояния. */
  isLoading: boolean;
  /** Авторизован ли пользователь. */
  isAuthenticated: boolean;
}

/**
 * Действия для управления аутентификацией.
 */
interface AuthActions {
  /** Выполняет вход пользователя по переданным данным. */
  login: (data: LoginRequest) => Promise<void>;
  /** Выполняет выход текущего пользователя. */
  logout: () => Promise<void>;
}

/**
 * Значение контекста аутентификации.
 */
export type AuthContextValue = AuthState & AuthActions;

/**
 * React-контекст аутентификации.
 *
 * Должен использоваться внутри `AuthProvider`.
 */
export const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Возвращает данные и действия аутентификации из `AuthContext`.
 *
 * @throws Если хук используется вне `AuthProvider`.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth должен использоваться внутри <AuthProvider>");
  return ctx;
}
