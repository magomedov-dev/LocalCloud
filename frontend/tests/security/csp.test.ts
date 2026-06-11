import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

// Гард против рассинхрона: CSP-хэш инлайн-скрипта в gateway nginx должен
// совпадать с реальным содержимым frontend/index.html. Иначе при правке
// бутстрап-скрипта темы CSP молча заблокировал бы его (тёмная тема при
// загрузке перестала бы применяться). Тест ловит это до деплоя.

const FRONTEND_ROOT = process.cwd();
const NGINX_DIR = resolve(FRONTEND_ROOT, "..", "nginx");
const NGINX_CONF = resolve(NGINX_DIR, "nginx.conf");
const NGINX_TLS_CONF = resolve(NGINX_DIR, "nginx-tls.conf.example");
const INDEX_HTML = resolve(FRONTEND_ROOT, "index.html");

function inlineThemeScript(html: string): string {
  // Первый <script> без атрибутов — бутстрап темы.
  const match = html.match(/<script>\n([\s\S]*?)<\/script>/);
  if (!match) throw new Error("Инлайн-скрипт темы не найден в index.html");
  return match[1];
}

function expectedScriptHash(): string {
  const html = readFileSync(INDEX_HTML, "utf-8");
  return createHash("sha256").update(inlineThemeScript(html), "utf-8").digest("base64");
}

describe("Content-Security-Policy", () => {
  // Оба конфига шлюза (HTTP и TLS-пример) должны нести один и тот же хэш
  // инлайн-скрипта темы — иначе правка index.html молча сломает одну из веток.
  it.each([
    ["nginx.conf", NGINX_CONF],
    ["nginx-tls.conf.example", NGINX_TLS_CONF],
  ])("script-src hash in %s matches the inline theme script", (name, path) => {
    const expected = expectedScriptHash();
    const conf = readFileSync(path, "utf-8");
    const cspHashes = [...conf.matchAll(/'sha256-([A-Za-z0-9+/=]+)'/g)].map((m) => m[1]);

    expect(
      cspHashes,
      `CSP в ${name} должен содержать sha256-${expected} ` +
        "(обновите хэш после изменения инлайн-скрипта темы)",
    ).toContain(expected);
  });

  it("gateway sets the core security headers", () => {
    const conf = readFileSync(NGINX_CONF, "utf-8");
    expect(conf).toMatch(/add_header\s+X-Frame-Options\s+"DENY"\s+always/);
    expect(conf).toMatch(/add_header\s+X-Content-Type-Options\s+"nosniff"\s+always/);
    expect(conf).toMatch(/add_header\s+Referrer-Policy\s+"no-referrer"\s+always/);
    expect(conf).toMatch(/add_header\s+Content-Security-Policy[\s\S]*frame-ancestors 'none'/);
  });

  it("TLS example adds HSTS", () => {
    const conf = readFileSync(NGINX_TLS_CONF, "utf-8");
    expect(conf).toMatch(/add_header\s+Strict-Transport-Security[\s\S]*max-age=\d+/);
  });
});
