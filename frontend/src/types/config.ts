/**
 * Флаги функциональности развёртывания.
 *
 * Приходят с бэкенда (`GET /config`) и позволяют скрывать недоступные
 * возможности UI на слабых или ограниченных серверах.
 */
export interface ClientFeatureFlags {
  /** Показывать ли preview-миниатюры файлов. */
  previews_enabled: boolean;
  /** Доступен ли просмотр содержимого файлов. */
  file_viewer_enabled: boolean;
  /** Доступно ли проигрывание аудио/видео. */
  media_playback_enabled: boolean;
  /** Доступно ли редактирование текстовых файлов. */
  file_editing_enabled: boolean;
}

/** Публичная конфигурация клиента. */
export interface ClientConfig {
  /** Флаги функциональности приложения. */
  features: ClientFeatureFlags;
}
