import axios from "axios";
import { QueryClient } from "@tanstack/react-query";

/**
 * Глобальный React Query client приложения.
 *
 * Хранит настройки по умолчанию для всех queries: время свежести данных,
 * время удержания неактивного кэша в памяти и retry-политику.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      /**
       * Время, в течение которого данные считаются свежими.
       *
       * Значение 2 минуты помогает избежать лишнего refetch при обычной
       * навигации между папками.
       */
      staleTime: 1000 * 60 * 2,

      /**
       * Время удержания неактивных query-данных в памяти.
       *
       * После 5 минут неиспользуемые данные могут быть удалены из кэша.
       */
      gcTime: 1000 * 60 * 5,

      /**
       * Retry-политика для query-запросов.
       *
       * Ошибки `401 Unauthorized` не повторяются, потому что auth-слой сам
       * отвечает за refresh-сценарий и сброс сессии. Остальные ошибки
       * повторяются максимум два раза.
       */
      retry: (failureCount, error) => {
        if (axios.isAxiosError(error) && error.response?.status === 401) return false;
        return failureCount < 2;
      },
    },
  },
});
