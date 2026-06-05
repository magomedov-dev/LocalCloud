import { describe, expect, it } from "vitest";
import {
  ACCESS_LEVELS,
  accessLevelLabel,
  flagsToLevel,
} from "@/lib/accessLevels";

describe("accessLevels", () => {
  it("каждый уровень несёт согласованный набор флагов", () => {
    const view = ACCESS_LEVELS.find((l) => l.value === "download")!;
    expect(view.flags).toMatchObject({ can_read: true, can_download: true, can_write: false });
    const edit = ACCESS_LEVELS.find((l) => l.value === "write")!;
    expect(edit.flags).toMatchObject({ can_write: true, can_delete: false });
    const full = ACCESS_LEVELS.find((l) => l.value === "delete")!;
    expect(full.flags).toMatchObject({ can_delete: true, can_share: true });
  });

  it.each([
    ["read", "Просмотр"],
    ["download", "Просмотр"],
    ["write", "Редактирование"],
    ["delete", "Полный доступ"],
    ["owner", "Владелец"],
  ] as const)("accessLevelLabel(%s) -> %s", (level, label) => {
    expect(accessLevelLabel(level)).toBe(label);
  });

  it.each([
    [{ can_write: false, can_delete: false }, "download"],
    [{ can_write: true, can_delete: false }, "write"],
    [{ can_write: true, can_delete: true }, "delete"],
  ] as const)("flagsToLevel(%o) -> %s", (flags, expected) => {
    expect(flagsToLevel(flags)).toBe(expected);
  });
});
