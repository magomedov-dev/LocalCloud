import { useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  Check,
  Download,
  ExternalLink,
  Loader2,
  Maximize2,
  Minimize2,
  Minus,
  Music,
  Pause,
  Pencil,
  Play,
  PlayCircle,
  Plus,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { nodesApi } from "@/api/nodes";
import { uploadsApi } from "@/api/uploads";
import { useFeatures } from "@/hooks/useFeatures";
import { downloadBlobFromUrl } from "@/lib/download";
import type { NodeListItem } from "@/types/nodes";

import { detectPreviewKind } from "./filePreviewKind";

/**
 * Форматирует время в секундах в формат `m:ss`.
 *
 * Если значение некорректное или отрицательное,
 * возвращает placeholder `--:--`.
 */
function formatTime(s: number) {
  if (!isFinite(s) || s < 0) return "--:--";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

// ── Общие примитивы ──────────────────────────────────────────────────────────

/**
 * Полоса управления числовым значением.
 *
 * Используется как базовый range-контрол для прогресса,
 * перемотки и громкости. Видимая заливка синхронизируется
 * со значением `value` относительно `max`.
 */
function TrackBar({
  value,
  max,
  step = 0.1,
  fillClass = "bg-primary",
  onChange,
}: {
  value: number;
  max: number;
  step?: number;
  fillClass?: string;
  onChange: (v: number) => void;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="bg-border relative h-1.5 w-full overflow-hidden rounded-full">
      <div
        className={cn("absolute inset-y-0 left-0 rounded-full", fillClass)}
        style={{ width: `${pct}%` }}
      />
      <input
        type="range"
        min={0}
        max={max || 1}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </div>
  );
}

/**
 * Строка перемотки медиа.
 *
 * Отображает progress/range-контрол и текущее время
 * вместе с общей длительностью.
 */
function SeekRow({
  currentTime,
  duration,
  onSeek,
}: {
  currentTime: number;
  duration: number;
  onSeek: (t: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <TrackBar value={currentTime} max={duration} step={0.1} onChange={onSeek} />
      <div className="text-muted-foreground flex justify-between text-xs">
        <span>{formatTime(currentTime)}</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

/**
 * Кнопки управления воспроизведением.
 *
 * Содержит перемотку на 10 секунд назад,
 * кнопку play/pause и перемотку на 10 секунд вперёд.
 */
function PlaybackButtons({
  playing,
  onToggle,
  onSeek,
}: {
  playing: boolean;
  onToggle: () => void;
  onSeek: (delta: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-4">
      <button
        onClick={() => onSeek(-10)}
        className="text-muted-foreground hover:bg-accent hover:text-foreground flex h-8 w-8 flex-col items-center justify-center rounded-full transition-colors"
      >
        <span className="text-[10px] leading-none font-bold">−10</span>
        <span className="text-[8px] leading-none opacity-60">с</span>
      </button>
      <button
        onClick={onToggle}
        className="bg-primary text-primary-foreground flex h-11 w-11 items-center justify-center rounded-full shadow-md transition-opacity hover:opacity-90"
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 translate-x-px" />}
      </button>
      <button
        onClick={() => onSeek(10)}
        className="text-muted-foreground hover:bg-accent hover:text-foreground flex h-8 w-8 flex-col items-center justify-center rounded-full transition-colors"
      >
        <span className="text-[10px] leading-none font-bold">+10</span>
        <span className="text-[8px] leading-none opacity-60">с</span>
      </button>
    </div>
  );
}

/**
 * Строка управления громкостью.
 *
 * Содержит кнопку mute/unmute, полосу громкости
 * и опциональный дополнительный элемент справа.
 */
function VolumeRow({
  volume,
  muted,
  onVolumeChange,
  onToggleMute,
  extra,
}: {
  volume: number;
  muted: boolean;
  onVolumeChange: (v: number) => void;
  onToggleMute: () => void;
  extra?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onToggleMute}
        className="text-muted-foreground hover:text-foreground shrink-0 transition-colors"
      >
        {muted || volume === 0 ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
      </button>
      <TrackBar
        value={muted ? 0 : volume}
        max={1}
        step={0.01}
        fillClass="bg-muted-foreground/50"
        onChange={onVolumeChange}
      />
      {extra}
    </div>
  );
}

// ── Просмотр изображения с zoom / pan ────────────────────────────────────────

/**
 * Просмотрщик изображений.
 *
 * Поддерживает масштабирование кнопками и колесом мыши,
 * а также перемещение изображения drag-and-drop при zoom больше 100%.
 */
function ImageViewer({ src, alt }: { src: string; alt: string }) {
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragOrigin = useRef({ x: 0, y: 0, px: 0, py: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  /**
   * Применяет новый zoom с ограничением диапазона.
   *
   * При масштабе 100% или меньше сбрасывает смещение изображения.
   */
  function applyZoom(next: number) {
    const clamped = Math.round(Math.min(5, Math.max(0.25, next)) * 100) / 100;
    setZoom(clamped);
    if (clamped <= 1) setPos({ x: 0, y: 0 });
  }

  /**
   * Подключает нативный wheel-listener для масштабирования.
   *
   * Синтетический `onWheel` в React может быть passive,
   * поэтому `preventDefault()` там может игнорироваться.
   * Нативный non-passive listener позволяет блокировать scroll страницы.
   */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      setZoom((prev) => {
        const next =
          Math.round(Math.min(5, Math.max(0.25, prev * (e.deltaY < 0 ? 1.1 : 0.9))) * 100) / 100;
        if (next <= 1) setPos({ x: 0, y: 0 });
        return next;
      });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  /**
   * Запускает drag-перемещение изображения,
   * если оно увеличено больше чем на 100%.
   */
  function handleMouseDown(e: React.MouseEvent) {
    if (zoom <= 1) return;
    e.preventDefault();
    setIsDragging(true);
    dragOrigin.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
  }

  /**
   * Обновляет смещение изображения во время drag-перемещения.
   */
  function handleMouseMove(e: React.MouseEvent) {
    if (!isDragging) return;
    setPos({
      x: dragOrigin.current.px + (e.clientX - dragOrigin.current.x),
      y: dragOrigin.current.py + (e.clientY - dragOrigin.current.y),
    });
  }

  return (
    <div
      ref={containerRef}
      className="relative flex h-full w-full items-center justify-center overflow-hidden select-none"
      style={{ cursor: isDragging ? "grabbing" : zoom > 1 ? "grab" : "default" }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={() => setIsDragging(false)}
      onMouseLeave={() => setIsDragging(false)}
    >
      <img
        src={src}
        alt={alt}
        draggable={false}
        className="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
        style={{
          transform: `translate(${pos.x}px, ${pos.y}px) scale(${zoom})`,
          transition: isDragging ? "none" : "transform 0.12s ease-out",
        }}
      />
      <div className="border-border bg-panel/95 absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border p-1 shadow-lg backdrop-blur-sm">
        <button
          onClick={() => applyZoom(zoom - 0.25)}
          className="text-muted-foreground hover:bg-accent hover:text-foreground flex h-7 w-7 items-center justify-center rounded-md transition-colors"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => {
            setZoom(1);
            setPos({ x: 0, y: 0 });
          }}
          className="text-foreground hover:bg-accent min-w-13 rounded-md px-1 py-1 text-center text-xs font-medium transition-colors"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          onClick={() => applyZoom(zoom + 0.25)}
          className="text-muted-foreground hover:bg-accent hover:text-foreground flex h-7 w-7 items-center justify-center rounded-md transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Аудиоплеер ───────────────────────────────────────────────────────────────

/**
 * Аудиоплеер для предпросмотра аудиофайла.
 *
 * Поддерживает воспроизведение, паузу, перемотку,
 * отображение прогресса, mute/unmute и изменение громкости.
 */
function AudioPlayer({ src, name }: { src: string; name: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);

  /**
   * Переключает воспроизведение аудио.
   */
  function toggle() {
    const a = audioRef.current;
    if (!a) return;
    if (playing) {
      a.pause();
      setPlaying(false);
    } else {
      a.play()
        .then(() => setPlaying(true))
        .catch(() => {});
    }
  }

  /**
   * Перематывает аудио на указанное количество секунд.
   */
  function seek(delta: number) {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + delta));
  }

  /**
   * Изменяет громкость аудио.
   */
  function handleVolume(v: number) {
    setVolume(v);
    if (audioRef.current) audioRef.current.volume = v;
    setMuted(v === 0);
  }

  /**
   * Переключает mute-состояние.
   */
  function toggleMute() {
    const a = audioRef.current;
    if (!a) return;
    const next = !muted;
    a.muted = next;
    setMuted(next);
  }

  return (
    <div className="border-border bg-card w-full max-w-xs overflow-hidden rounded-2xl border shadow-2xl">
      <div className="bg-muted/30 flex h-36 items-center justify-center">
        <Music className="text-muted-foreground/30 h-12 w-12" />
      </div>
      <div className="p-5">
        <p className="text-foreground mb-4 truncate text-sm font-semibold" title={name}>
          {name}
        </p>
        <div className="mb-4">
          <SeekRow
            currentTime={currentTime}
            duration={duration}
            onSeek={(t) => {
              if (audioRef.current) audioRef.current.currentTime = t;
              setCurrentTime(t);
            }}
          />
        </div>
        <div className="mb-4">
          <PlaybackButtons playing={playing} onToggle={toggle} onSeek={seek} />
        </div>
        <VolumeRow
          volume={volume}
          muted={muted}
          onVolumeChange={handleVolume}
          onToggleMute={toggleMute}
        />
      </div>
      <audio
        ref={audioRef}
        src={src}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onEnded={() => setPlaying(false)}
      />
    </div>
  );
}

// ── Видеоплеер: единое JSX-дерево, чтобы <video> не перемонтировался ─────────

/**
 * Видеоплеер для предпросмотра видеофайла.
 *
 * Поддерживает воспроизведение, паузу, перемотку,
 * управление громкостью, fullscreen-режим и poster-изображение.
 *
 * Компонент специально возвращает единое JSX-дерево:
 * элемент `<video>` остаётся в одной позиции дерева при переключении fullscreen,
 * поэтому React не размонтирует и не монтирует его заново,
 * а состояние воспроизведения сохраняется.
 */
function VideoPlayer({
  src,
  name,
  posterUrl,
}: {
  src: string;
  name: string;
  posterUrl?: string | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);
  const [videoError, setVideoError] = useState<string | null>(null);

  /**
   * Очищает таймер скрытия overlay при размонтировании.
   */
  useEffect(() => {
    return () => clearTimeout(hideTimerRef.current);
  }, []);

  /**
   * Синхронизирует состояние fullscreen с браузерным Fullscreen API.
   */
  useEffect(() => {
    function onFsChange() {
      setIsFullscreen(!!document.fullscreenElement);
    }
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  /**
   * Планирует скрытие overlay-контролов в fullscreen-режиме.
   */
  function scheduleHide() {
    clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => setShowOverlay(false), 2500);
  }

  /**
   * Переключает воспроизведение видео.
   */
  function toggle() {
    const v = videoRef.current;
    if (!v) return;
    if (playing) {
      v.pause();
    } else {
      v.play().catch(() => {});
      scheduleHide();
    }
  }

  /**
   * Перематывает видео на указанное количество секунд.
   */
  function seek(delta: number) {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + delta));
  }

  /**
   * Изменяет громкость видео.
   */
  function handleVolume(val: number) {
    setVolume(val);
    if (videoRef.current) videoRef.current.volume = val;
    setMuted(val === 0);
  }

  /**
   * Переключает mute-состояние видео.
   */
  function toggleMute() {
    const v = videoRef.current;
    if (!v) return;
    const next = !muted;
    v.muted = next;
    setMuted(next);
  }

  /**
   * Переключает fullscreen-режим.
   */
  function toggleFullscreen() {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) containerRef.current.requestFullscreen();
    else document.exitFullscreen();
  }

  const fsProgress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      ref={containerRef}
      className={cn(
        "overflow-hidden",
        isFullscreen
          ? "h-full w-full bg-black"
          : "border-border bg-card w-full max-w-md rounded-2xl border shadow-2xl",
      )}
      onMouseMove={() => {
        if (isFullscreen) {
          setShowOverlay(true);
          if (playing) scheduleHide();
        }
      }}
      onMouseLeave={() => {
        if (isFullscreen && playing) setShowOverlay(false);
      }}
    >
      {/* Область видео — всегда находится в одной позиции JSX-дерева */}
      <div
        className={cn(
          "relative cursor-pointer bg-black",
          isFullscreen ? "h-full w-full" : "aspect-video w-full",
        )}
        onClick={toggle}
      >
        <video
          ref={videoRef}
          src={src}
          poster={posterUrl ?? undefined}
          className="h-full w-full object-contain"
          onPlay={() => setPlaying(true)}
          onPause={() => {
            setPlaying(false);
            setShowOverlay(true);
            clearTimeout(hideTimerRef.current);
          }}
          onEnded={() => {
            setPlaying(false);
            setShowOverlay(true);
            clearTimeout(hideTimerRef.current);
          }}
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onError={(e) => {
            const err = e.currentTarget.error;
            const msg = err?.message ?? "";
            const isCodec =
              err?.code === 4 ||
              msg.includes("no supported streams") ||
              msg.includes("DEMUXER_ERROR");
            setVideoError(
              isCodec
                ? "Видеокодек не поддерживается браузером. Скачайте файл и откройте в плеере."
                : "Не удалось воспроизвести видео.",
            );
          }}
        />

        {videoError && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/90">
            <AlertCircle className="text-muted-foreground h-8 w-8" />
            <span className="text-muted-foreground px-6 text-center text-xs">{videoError}</span>
          </div>
        )}

        {/* Центральная кнопка play при паузе */}
        {!playing && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div
              className={cn(
                "flex items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm",
                isFullscreen ? "h-16 w-16" : "h-14 w-14",
              )}
            >
              <Play className={cn("translate-x-0.5", isFullscreen ? "h-7 w-7" : "h-6 w-6")} />
            </div>
          </div>
        )}

        {/* Overlay-контролы в fullscreen-режиме */}
        {isFullscreen && (
          <div
            className={cn(
              "absolute inset-x-0 bottom-0 bg-linear-to-t from-black/80 via-black/40 to-transparent px-5 pt-12 pb-5 transition-opacity duration-300",
              showOverlay ? "opacity-100" : "pointer-events-none opacity-0",
            )}
          >
            <div className="relative mb-3 h-1 w-full rounded-full bg-white/25">
              <div
                className="bg-primary absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${fsProgress}%` }}
              />
              <input
                type="range"
                min={0}
                max={duration || 1}
                step={0.1}
                value={currentTime}
                onChange={(e) => {
                  const t = Number(e.target.value);
                  if (videoRef.current) videoRef.current.currentTime = t;
                  setCurrentTime(t);
                }}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => seek(-10)}
                className="flex h-7 w-7 flex-col items-center justify-center text-white/70 hover:text-white"
              >
                <span className="text-[10px] leading-none font-bold">−10</span>
                <span className="text-[8px] leading-none opacity-60">с</span>
              </button>
              <button
                onClick={toggle}
                className="bg-primary text-primary-foreground flex h-8 w-8 items-center justify-center rounded-full hover:opacity-90"
              >
                {playing ? (
                  <Pause className="h-3.5 w-3.5" />
                ) : (
                  <Play className="h-3.5 w-3.5 translate-x-px" />
                )}
              </button>
              <button
                onClick={() => seek(10)}
                className="flex h-7 w-7 flex-col items-center justify-center text-white/70 hover:text-white"
              >
                <span className="text-[10px] leading-none font-bold">+10</span>
                <span className="text-[8px] leading-none opacity-60">с</span>
              </button>
              <span className="text-xs text-white/60 tabular-nums">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
              <div className="ml-auto flex items-center gap-2.5">
                <button onClick={toggleMute} className="text-white/70 hover:text-white">
                  {muted || volume === 0 ? (
                    <VolumeX className="h-4 w-4" />
                  ) : (
                    <Volume2 className="h-4 w-4" />
                  )}
                </button>
                <div className="relative h-1 w-20 rounded-full bg-white/25">
                  <div
                    className="absolute inset-y-0 left-0 rounded-full bg-white/70"
                    style={{ width: `${(muted ? 0 : volume) * 100}%` }}
                  />
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={muted ? 0 : volume}
                    onChange={(e) => handleVolume(Number(e.target.value))}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  />
                </div>
                <button onClick={toggleFullscreen} className="text-white/70 hover:text-white">
                  <Minimize2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Контролы карточки — только вне fullscreen-режима */}
      {!isFullscreen && (
        <div className="p-5">
          <p className="text-foreground mb-4 truncate text-sm font-semibold" title={name}>
            {name}
          </p>
          <div className="mb-4">
            <SeekRow
              currentTime={currentTime}
              duration={duration}
              onSeek={(t) => {
                if (videoRef.current) videoRef.current.currentTime = t;
                setCurrentTime(t);
              }}
            />
          </div>
          <div className="mb-4">
            <PlaybackButtons playing={playing} onToggle={toggle} onSeek={seek} />
          </div>
          <VolumeRow
            volume={volume}
            muted={muted}
            onVolumeChange={handleVolume}
            onToggleMute={toggleMute}
            extra={
              <button
                onClick={toggleFullscreen}
                className="text-muted-foreground hover:text-foreground ml-auto shrink-0 transition-colors"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            }
          />
        </div>
      )}
    </div>
  );
}

// ── Основная модалка ─────────────────────────────────────────────────────────

/**
 * Свойства модального окна предпросмотра файла.
 *
 * `item` — файл, который нужно открыть в предпросмотре.
 * `mimeType` — MIME-тип файла, если он уже известен снаружи.
 * `open` определяет, открыта ли модалка.
 * `onClose` закрывает модалку.
 */
interface Props {
  item: NodeListItem;
  mimeType?: string | null;
  open: boolean;
  onClose: () => void;
}

/**
 * Модальное окно предпросмотра файла.
 *
 * Поддерживает предпросмотр изображений, видео, аудио, PDF,
 * обычного текста и Markdown.
 *
 * Для текстовых и Markdown-файлов также поддерживает редактирование:
 * старый файл удаляется, после чего загружается новая версия с тем же именем.
 */
export function FilePreviewModal({ item, mimeType, open, onClose }: Props) {
  const kind = detectPreviewKind(item.name, mimeType ?? item.file_mime_type);
  const features = useFeatures();
  // Проигрывание аудио/видео может быть отключено флагом развёртывания: тогда
  // вместо плеера показываем предложение скачать файл.
  const mediaBlocked =
    (kind === "video" || kind === "audio") && !features.media_playback_enabled;
  const queryClient = useQueryClient();

  const [presignedUrl, setPresignedUrl] = useState<string | null>(null);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [posterUrl, setPosterUrl] = useState<string | null | undefined>(undefined);
  const [pdfLoaded, setPdfLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blobRef = useRef<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const videoStreamUrl = kind === "video" ? nodesApi.streamUrl(item.id) : null;

  /**
   * Загружает миниатюру для видео или аудио.
   *
   * Изображения, текст, Markdown и PDF не требуют poster-миниатюры.
   */
  useEffect(() => {
    if (
      !open ||
      !kind ||
      kind === "image" ||
      kind === "text" ||
      kind === "markdown" ||
      kind === "pdf"
    )
      return;
    let cancelled = false;
    setPosterUrl(undefined);
    nodesApi
      .thumbnail(item.id)
      .then((r) => {
        if (!cancelled) setPosterUrl(r.presigned_url);
      })
      .catch(() => {
        if (!cancelled) setPosterUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [open, item.id, kind]);

  /**
   * Загружает основной URL для предпросмотра файла.
   *
   * Для PDF дополнительно создаёт blob URL, чтобы браузер воспринимал файл
   * как `application/pdf` независимо от Content-Type, который вернул MinIO.
   *
   * Для текстовых файлов загружает содержимое как строку.
   * Видео использует same-origin stream URL и не запрашивает presigned URL.
   */
  useEffect(() => {
    if (!open || !kind) return;
    if (kind === "video") {
      setLoading(false);
      return;
    }

    setPresignedUrl(null);
    setPdfBlobUrl(null);
    setPdfError(null);
    setTextContent(null);
    setPdfLoaded(false);
    setError(null);
    setLoading(true);

    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current);
      blobRef.current = null;
    }

    // Флаг отмены: эффект асинхронный, и его продолжение может выполниться уже
    // после размонтирования/смены файла (когда cleanup отработал). Без этого
    // флага созданный ниже blob-URL присвоился бы blobRef ПОСЛЕ revoke в
    // cleanup и утёк бы навсегда.
    let cancelled = false;

    nodesApi
      .download(item.id, false)
      .then(async (resp) => {
        if (cancelled) return;
        const url = resp.presigned_url;
        setPresignedUrl(url);

        if (kind === "pdf") {
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
            // Эффект отменён, пока качался blob — немедленно освобождаем его.
            if (cancelled) {
              URL.revokeObjectURL(blobUrl);
              return;
            }
            blobRef.current = blobUrl;
            setPdfBlobUrl(blobUrl);
          } catch {
            if (!cancelled) setPdfBlobUrl(url);
          }
        } else if (kind === "text" || kind === "markdown") {
          const text = await fetch(url).then((r) => r.text());
          if (!cancelled) setTextContent(text);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message ?? "Не удалось загрузить файл");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (blobRef.current) {
        URL.revokeObjectURL(blobRef.current);
        blobRef.current = null;
      }
    };
  }, [open, item.id, kind]);

  /**
   * Сбрасывает состояние редактирования при закрытии модалки
   * или смене файла.
   */
  useEffect(() => {
    if (!open) {
      setEditing(false);
      setEditContent("");
      setSaveError(null);
    }
  }, [open, item.id]);

  /**
   * Заполняет contenteditable-редактор только при входе в режим редактирования.
   *
   * `textContent` намеренно не указан в зависимостях:
   * повторное заполнение при его изменении затёрло бы текущие правки пользователя.
   */
  useEffect(() => {
    if (!editing || !editorRef.current) return;
    editorRef.current.innerText = textContent ?? "";
    editorRef.current.focus();
  }, [editing]);

  if (!kind) return null;

  /**
   * Сохраняет изменения текстового или Markdown-файла.
   *
   * Старый файл сначала перемещается в корзину, затем создаётся upload-сессия
   * и загружается новая версия файла с тем же именем.
   */
  async function handleSave() {
    if (!item.parent_id) {
      setSaveError("Невозможно сохранить файл в корне.");
      return;
    }
    const content = editorRef.current?.innerText ?? editContent;
    if (!content.length) {
      setSaveError("Файл не может быть пустым.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const mType = kind === "markdown" ? "text/markdown" : "text/plain";
      const blob = new Blob([content], { type: mType });

      await nodesApi.softDelete(item.id);

      const session = await uploadsApi.create({
        parent_node_id: item.parent_id,
        filename: item.name,
        file_size_bytes: blob.size,
        parts_count: 1,
        mime_type: mType,
        part_size_bytes: blob.size,
      });

      const { parts } = await uploadsApi.getPresignedParts(session.id);
      const part = parts[0];

      const restricted = new Set(["content-length", "host", "connection", "transfer-encoding"]);
      const safeHeaders: Record<string, string> = {};
      for (const [k, v] of Object.entries(part.headers ?? {})) {
        if (!restricted.has(k.toLowerCase())) safeHeaders[k] = v;
      }

      const resp = await fetch(part.url, { method: "PUT", body: blob, headers: safeHeaders });
      if (!resp.ok) throw new Error(`Ошибка загрузки: ${resp.status}`);

      const etag = (resp.headers.get("ETag") ?? resp.headers.get("etag") ?? "").replace(/"/g, "");
      await uploadsApi.completePart(session.id, 1, { part_number: 1, etag, size_bytes: blob.size });
      await uploadsApi.complete(session.id, {
        upload_session_id: session.id,
        parts: [{ part_number: 1, etag, size_bytes: blob.size }],
      });

      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      onClose();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Не удалось сохранить файл.");
    } finally {
      setSaving(false);
    }
  }

  /**
   * Запускает скачивание текущего файла.
   *
   * Использует уже полученный presigned URL,
   * а если его нет — запрашивает новый URL для скачивания.
   */
  async function triggerDownload() {
    let url = presignedUrl;
    if (!url) {
      try {
        const resp = await nodesApi.download(item.id, true);
        url = resp.presigned_url;
      } catch {
        return;
      }
    }
    downloadBlobFromUrl(url, item.name);
  }

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/75" />
        <DialogPrimitive.Content
          className="fixed inset-0 z-50 flex flex-col focus:outline-none"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">{item.name}</DialogPrimitive.Title>

          {/* Заголовок */}
          <div className="border-border bg-panel flex shrink-0 items-center gap-2 border-b px-4 py-2.5">
            <span
              className="text-foreground min-w-0 flex-1 truncate text-sm font-medium"
              title={item.name}
            >
              {item.name}
            </span>

            {/* Переключение редактирования — только для загруженного text/markdown
                и только если редактирование включено флагом развёртывания. */}
            {features.file_editing_enabled &&
              (kind === "text" || kind === "markdown") &&
              textContent !== null &&
              !loading &&
              !error &&
              !editing && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  title="Редактировать"
                  onClick={() => {
                    setEditContent(textContent);
                    setEditing(true);
                    setSaveError(null);
                  }}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}

            {/* Сохранение / отмена — только в режиме редактирования */}
            {editing && (
              <>
                {saveError && (
                  <span className="text-destructive shrink-0 text-xs">{saveError}</span>
                )}
                <Button
                  size="sm"
                  className="h-8 shrink-0 gap-1.5"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                  {saving ? "Сохранение…" : "Сохранить"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 shrink-0"
                  onClick={() => {
                    setEditing(false);
                    setSaveError(null);
                  }}
                  disabled={saving}
                >
                  Отмена
                </Button>
              </>
            )}

            {!editing && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={triggerDownload}
                title="Скачать"
              >
                <Download className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={onClose}
              title="Закрыть"
              disabled={saving}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Содержимое */}
          <div className="bg-background relative flex flex-1 items-center justify-center overflow-hidden">
            {loading && <Loader2 className="text-muted-foreground h-7 w-7 animate-spin" />}

            {!loading && error && (
              <div className="text-muted-foreground flex flex-col items-center gap-2">
                <AlertCircle className="h-7 w-7" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {mediaBlocked && (
              <div className="text-muted-foreground flex flex-col items-center gap-3">
                <PlayCircle className="h-7 w-7" />
                <span className="text-sm">Проигрывание медиа отключено.</span>
                <Button variant="outline" size="sm" onClick={triggerDownload}>
                  <Download className="mr-2 h-4 w-4" /> Скачать файл
                </Button>
              </div>
            )}

            {!mediaBlocked && kind === "video" && videoStreamUrl && (
              <VideoPlayer src={videoStreamUrl} name={item.name} posterUrl={posterUrl} />
            )}

            {!loading && !error && presignedUrl && (
              <>
                {kind === "image" && <ImageViewer src={presignedUrl} alt={item.name} />}

                {!mediaBlocked && kind === "audio" && (
                  <AudioPlayer src={presignedUrl} name={item.name} />
                )}

                {kind === "pdf" && (
                  <div className="relative h-full w-full">
                    {/* Спиннер до загрузки iframe */}
                    {!pdfLoaded && !pdfError && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                        <Loader2 className="text-muted-foreground h-7 w-7 animate-spin" />
                        <span className="text-muted-foreground text-xs">Загрузка PDF…</span>
                      </div>
                    )}
                    {pdfError && (
                      <div className="text-muted-foreground absolute inset-0 flex flex-col items-center justify-center gap-3">
                        <AlertCircle className="h-7 w-7" />
                        <span className="text-sm">{pdfError}</span>
                        <a
                          href={presignedUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary flex items-center gap-1 text-sm underline underline-offset-2 hover:opacity-80"
                        >
                          <ExternalLink className="h-3.5 w-3.5" /> Открыть в новой вкладке
                        </a>
                      </div>
                    )}
                    {pdfBlobUrl && (
                      <iframe
                        src={pdfBlobUrl}
                        title={item.name}
                        className={cn("h-full w-full border-0", !pdfLoaded && "invisible")}
                        onLoad={() => setPdfLoaded(true)}
                        onError={() => setPdfError("Не удалось отобразить PDF")}
                      />
                    )}
                  </div>
                )}

                {(kind === "text" || kind === "markdown") && textContent !== null && editing && (
                  <div className="flex h-full w-full overflow-auto font-mono text-sm leading-relaxed">
                    {/* Line numbers are in the same scroll container — no sync needed */}
                    <div
                      className="border-border bg-background text-muted-foreground shrink-0 border-r px-3 py-6 text-right select-none"
                      style={{ minWidth: `${String(editContent.split("\n").length).length + 2}ch` }}
                      aria-hidden
                    >
                      {editContent.split("\n").map((_, i) => (
                        <div key={i}>{i + 1}</div>
                      ))}
                    </div>
                    <div
                      ref={editorRef}
                      contentEditable
                      suppressContentEditableWarning
                      spellCheck={false}
                      onInput={() => setEditContent(editorRef.current?.innerText ?? "")}
                      onPaste={(e) => {
                        e.preventDefault();
                        document.execCommand(
                          "insertText",
                          false,
                          e.clipboardData?.getData("text/plain") ?? "",
                        );
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Tab") {
                          e.preventDefault();
                          document.execCommand("insertText", false, "  ");
                        }
                      }}
                      className="text-foreground min-w-0 flex-1 py-6 pr-8 pl-4 wrap-break-word whitespace-pre-wrap focus:outline-none"
                    />
                  </div>
                )}

                {(kind === "text" || kind === "markdown") && textContent !== null && !editing && (
                  <div className="flex h-full w-full items-start justify-center overflow-auto p-6">
                    <div className="border-border bg-card w-full max-w-4xl rounded-xl border p-8 shadow-2xl">
                      {kind === "markdown" ? (
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            h1: ({ children }) => (
                              <h1 className="text-foreground mt-0 mb-4 text-2xl font-bold">
                                {children}
                              </h1>
                            ),
                            h2: ({ children }) => (
                              <h2 className="text-foreground mt-6 mb-3 text-xl font-semibold">
                                {children}
                              </h2>
                            ),
                            h3: ({ children }) => (
                              <h3 className="text-foreground mt-4 mb-2 text-lg font-semibold">
                                {children}
                              </h3>
                            ),
                            h4: ({ children }) => (
                              <h4 className="text-foreground mt-3 mb-1 text-base font-semibold">
                                {children}
                              </h4>
                            ),
                            p: ({ children }) => (
                              <p className="text-foreground mb-3 leading-relaxed">{children}</p>
                            ),
                            ul: ({ children }) => (
                              <ul className="text-foreground mb-3 list-disc pl-5">{children}</ul>
                            ),
                            ol: ({ children }) => (
                              <ol className="text-foreground mb-3 list-decimal pl-5">{children}</ol>
                            ),
                            li: ({ children }) => <li className="mb-1">{children}</li>,
                            pre: ({ children }) => (
                              <pre className="bg-muted mb-3 overflow-x-auto rounded-lg p-4">
                                {children}
                              </pre>
                            ),
                            code: ({ className, children, ...props }) => {
                              const isBlock = !!className?.startsWith("language-");
                              return isBlock ? (
                                <code
                                  className="text-foreground block font-mono text-xs leading-relaxed"
                                  {...props}
                                >
                                  {children}
                                </code>
                              ) : (
                                <code
                                  className="bg-muted text-foreground rounded px-1.5 py-0.5 font-mono text-xs"
                                  {...props}
                                >
                                  {children}
                                </code>
                              );
                            },
                            blockquote: ({ children }) => (
                              <blockquote className="border-primary/40 text-muted-foreground mb-3 border-l-4 pl-4 italic">
                                {children}
                              </blockquote>
                            ),
                            a: ({ href, children }) => (
                              <a
                                href={href}
                                className="text-primary underline underline-offset-2 hover:opacity-80"
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {children}
                              </a>
                            ),
                            hr: () => <hr className="border-border my-6" />,
                            table: ({ children }) => (
                              <div className="border-border mb-3 overflow-x-auto rounded-lg border">
                                <table className="w-full border-collapse text-sm">{children}</table>
                              </div>
                            ),
                            th: ({ children }) => (
                              <th className="border-border bg-muted text-muted-foreground border-b px-4 py-2 text-left text-xs font-semibold tracking-wide uppercase">
                                {children}
                              </th>
                            ),
                            td: ({ children }) => (
                              <td className="border-border text-foreground border-b px-4 py-2 last:border-b-0">
                                {children}
                              </td>
                            ),
                          }}
                        >
                          {textContent}
                        </ReactMarkdown>
                      ) : (
                        <div className="text-foreground flex font-mono text-xs leading-relaxed">
                          <div
                            className="border-border text-muted-foreground shrink-0 border-r pr-3 text-right select-none"
                            style={{
                              minWidth: `${String(textContent.split("\n").length).length + 2}ch`,
                            }}
                            aria-hidden
                          >
                            {textContent.split("\n").map((_, i) => (
                              <div key={i}>{i + 1}</div>
                            ))}
                          </div>
                          <div className="min-w-0 flex-1 pl-4">
                            {textContent.split("\n").map((line, i) => (
                              <div key={i} className="wrap-break-word whitespace-pre-wrap">
                                {line || " "}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
