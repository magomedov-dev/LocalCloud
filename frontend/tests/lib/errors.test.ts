import { describe, expect, it } from "vitest";
import { friendlyError, parseApiError, UserFacingError } from "@/lib/errors";

function axiosError(status: number, data?: unknown) {
  return { response: { status, data }, request: {}, message: "Request failed" };
}

describe("parseApiError", () => {
  it("извлекает code/message/status/details из axios-ошибки", () => {
    const parsed = parseApiError(
      axiosError(409, {
        error: "conflict_error",
        message: "уже существует",
        details: { value: "x" },
      }),
    );
    expect(parsed).toMatchObject({
      isNetwork: false,
      status: 409,
      code: "conflict_error",
      message: "уже существует",
      details: { value: "x" },
    });
  });

  it("помечает сетевую ошибку, когда нет response", () => {
    const parsed = parseApiError({ request: {}, message: "Network Error" });
    expect(parsed.isNetwork).toBe(true);
  });

  it("берёт message из обычного Error", () => {
    const parsed = parseApiError(new Error("boom"));
    expect(parsed).toEqual({ isNetwork: false, message: "boom" });
  });

  it("возвращает пустой результат для неизвестного значения", () => {
    expect(parseApiError(42)).toEqual({ isNetwork: false });
  });
});

describe("friendlyError", () => {
  it("возвращает текст UserFacingError как есть", () => {
    expect(friendlyError(new UserFacingError("выберите папку"))).toBe("выберите папку");
  });

  it("сетевая ошибка → сообщение о соединении", () => {
    expect(friendlyError({ request: {}, message: "Network Error" })).toMatch(/соединени/i);
  });

  it("конфликт при загрузке подставляет имя файла", () => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation: "upload",
      name: "report.pdf",
    });
    expect(msg).toContain("report.pdf");
    expect(msg).toMatch(/уже есть/i);
  });

  it("конфликт перемещения без имени", () => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation: "move",
    });
    expect(msg).toMatch(/назначени/i);
  });

  it("конфликт переименования", () => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation: "rename",
      name: "f",
    });
    expect(msg).toMatch(/занято/i);
  });

  it("конфликт создания папки", () => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation: "createFolder",
      name: "docs",
    });
    expect(msg).toMatch(/docs/);
  });

  it("конфликт восстановления", () => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation: "restore",
    });
    expect(msg).toMatch(/исходной папке/i);
  });

  it("квота при загрузке распознаётся по коду upload_error+текст", () => {
    const msg = friendlyError(
      axiosError(409, { error: "upload_error", message: "превышение квоты" }),
      { operation: "upload", name: "big.bin" },
    );
    expect(msg).toMatch(/недостаточно места/i);
  });

  it("quota_exceeded → нехватка места", () => {
    const msg = friendlyError(axiosError(413, { error: "quota_exceeded" }), {
      operation: "upload",
    });
    expect(msg).toMatch(/недостаточно места|лимит/i);
  });

  it("not_found по коду", () => {
    const msg = friendlyError(axiosError(404, { error: "not_found" }), {
      operation: "move",
    });
    expect(msg).toMatch(/не найден/i);
  });

  it("permission_denied по статусу", () => {
    const msg = friendlyError(axiosError(403, {}), { operation: "delete" });
    expect(msg).toMatch(/прав/i);
  });

  it("401 → сессия истекла", () => {
    expect(friendlyError(axiosError(401, {}))).toMatch(/сесси/i);
  });

  it("storage/database недоступны", () => {
    expect(
      friendlyError(axiosError(502, { error: "storage_service_error" })),
    ).toMatch(/недоступ/i);
  });

  it("generic upload_error (не 409, без квоты)", () => {
    const msg = friendlyError(axiosError(400, { error: "upload_error" }), {
      operation: "upload",
      name: "a",
    });
    expect(msg).toMatch(/не удалось загрузить/i);
  });

  it("validation_error отдаёт сообщение бэкенда", () => {
    const msg = friendlyError(
      axiosError(422, { error: "validation_error", message: "Поле обязательно" }),
    );
    expect(msg).toBe("Поле обязательно");
  });

  it("5xx → серверная ошибка", () => {
    expect(friendlyError(axiosError(500, { error: "unexpected_error" }))).toMatch(
      /сервер/i,
    );
  });

  it("неизвестный код с операцией → общий текст операции", () => {
    const msg = friendlyError(axiosError(418, { error: "weird" }), {
      operation: "rename",
    });
    expect(msg).toMatch(/не удалось переименовать/i);
  });

  it("неизвестный код без операции → message бэкенда", () => {
    const msg = friendlyError(axiosError(418, { error: "weird", message: "странно" }));
    expect(msg).toBe("странно");
  });

  it("authorization_error → сессия истекла", () => {
    expect(friendlyError(axiosError(400, { error: "authorization_error" }))).toMatch(
      /сесси/i,
    );
  });

  it("database_error → сервис недоступен", () => {
    expect(friendlyError(axiosError(500, { error: "database_error" }))).toMatch(
      /недоступ/i,
    );
  });

  // not_found по всем операциям.
  it.each([
    ["upload", /папк/i],
    ["createFolder", /папк/i],
    ["restore", /исходн/i],
    ["copy", /папк/i],
    ["rename", /не найден/i],
    ["delete", /не найден/i],
    ["generic", /не найден/i],
  ] as const)("not_found для операции %s", (operation, re) => {
    const msg = friendlyError(axiosError(404, { error: "not_found" }), { operation });
    expect(msg).toMatch(re);
  });

  // permission_denied по всем операциям.
  it.each([
    ["upload"],
    ["move"],
    ["copy"],
    ["rename"],
    ["createFolder"],
    ["delete"],
    ["restore"],
    ["generic"],
  ] as const)("permission_denied для операции %s", (operation) => {
    const msg = friendlyError(axiosError(403, { error: "permission_denied" }), {
      operation,
    });
    expect(msg).toMatch(/прав/i);
  });

  // Конфликт для delete/download/copy/generic операций.
  it.each([
    ["delete"],
    ["download"],
    ["copy"],
    ["generic"],
  ] as const)("конфликт для операции %s", (operation) => {
    const msg = friendlyError(axiosError(409, { error: "conflict_error" }), {
      operation,
    });
    expect(msg).toMatch(/существ|именем/i);
  });

  // Общий фолбэк для разных операций (неизвестный код).
  it.each([
    ["upload", /загруз/i],
    ["move", /перемест/i],
    ["copy", /скопировать/i],
    ["createFolder", /папк/i],
    ["delete", /удал/i],
    ["restore", /восстанов/i],
    ["download", /скачать/i],
  ] as const)("общий фолбэк для операции %s", (operation, re) => {
    const msg = friendlyError(axiosError(418, { error: "weird" }), { operation });
    expect(msg).toMatch(re);
  });

  it("квота для не-upload операции", () => {
    const msg = friendlyError(axiosError(413, { error: "quota_exceeded" }), {
      operation: "move",
    });
    expect(msg).toMatch(/лимит хранилища/i);
  });

  it("квота при копировании → нехватка места для копирования", () => {
    const msg = friendlyError(axiosError(413, { error: "quota_exceeded" }), {
      operation: "copy",
    });
    expect(msg).toMatch(/недостаточно места для копирования/i);
  });
});
