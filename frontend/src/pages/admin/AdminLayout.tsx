import { NavLink, Outlet } from "react-router-dom";
import { Users, ClipboardList, ScrollText, ListTodo } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "/admin/users", label: "Пользователи", icon: Users },
  { to: "/admin/registration", label: "Заявки", icon: ClipboardList },
  { to: "/admin/audit", label: "Аудит", icon: ScrollText },
  { to: "/admin/tasks", label: "Задачи", icon: ListTodo },
];

export function AdminLayout() {
  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-semibold">Администрирование</h1>
        <p className="text-muted-foreground text-sm">Управление пользователями и системой</p>
      </div>

      <nav className="flex w-fit gap-1 rounded-lg border p-1">
        {TABS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  );
}
