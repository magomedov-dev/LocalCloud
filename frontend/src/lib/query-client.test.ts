import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { queryClient } from "./query-client";

function axiosErr(status: number) {
  return { isAxiosError: true, response: { status }, config: {}, name: "AxiosError" };
}

describe("queryClient", () => {
  it("является экземпляром QueryClient", () => {
    expect(queryClient).toBeInstanceOf(QueryClient);
  });

  it("настраивает staleTime и gcTime по умолчанию", () => {
    const defaults = queryClient.getDefaultOptions().queries!;
    expect(defaults.staleTime).toBe(1000 * 60 * 2);
    expect(defaults.gcTime).toBe(1000 * 60 * 5);
  });

  it("не повторяет 401-ошибки", () => {
    const retry = queryClient.getDefaultOptions().queries!.retry as (
      count: number,
      error: unknown,
    ) => boolean;
    expect(retry(0, axiosErr(401))).toBe(false);
  });

  it("повторяет прочие ошибки максимум дважды", () => {
    const retry = queryClient.getDefaultOptions().queries!.retry as (
      count: number,
      error: unknown,
    ) => boolean;
    expect(retry(0, axiosErr(500))).toBe(true);
    expect(retry(1, axiosErr(500))).toBe(true);
    expect(retry(2, axiosErr(500))).toBe(false);
  });

  it("повторяет не-axios ошибки до лимита", () => {
    const retry = queryClient.getDefaultOptions().queries!.retry as (
      count: number,
      error: unknown,
    ) => boolean;
    expect(retry(0, new Error("network"))).toBe(true);
    expect(retry(2, new Error("network"))).toBe(false);
  });
});
