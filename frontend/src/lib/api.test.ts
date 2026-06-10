import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Мокаем axios так, чтобы:
 * - `axios.create()` возвращал callable-инстанс (его вызывают как `api(config)`
 *   для повторного запроса), у которого есть `.post` и `.interceptors`.
 * - мы могли перехватить onRejected-callback, переданный в
 *   `interceptors.response.use`, и вызывать его напрямую.
 */
const instanceCall = vi.fn();
const postMock = vi.fn();
let rejectionHandler: (error: unknown) => Promise<unknown>;
let fulfilledHandler: (res: unknown) => unknown;

vi.mock("axios", () => {
  const create = vi.fn(() => {
    const instance = Object.assign(instanceCall, {
      post: postMock,
      interceptors: {
        response: {
          use: (onFulfilled: typeof fulfilledHandler, onRejected: typeof rejectionHandler) => {
            fulfilledHandler = onFulfilled;
            rejectionHandler = onRejected;
          },
        },
      },
    });
    return instance;
  });
  return { default: { create }, create };
});

// Импортируем после установки мока, чтобы регистрация interceptor использовала его.
await import("./api");

function err(status: number | undefined, config: Record<string, unknown> | undefined = {}) {
  return { response: status === undefined ? undefined : { status }, config };
}

describe("api response interceptor", () => {
  beforeEach(() => {
    instanceCall.mockReset();
    postMock.mockReset();
    instanceCall.mockResolvedValue({ data: "retried" });
    postMock.mockResolvedValue({});
  });

  it("fulfilled-обработчик пробрасывает response без изменений", () => {
    const res = { data: 1 };
    expect(fulfilledHandler(res)).toBe(res);
  });

  it("не-401 ошибки пробрасываются без refresh", async () => {
    const error = err(500, { url: "/nodes" });
    await expect(rejectionHandler(error)).rejects.toBe(error);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("ошибка без response (network) пробрасывается без refresh", async () => {
    const error = err(undefined, { url: "/nodes" });
    await expect(rejectionHandler(error)).rejects.toBe(error);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("401 уже с _retry пробрасывается без повторного refresh", async () => {
    const error = err(401, { url: "/nodes", _retry: true });
    await expect(rejectionHandler(error)).rejects.toBe(error);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("401 на самом /auth/refresh пропускается, чтобы избежать loop", async () => {
    const error = err(401, { url: "/auth/refresh" });
    await expect(rejectionHandler(error)).rejects.toBe(error);
    expect(postMock).not.toHaveBeenCalled();
  });

  it("401 вызывает refresh и повторяет исходный запрос", async () => {
    const config = { url: "/nodes" } as Record<string, unknown>;
    const result = await rejectionHandler(err(401, config));

    expect(postMock).toHaveBeenCalledWith("/auth/refresh");
    expect(config._retry).toBe(true);
    expect(instanceCall).toHaveBeenCalledWith(config);
    expect(result).toEqual({ data: "retried" });
  });

  it("при неудачном refresh диспатчит auth:session-expired и реджектит", async () => {
    postMock.mockRejectedValueOnce(new Error("refresh failed"));
    const listener = vi.fn();
    window.addEventListener("auth:session-expired", listener);

    const error = err(401, { url: "/nodes" });
    await expect(rejectionHandler(error)).rejects.toBe(error);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(instanceCall).not.toHaveBeenCalled();
    window.removeEventListener("auth:session-expired", listener);
  });

  it("параллельные 401 ставятся в очередь и повторяются после одного refresh", async () => {
    // Удерживаем refresh незавершённым, чтобы второй запрос встал в очередь.
    let resolveRefresh!: () => void;
    postMock.mockReturnValueOnce(
      new Promise<void>((r) => {
        resolveRefresh = () => r();
      }),
    );

    const firstConfig = { url: "/a" } as Record<string, unknown>;
    const secondConfig = { url: "/b" } as Record<string, unknown>;

    const firstPromise = rejectionHandler(err(401, firstConfig));
    // Пока isRefreshing=true, второй 401 уходит в waitQueue.
    const secondPromise = rejectionHandler(err(401, secondConfig));

    expect(postMock).toHaveBeenCalledTimes(1);

    resolveRefresh();
    const [first, second] = await Promise.all([firstPromise, secondPromise]);

    expect(first).toEqual({ data: "retried" });
    expect(second).toEqual({ data: "retried" });
    expect(secondConfig._retry).toBe(true);
    // Один refresh обслужил оба запроса, оба ретраились через инстанс.
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(instanceCall).toHaveBeenCalledWith(firstConfig);
    expect(instanceCall).toHaveBeenCalledWith(secondConfig);
  });
});
