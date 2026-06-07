// Определение типа предпросмотра: чистые helper-функции вынесены из FilePreviewModal,
// чтобы файл компонента экспортировал только компоненты (react-refresh/only-export-components).

export type PreviewKind = "image" | "video" | "audio" | "pdf" | "text" | "markdown";

// Расширения, содержимое которых всегда считается человекочитаемым текстом.
// Для файлов без расширения (Dockerfile, Makefile и т. п.) name.split(".").pop()
// возвращает полное имя файла в нижнем регистре — оно также проверяется здесь.
const TEXT_EXTENSIONS = new Set([
  // Обычный текст / документы
  "txt",
  "log",
  "rst",
  "adoc",
  "tex",
  "csv",
  "tsv",
  "diff",
  "patch",
  "ics",
  "vcf",
  // Web
  "html",
  "htm",
  "css",
  "scss",
  "sass",
  "less",
  // Данные и конфигурация
  "json",
  "jsonc",
  "json5",
  "yaml",
  "yml",
  "toml",
  "ini",
  "cfg",
  "conf",
  "properties",
  "env",
  "lock",
  "plist",
  // Семейство XML
  "xml",
  "xsl",
  "xslt",
  "rss",
  "atom",
  // Shell-скрипты
  "sh",
  "bash",
  "zsh",
  "fish",
  "ps1",
  "bat",
  "cmd",
  // JavaScript / TypeScript
  "js",
  "mjs",
  "cjs",
  "ts",
  "jsx",
  "tsx",
  // Web-фреймворки
  "vue",
  "svelte",
  "astro",
  // Python
  "py",
  "pyw",
  "pyi",
  // Ruby
  "rb",
  "rake",
  "gemspec",
  "gemfile",
  "rakefile",
  // Go
  "go",
  // Rust
  "rs",
  // JVM
  "java",
  "kt",
  "kts",
  "groovy",
  "scala",
  // C подобные
  "c",
  "h",
  "cpp",
  "cc",
  "cxx",
  "hpp",
  "hxx",
  "cs",
  // Другие языки
  "php",
  "swift",
  "dart",
  "lua",
  "r",
  "jl",
  "ex",
  "exs",
  "hs",
  "elm",
  "clj",
  "cljs",
  "ml",
  "mli",
  "fs",
  "fsx",
  "fsi",
  "pl",
  "pm",
  // Запросы / схемы
  "sql",
  "psql",
  "graphql",
  "gql",
  // DevOps / сборка
  "dockerfile",
  "makefile",
  "vagrantfile",
  "procfile",
  "brewfile",
  "jenkinsfile",
  "cmake",
  "tf",
  "tfvars",
  "hcl",
  "gradle",
  "bazel",
  "bzl",
  // Dotfiles: расширение — это часть после последней точки
  // или полное имя файла, если точки нет.
  "gitignore",
  "gitattributes",
  "gitmodules",
  "npmignore",
  "dockerignore",
  "editorconfig",
  "eslintrc",
  "prettierrc",
  "babelrc",
  "stylelintrc",
  "huskyrc",
  "lintstagedrc",
]);

// MIME-типы application/*, содержимое которых является обычным текстом.
const TEXT_APP_MIME = new Set([
  "application/json",
  "application/ld+json",
  "application/manifest+json",
  "application/geo+json",
  "application/xml",
  "application/xhtml+xml",
  "application/atom+xml",
  "application/rss+xml",
  "application/javascript",
  "application/ecmascript",
  "application/typescript",
  "application/x-yaml",
  "application/x-sh",
  "application/x-httpd-php",
  "application/sql",
  "application/graphql",
]);

/**
 * Определяет тип предпросмотра файла.
 *
 * Возвращает тип предпросмотра на основе имени файла, расширения и MIME-типа.
 * Поддерживает изображения, видео, аудио, PDF, текстовые файлы и Markdown.
 *
 * Если файл не поддерживается для предпросмотра, возвращает `null`.
 */
export function detectPreviewKind(name: string, mimeType?: string | null): PreviewKind | null {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";

  // Если расширение известно как текстовый формат,
  // пропускаем MIME-проверку на бинарные типы.
  //
  // Это решает неоднозначные случаи вроде .ts:
  // TypeScript против MPEG-TS / video/mp2t.
  const knownTextExt = TEXT_EXTENSIONS.has(ext);

  if (!knownTextExt) {
    if (mimeType?.startsWith("image/")) return "image";
    if (mimeType?.startsWith("video/")) return "video";
    if (mimeType?.startsWith("audio/")) return "audio";
    if (mimeType === "application/pdf") return "pdf";
  }

  // Проверки по расширению имеют приоритет
  // для этих конкретных форматов.
  if (["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"].includes(ext)) return "image";
  if (["mp4", "webm", "ogv", "mov", "mkv"].includes(ext)) return "video";
  if (["mp3", "wav", "ogg", "flac", "aac", "m4a", "opus"].includes(ext)) return "audio";
  if (ext === "pdf") return "pdf";
  if (
    ["md", "mdx", "markdown"].includes(ext) ||
    mimeType === "text/markdown" ||
    mimeType === "text/x-markdown"
  )
    return "markdown";

  const isTextMime = !!mimeType && (mimeType.startsWith("text/") || TEXT_APP_MIME.has(mimeType));
  if (knownTextExt || isTextMime) return "text";

  return null;
}
