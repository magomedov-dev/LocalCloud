/**
 * Разрешённые действия над элементом для контекста ограниченного доступа
 * (вкладка «Доступно мне»). В обычном файловом менеджере не используется —
 * там пользователь владеет элементами и может всё.
 */
export interface ItemCapabilities {
  /** Можно изменять: переименовать, переместить, копировать, цвет папки. */
  canWrite: boolean;
  /** Можно удалить (переместить в корзину). */
  canDelete: boolean;
  /** Можно передавать доступ дальше (делиться). */
  canShare: boolean;
}

/**
 * Возвращает признаки доступности действий с учётом возможного ограничения.
 *
 * Если `capabilities` не задан (собственный файл) — все действия разрешены.
 */
export function resolveCapabilities(capabilities?: ItemCapabilities): ItemCapabilities {
  if (!capabilities) return { canWrite: true, canDelete: true, canShare: true };
  return capabilities;
}
