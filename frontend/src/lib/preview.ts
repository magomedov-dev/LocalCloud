/**
 * Поддержка миниатюр по MIME-типу — фронтовый аналог backend
 * `produces_image_thumbnail`.
 *
 * Для этих типов backend рендерит растровую миниатюру (webp), которую можно
 * показать в `<img>`: изображения, видео и PDF. Текст/JSON тоже имеют превью,
 * но в виде текстового фрагмента — он не миниатюра и обрабатывается отдельно
 * в модальном предпросмотре, поэтому в сетке для них показывается иконка.
 *
 * Источник истины о готовности миниатюры — сам ответ thumbnail-эндпоинта
 * (URL или null); здесь лишь решается, для каких файлов её вообще запрашивать.
 */

/**
 * Возвращает `true`, если для MIME-типа backend формирует растровую
 * миниатюру (изображение, видео или PDF).
 */
export function thumbnailSupported(mime: string | null | undefined): boolean {
  const m = (mime ?? "").trim().toLowerCase();
  if (!m) return false;
  return m.startsWith("image/") || m.startsWith("video/") || m === "application/pdf";
}
