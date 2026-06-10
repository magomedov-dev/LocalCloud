import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";

vi.mock("@/api/public-links", () => ({
  publicLinksApi: {
    getPublic: vi.fn(),
    validateAccess: vi.fn(),
    download: vi.fn(),
    startFolderArchive: vi.fn(),
    pollFolderArchive: vi.fn(),
  },
}));

const downloadBlobFromUrl = vi.fn();
vi.mock("@/lib/download", () => ({
  downloadBlobFromUrl: (...args: unknown[]) => downloadBlobFromUrl(...args),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

import { publicLinksApi } from "@/api/public-links";
import { toast } from "sonner";
import { SharePage } from "./Share";

const getPublic = vi.mocked(publicLinksApi.getPublic);
const validateAccess = vi.mocked(publicLinksApi.validateAccess);
const download = vi.mocked(publicLinksApi.download);
const startFolderArchive = vi.mocked(publicLinksApi.startFolderArchive);
const pollFolderArchive = vi.mocked(publicLinksApi.pollFolderArchive);

function makeLink(overrides: Record<string, unknown> = {}) {
  return {
    token: "tok",
    status: "active",
    has_password: false,
    expires_at: null,
    description: null,
    node: { id: "n1", name: "report.pdf", node_type: "file", file_mime_type: "application/pdf" },
    ...overrides,
  };
}

function renderShare(token = "tok123") {
  return renderWithProviders(
    <Routes>
      <Route path="/share/:token" element={<SharePage />} />
    </Routes>,
    { routerEntries: [`/share/${token}`] },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("SharePage", () => {
  it("shows loading skeletons", () => {
    getPublic.mockReturnValue(new Promise(() => {}) as never);
    const { container } = renderShare();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows error when link is unavailable", async () => {
    getPublic.mockRejectedValue(new Error("404"));
    renderShare();
    expect(await screen.findByText("Ссылка недоступна")).toBeInTheDocument();
  });

  it("shows error when link status is not active", async () => {
    getPublic.mockResolvedValue(makeLink({ status: "revoked" }) as never);
    renderShare();
    expect(await screen.findByText("Ссылка недоступна")).toBeInTheDocument();
  });

  it("renders a file and downloads it", async () => {
    getPublic.mockResolvedValue(makeLink() as never);
    download.mockResolvedValue({
      presigned_url: "https://x/file",
      filename: "report.pdf",
      size_bytes: 1024,
    } as never);
    const user = userEvent.setup();
    renderShare();

    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    await waitFor(() =>
      expect(downloadBlobFromUrl).toHaveBeenCalledWith("https://x/file", "report.pdf"),
    );
  });

  it("prompts for a password and rejects the wrong one", async () => {
    getPublic.mockResolvedValue(makeLink({ has_password: true }) as never);
    validateAccess.mockResolvedValue({ allowed: false, message: "Неверный пароль" } as never);
    const user = userEvent.setup();
    renderShare();

    expect(await screen.findByText("Ссылка защищена паролем")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Пароль"), "wrong");
    await user.click(screen.getByRole("button", { name: "Открыть" }));

    await waitFor(() => expect(validateAccess).toHaveBeenCalledWith("tok123", "wrong"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Неверный пароль"));
    // Still locked.
    expect(screen.getByText("Ссылка защищена паролем")).toBeInTheDocument();
  });

  it("unlocks with the correct password and reveals the file", async () => {
    getPublic.mockResolvedValue(makeLink({ has_password: true }) as never);
    validateAccess.mockResolvedValue({ allowed: true } as never);
    download.mockResolvedValue({
      presigned_url: "https://x/file",
      filename: "report.pdf",
      size_bytes: 10,
    } as never);
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("Ссылка защищена паролем");
    await user.type(screen.getByPlaceholderText("Пароль"), "right");
    await user.click(screen.getByRole("button", { name: "Открыть" }));

    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    await waitFor(() => expect(download).toHaveBeenCalledWith("tok123", "right"));
  });

  it("shows an error toast when password validation throws", async () => {
    getPublic.mockResolvedValue(makeLink({ has_password: true }) as never);
    validateAccess.mockRejectedValue(new Error("network"));
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("Ссылка защищена паролем");
    await user.type(screen.getByPlaceholderText("Пароль"), "x");
    await user.click(screen.getByRole("button", { name: "Открыть" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось проверить пароль"),
    );
  });

  it("downloads a folder archive that completes immediately", async () => {
    getPublic.mockResolvedValue(
      makeLink({ node: { id: "f1", name: "docs", node_type: "folder" } }) as never,
    );
    startFolderArchive.mockResolvedValue({
      task_id: "t1",
      status: "completed",
      presigned_url: "https://x/archive.zip",
      filename: "docs.zip",
    } as never);
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("docs");
    await user.click(screen.getByRole("button", { name: /Скачать как ZIP/ }));

    await waitFor(() =>
      expect(downloadBlobFromUrl).toHaveBeenCalledWith("https://x/archive.zip", "docs.zip"),
    );
  });

  it("polls a folder archive until completion", async () => {
    getPublic.mockResolvedValue(
      makeLink({ node: { id: "f1", name: "docs", node_type: "folder" } }) as never,
    );
    startFolderArchive.mockResolvedValue({ task_id: "t1", status: "in_progress" } as never);
    pollFolderArchive.mockResolvedValue({
      task_id: "t1",
      status: "completed",
      presigned_url: "https://x/archive.zip",
      filename: "docs.zip",
    } as never);
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("docs");
    await user.click(screen.getByRole("button", { name: /Скачать как ZIP/ }));
    await waitFor(() => expect(startFolderArchive).toHaveBeenCalled());

    // The poll fires on a real 2000ms timer.
    await waitFor(() => expect(pollFolderArchive).toHaveBeenCalledWith("tok123", "t1"), {
      timeout: 4000,
    });
    await waitFor(() =>
      expect(downloadBlobFromUrl).toHaveBeenCalledWith("https://x/archive.zip", "docs.zip"),
    );
  });

  it("reports a failed folder archive while polling", async () => {
    getPublic.mockResolvedValue(
      makeLink({ node: { id: "f1", name: "docs", node_type: "folder" } }) as never,
    );
    startFolderArchive.mockResolvedValue({ task_id: "t1", status: "in_progress" } as never);
    pollFolderArchive.mockResolvedValue({ task_id: "t1", status: "failed" } as never);
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("docs");
    await user.click(screen.getByRole("button", { name: /Скачать как ZIP/ }));
    await waitFor(() => expect(startFolderArchive).toHaveBeenCalled());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Не удалось создать архив папки"), {
      timeout: 4000,
    });
  });

  it("reports a failure when starting the archive throws", async () => {
    getPublic.mockResolvedValue(
      makeLink({ node: { id: "f1", name: "docs", node_type: "folder" } }) as never,
    );
    startFolderArchive.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderShare();

    await screen.findByText("docs");
    await user.click(screen.getByRole("button", { name: /Скачать как ZIP/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось начать создание архива"),
    );
  });
});
