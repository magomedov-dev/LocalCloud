import axios, { type AxiosRequestConfig } from "axios";

/**
 * Axios-клиент для запросов к backend API.
 *
 * Использует базовый путь `/api/v1`, отправляет cookies вместе с запросами
 * и по умолчанию передаёт JSON-заголовок `Content-Type`.
 */
export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

/**
 * Флаг активного silent refresh.
 *
 * Нужен, чтобы при нескольких параллельных `401 Unauthorized` не отправлять
 * несколько refresh-запросов одновременно.
 */
let isRefreshing = false;

/**
 * Очередь запросов, ожидающих завершения текущего refresh-запроса.
 *
 * Каждый callback продолжает выполнение запроса после успешного обновления
 * сессии.
 */
let waitQueue: Array<() => void> = [];

/**
 * Выполняет все ожидающие callbacks и очищает очередь.
 */
function drainQueue() {
  waitQueue.forEach((fn) => fn());
  waitQueue = [];
}

/**
 * Расширенная конфигурация Axios-запроса.
 *
 * Attributes:
 *   _retry: Внутренний флаг, который показывает, что запрос уже был повторён
 *     после попытки обновления сессии.
 */
interface RetryConfig extends AxiosRequestConfig {
  _retry?: boolean;
}

/**
 * Interceptor для silent refresh при ответе `401 Unauthorized`.
 *
 * Если access token истёк, interceptor один раз вызывает `/auth/refresh`,
 * затем повторяет исходный запрос. Параллельные запросы, которые тоже получили
 * `401`, ждут завершения текущего refresh-запроса в очереди.
 *
 * Если refresh не удался, очередь очищается и приложение получает событие
 * `auth:session-expired`, чтобы сбросить auth-state и выполнить redirect через
 * React Router.
 */
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const config = error.config as RetryConfig | undefined;
    const status = error.response?.status as number | undefined;

    // Перехватываем только 401, которые ещё не повторялись.
    // Сам /auth/refresh пропускаем, чтобы избежать бесконечного retry-loop.
    const isRefreshEndpoint = config?.url === "/auth/refresh";
    if (status !== 401 || config?._retry || isRefreshEndpoint) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      // Ждём, пока текущий refresh-запрос завершится.
      return new Promise<void>((resolve) => {
        waitQueue.push(resolve);
      }).then(() => {
        if (config) config._retry = true;
        return api(config!);
      });
    }

    if (config) config._retry = true;
    isRefreshing = true;

    try {
      await api.post("/auth/refresh");
      drainQueue();
      return api(config!);
    } catch {
      waitQueue = [];

      // AuthProvider слушает это событие, очищает auth-state и делает redirect
      // через React Router без полного reload страницы.
      window.dispatchEvent(new Event("auth:session-expired"));

      return Promise.reject(error);
    } finally {
      isRefreshing = false;
    }
  },
);

export default api;
