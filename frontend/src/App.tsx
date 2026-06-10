import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/contexts/auth";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { LoginPage } from "@/pages/Login";
import { RegisterPage } from "@/pages/Register";
import { FilesPage } from "@/pages/Files";
import { TrashPage } from "@/pages/Trash";
import { SharedPage } from "@/pages/Shared";
import { SharePage } from "@/pages/Share";
import { AdminLayout } from "@/pages/admin/AdminLayout";
import { UsersPage } from "@/pages/admin/UsersPage";
import { RegistrationPage } from "@/pages/admin/RegistrationPage";
import { AuditPage } from "@/pages/admin/AuditPage";
import { TasksPage } from "@/pages/admin/TasksPage";
import { AppShell } from "@/components/layout/AppShell";

function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Публичные маршруты */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/share/:token" element={<SharePage />} />

        {/* Protected — all wrapped in AppShell */}
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="/files" element={<FilesPage />} />
          <Route path="/files/folders/:nodeId" element={<FilesPage />} />
          <Route path="/shared" element={<SharedPage />} />
          <Route path="/trash" element={<TrashPage />} />

          {/* Административные маршруты */}
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="/admin/users" replace />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="registration" element={<RegistrationPage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="tasks" element={<TasksPage />} />
          </Route>
        </Route>

        {/* Основные маршруты */}
        <Route path="/" element={<Navigate to="/files" replace />} />
        <Route
          path="*"
          element={<p className="text-muted-foreground p-6">404 — Страница не найдена</p>}
        />
      </Routes>
    </AuthProvider>
  );
}

export default App;
