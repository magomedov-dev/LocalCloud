import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";
import { AdminLayout } from "./AdminLayout";

describe("AdminLayout", () => {
  it("renders heading and all nav tabs with correct hrefs", () => {
    renderWithProviders(<AdminLayout />, { routerEntries: ["/admin/users"] });

    expect(screen.getByRole("heading", { name: "Администрирование" })).toBeInTheDocument();
    expect(screen.getByText("Управление пользователями и системой")).toBeInTheDocument();

    const tabs: [string, string][] = [
      ["Пользователи", "/admin/users"],
      ["Заявки", "/admin/registration"],
      ["Аудит", "/admin/audit"],
      ["Задачи", "/admin/tasks"],
    ];
    for (const [label, href] of tabs) {
      const link = screen.getByRole("link", { name: label });
      expect(link).toHaveAttribute("href", href);
    }
  });

  it("renders the nested route Outlet content", () => {
    renderWithProviders(
      <Routes>
        <Route path="/admin" element={<AdminLayout />}>
          <Route path="users" element={<div>USERS_OUTLET</div>} />
        </Route>
      </Routes>,
      { routerEntries: ["/admin/users"] },
    );

    expect(screen.getByText("USERS_OUTLET")).toBeInTheDocument();
  });
});
