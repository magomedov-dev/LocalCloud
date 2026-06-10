import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { AuthContextValue } from "@/contexts/auth-context";
import { ProtectedRoute } from "./ProtectedRoute";

const authState = vi.hoisted(() => ({
  value: {
    user: null,
    isLoading: false,
    isAuthenticated: false,
    login: vi.fn(),
    logout: vi.fn(),
  } as AuthContextValue,
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => authState.value,
}));

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={["/secret"]}>
      <Routes>
        <Route
          path="/secret"
          element={
            <ProtectedRoute>
              <div>Секретное содержимое</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<div>Страница входа</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    authState.value = {
      user: null,
      isLoading: false,
      isAuthenticated: false,
      login: vi.fn(),
      logout: vi.fn(),
    };
  });

  it("показывает индикатор загрузки при isLoading", () => {
    authState.value.isLoading = true;
    const { container } = renderRoute();
    expect(screen.queryByText("Секретное содержимое")).not.toBeInTheDocument();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("рендерит children для авторизованного пользователя", () => {
    authState.value.isAuthenticated = true;
    renderRoute();
    expect(screen.getByText("Секретное содержимое")).toBeInTheDocument();
  });

  it("перенаправляет на /login для неавторизованного пользователя", () => {
    authState.value.isAuthenticated = false;
    renderRoute();
    expect(screen.queryByText("Секретное содержимое")).not.toBeInTheDocument();
    expect(screen.getByText("Страница входа")).toBeInTheDocument();
  });
});
