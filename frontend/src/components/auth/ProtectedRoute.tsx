import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/auth-context";

/**
 * Свойства защищённого маршрута.
 *
 * `children` — содержимое, которое будет отображено
 * только для авторизованного пользователя.
 */
interface Props {
  children: React.ReactNode;
}

/**
 * Компонент защищённого маршрута.
 *
 * Проверяет состояние авторизации пользователя.
 * Пока данные авторизации загружаются, отображает индикатор загрузки.
 *
 * Если пользователь не авторизован, перенаправляет его на страницу входа
 * и сохраняет текущий маршрут в `state.from`, чтобы после входа
 * можно было вернуться на исходную страницу.
 */
export function ProtectedRoute({ children }: Props) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="border-primary h-8 w-8 animate-spin rounded-full border-2 border-t-transparent" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
