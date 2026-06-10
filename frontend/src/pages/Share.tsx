import { useParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";
import { Download, FileText, Folder, Loader2, AlertTriangle, ImageIcon, Lock } from "lucide-react";
import { toast } from "sonner";
import { publicLinksApi } from "@/api/public-links";
import { thumbnailSupported } from "@/lib/preview";
import { downloadBlobFromUrl } from "@/lib/download";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes } from "@/hooks/useQuota";
import type { ArchiveTaskStatus } from "@/types/public-links";

const IMAGE_EXT = /\.(jpe?g|png|gif|webp|bmp|avif|svg)$/i;

function isImageFile(name?: string | null, mime?: string | null): boolean {
  if (mime?.startsWith("image/")) return true;
  return IMAGE_EXT.test(name ?? "");
}

function formatExpiry(iso: string) {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function SharePage() {
  const { token } = useParams<{ token: string }>();

  const {
    data: link,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["share", token],
    queryFn: () => publicLinksApi.getPublic(token!),
    enabled: !!token,
    retry: false,
  });

  const node = link?.node;
  const isFolder = node?.node_type === "folder";
  const isImage = !isFolder && isImageFile(node?.name, node?.file_mime_type);
  // Не-изображения (PDF/видео) показываем через сгенерированную webp-миниатюру.
  const hasThumbnail = !isFolder && !isImage && thumbnailSupported(node?.file_mime_type);

  // Пароль публичной ссылки: вводится на шлюзе и подтверждается через /access.
  // До разблокировки скачивание не запускаем, иначе сервер вернёт 403.
  const [password, setPassword] = useState("");
  const [unlockedPassword, setUnlockedPassword] = useState<string | null>(null);
  const needsUnlock = !!link && link.has_password && unlockedPassword === null;

  const access = useMutation({
    mutationFn: (pwd: string) => publicLinksApi.validateAccess(token!, pwd),
    onSuccess: (res, pwd) => {
      if (res.allowed) {
        setUnlockedPassword(pwd);
      } else {
        toast.error(res.message ?? "Неверный пароль");
      }
    },
    onError: () => toast.error("Не удалось проверить пароль"),
  });

  // Pre-fetch the presigned URL — used for both image preview and download.
  const { data: fileData, isLoading: fileLoading } = useQuery({
    queryKey: ["share-file", token, unlockedPassword],
    queryFn: () => publicLinksApi.download(token!, unlockedPassword ?? undefined),
    enabled: !!token && !!link && link.status === "active" && !isFolder && !needsUnlock,
    staleTime: 3 * 60 * 1000,
  });

  // Миниатюра для не-изображений (PDF/видео): отдельный presigned URL на
  // preview-объект. 404 (preview ещё не готов) трактуем как «нет миниатюры».
  const { data: thumbData, isLoading: thumbLoading } = useQuery({
    queryKey: ["share-thumb", token, unlockedPassword],
    queryFn: () => publicLinksApi.thumbnail(token!, unlockedPassword ?? undefined),
    enabled:
      !!token && !!link && link.status === "active" && hasThumbnail && !needsUnlock,
    retry: false,
    staleTime: 3 * 60 * 1000,
  });

  const [folderStatus, setFolderStatus] = useState<ArchiveTaskStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function stopPolling() {
    if (pollRef.current !== null) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => stopPolling, []);

  function handleFileDownload() {
    if (fileData) {
      downloadBlobFromUrl(fileData.presigned_url, fileData.filename ?? node?.name ?? "download");
      return;
    }
    publicLinksApi
      .download(token!, unlockedPassword ?? undefined)
      .then((r) => downloadBlobFromUrl(r.presigned_url, r.filename ?? "download"))
      .catch(() => toast.error("Не удалось скачать файл"));
  }

  const [folderArchiving, setFolderArchiving] = useState(false);

  async function handleFolderDownload() {
    setFolderStatus(null);
    stopPolling();
    setFolderArchiving(true);
    try {
      const resp = await publicLinksApi.startFolderArchive(token!, unlockedPassword ?? undefined);
      setFolderStatus(resp.status);
      if (resp.status === "completed" && resp.presigned_url) {
        downloadBlobFromUrl(resp.presigned_url, resp.filename ?? "archive.zip");
        setFolderArchiving(false);
        return;
      }
      function schedulePoll() {
        pollRef.current = setTimeout(async () => {
          try {
            const status = await publicLinksApi.pollFolderArchive(token!, resp.task_id);
            setFolderStatus(status.status);
            if (status.status === "completed" && status.presigned_url) {
              downloadBlobFromUrl(status.presigned_url, status.filename ?? "archive.zip");
              setFolderArchiving(false);
            } else if (status.status === "failed") {
              toast.error("Не удалось создать архив папки");
              setFolderArchiving(false);
            } else {
              schedulePoll();
            }
          } catch {
            toast.error("Не удалось получить статус архива");
            setFolderArchiving(false);
          }
        }, 2000);
      }
      schedulePoll();
    } catch {
      toast.error("Не удалось начать создание архива");
      setFolderArchiving(false);
    }
  }

  const isFolderBusy =
    folderArchiving ||
    (folderStatus !== null && folderStatus !== "completed" && folderStatus !== "failed");

  // ── Loading ──────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="bg-muted/20 flex min-h-screen items-center justify-center p-4">
        <div className="bg-card w-full max-w-md overflow-hidden rounded-2xl border shadow-lg">
          <Skeleton className="h-56 w-full rounded-none" />
          <div className="flex flex-col gap-3 p-6">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-2 h-10 w-full rounded-lg" />
          </div>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────

  if (isError || !link || link.status !== "active") {
    return (
      <div className="bg-muted/20 flex min-h-screen items-center justify-center p-4">
        <div className="bg-card flex flex-col items-center gap-4 rounded-2xl border p-10 text-center shadow-lg">
          <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
            <AlertTriangle className="text-muted-foreground h-7 w-7" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Ссылка недоступна</h1>
            <p className="text-muted-foreground mt-1 max-w-xs text-sm">
              Эта ссылка устарела, была отозвана или не существует.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Требуется пароль ───────────────────────────────────────────────────────

  if (needsUnlock) {
    return (
      <div className="bg-muted/20 flex min-h-screen items-center justify-center p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const pwd = password.trim();
            if (pwd) access.mutate(pwd);
          }}
          className="bg-card flex w-full max-w-sm flex-col items-center gap-4 rounded-2xl border p-8 text-center shadow-lg"
        >
          <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
            <Lock className="text-muted-foreground h-7 w-7" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Ссылка защищена паролем</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              Введите пароль, чтобы открыть {isFolder ? "папку" : "файл"}.
            </p>
          </div>
          <div className="flex w-full flex-col gap-1.5 text-left">
            <Label htmlFor="access-password" className="sr-only">
              Пароль
            </Label>
            <Input
              id="access-password"
              type="password"
              autoComplete="current-password"
              placeholder="Пароль"
              maxLength={128}
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            className="w-full"
            disabled={access.isPending || !password.trim()}
          >
            {access.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Проверка…
              </>
            ) : (
              "Открыть"
            )}
          </Button>
        </form>
      </div>
    );
  }

  // ── Shared page ──────────────────────────────────────────────────────────────

  const previewUrl = isImage ? fileData?.presigned_url : null;
  const thumbnailUrl = hasThumbnail ? (thumbData?.presigned_url ?? null) : null;
  const sizeBytes = fileData?.size_bytes ?? null;

  return (
    <div className="bg-muted/20 flex min-h-screen items-center justify-center p-4">
      <div className="bg-card w-full max-w-md overflow-hidden rounded-2xl border shadow-lg">
        {/* Предпросмотр изображения */}
        {isImage && (
          <div className="bg-muted/30 flex min-h-52 items-center justify-center">
            {fileLoading ? (
              <Skeleton className="h-52 w-full rounded-none" />
            ) : previewUrl ? (
              <img
                src={previewUrl}
                alt={node?.name ?? ""}
                className="max-h-80 w-full object-contain"
              />
            ) : (
              <ImageIcon className="text-muted-foreground/40 h-12 w-12" />
            )}
          </div>
        )}

        {/* Миниатюра для не-изображений с готовым preview (PDF/видео) */}
        {hasThumbnail && (
          <div className="bg-muted/30 flex min-h-52 items-center justify-center">
            {thumbLoading ? (
              <Skeleton className="h-52 w-full rounded-none" />
            ) : thumbnailUrl ? (
              <img
                src={thumbnailUrl}
                alt={node?.name ?? ""}
                className="max-h-80 w-full object-contain"
              />
            ) : (
              <div className="bg-muted flex h-20 w-20 items-center justify-center rounded-2xl">
                <FileText className="text-muted-foreground h-10 w-10" />
              </div>
            )}
          </div>
        )}

        {/* Иконка для папок и файлов без миниатюры */}
        {!isImage && !hasThumbnail && (
          <div className="bg-muted/20 flex items-center justify-center py-10">
            <div className="bg-muted flex h-20 w-20 items-center justify-center rounded-2xl">
              {isFolder ? (
                <Folder className="text-muted-foreground h-10 w-10" />
              ) : (
                <FileText className="text-muted-foreground h-10 w-10" />
              )}
            </div>
          </div>
        )}

        {/* Информация и действия */}
        <div className="flex flex-col gap-4 p-6">
          <div>
            <h1
              className="text-base leading-snug font-semibold break-all"
              title={node?.name ?? undefined}
            >
              {node?.name ?? "Файл"}
            </h1>
            {sizeBytes != null && (
              <p className="text-muted-foreground mt-0.5 text-sm">{formatBytes(sizeBytes)}</p>
            )}
            {link.description && (
              <p className="text-muted-foreground mt-1 text-sm">{link.description}</p>
            )}
          </div>

          {/* Кнопка скачивания */}
          {isFolder ? (
            <Button className="w-full" disabled={isFolderBusy} onClick={handleFolderDownload}>
              {isFolderBusy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {folderStatus === "in_progress" ? "Создаётся архив…" : "Подготовка…"}
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" />
                  Скачать как ZIP
                </>
              )}
            </Button>
          ) : (
            <Button className="w-full" onClick={handleFileDownload}>
              <Download className="mr-2 h-4 w-4" />
              Скачать
            </Button>
          )}

          {link.expires_at && (
            <p className="text-muted-foreground text-center text-xs">
              Доступна до {formatExpiry(link.expires_at)}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
