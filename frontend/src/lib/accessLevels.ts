import type { PermissionLevel } from "@/types/permissions";

/**
 * Набор флагов доступа, соответствующий уровню.
 */
export interface AccessFlags {
  can_read: boolean;
  can_download: boolean;
  can_write: boolean;
  can_delete: boolean;
  can_share: boolean;
}

/**
 * Выбираемый при шеринге уровень доступа.
 *
 * `value` — это `permission_level` бэкенда (метка), а `flags` — реальные
 * права. Бэкенд НЕ выводит флаги из уровня сам, поэтому фронт обязан слать
 * корректный набор флагов вместе с уровнем.
 */
export interface AccessLevelOption {
  value: PermissionLevel;
  label: string;
  description: string;
  flags: AccessFlags;
}

/**
 * Три уровня доступа, предлагаемые при выдаче доступа пользователю.
 */
export const ACCESS_LEVELS: readonly AccessLevelOption[] = [
  {
    value: "download",
    label: "Просмотр",
    description: "Открывать, просматривать и скачивать",
    flags: {
      can_read: true,
      can_download: true,
      can_write: false,
      can_delete: false,
      can_share: false,
    },
  },
  {
    value: "write",
    label: "Редактирование",
    description: "Просмотр + переименование и загрузка",
    flags: {
      can_read: true,
      can_download: true,
      can_write: true,
      can_delete: false,
      can_share: false,
    },
  },
  {
    value: "delete",
    label: "Полный доступ",
    description: "Редактирование + удаление и передача доступа",
    flags: {
      can_read: true,
      can_download: true,
      can_write: true,
      can_delete: true,
      can_share: true,
    },
  },
] as const;

const LEVEL_LABELS: Record<PermissionLevel, string> = {
  read: "Просмотр",
  download: "Просмотр",
  write: "Редактирование",
  delete: "Полный доступ",
  owner: "Владелец",
};

/**
 * Человекочитаемая метка уровня доступа для бейджей.
 */
export function accessLevelLabel(level: PermissionLevel): string {
  return LEVEL_LABELS[level] ?? level;
}

/**
 * Возвращает опцию уровня, ближайшую к набору флагов разрешения.
 *
 * Нужна, чтобы в списке выданных доступов показать текущий уровень как один из
 * трёх выбираемых, опираясь на фактические флаги (а не только на метку).
 */
export function flagsToLevel(flags: Partial<AccessFlags>): PermissionLevel {
  if (flags.can_delete) return "delete";
  if (flags.can_write) return "write";
  return "download";
}
