import { nodesApi } from "@/api/nodes";

/**
 * Запускает скачивание файла в браузере по URL.
 *
 * Создаёт временный HTML-элемент `<a>`, назначает ему URL и программно
 * вызывает click. После запуска скачивания элемент удаляется из DOM.
 *
 * Args:
 *   url: URL файла для скачивания. Обычно это presigned URL.
 *   filename: Имя файла, которое браузер должен использовать при скачивании.
 */
export function downloadBlobFromUrl(url: string, filename?: string): void {
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/**
 * Получает presigned URL файла и запускает его скачивание.
 *
 * Запрашивает у backend presigned download URL для node, затем передаёт его в
 * `downloadBlobFromUrl`. Если backend вернул имя файла, используется оно,
 * иначе используется fallback-значение `filename`.
 *
 * Args:
 *   nodeId: Идентификатор node, файл которого нужно скачать.
 *   filename: Fallback-имя файла для скачивания.
 *
 * Returns:
 *   Promise, который завершается после запуска скачивания.
 */
export async function downloadNodeFile(nodeId: string, filename: string): Promise<void> {
  const resp = await nodesApi.download(nodeId);
  downloadBlobFromUrl(resp.presigned_url, resp.filename ?? filename);
}
