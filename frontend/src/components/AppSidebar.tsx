import { NavLink, useParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import {
  LayoutDashboard,
  Database,
  Users,
  MessageSquareText,
  BarChart3,
  Download,
  LogOut,
  FolderOpen,
  Moon,
  Sun,
  Activity,
} from "lucide-react";
import { useEffect, useState } from "react";

const projectNavSections = [
  { label: "Overview", suffix: "", icon: LayoutDashboard, end: true },
  { label: "Data", suffix: "/data", icon: Database },
  { label: "Patients", suffix: "/patients", icon: Users },
  { label: "Evaluation", suffix: "/evaluation", icon: BarChart3 },
  { label: "Jobs", suffix: "/jobs", icon: Activity },
  { label: "Annotations", suffix: "/annotations", icon: MessageSquareText },
  { label: "Export", suffix: "/export", icon: Download },
];

function useDarkMode() {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark")
  );

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [dark]);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "dark") {
      setDark(true);
    } else if (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setDark(true);
    }
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem("theme")) {
        setDark(e.matches);
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return [dark, setDark] as const;
}

export default function AppSidebar() {
  const { user, logout } = useAuth();
  const { projectId } = useParams();
  const [dark, setDark] = useDarkMode();

  return (
    <aside className="flex h-screen w-56 flex-col bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 py-5">
        <img
          src="/cedars-logo.png"
          alt="CEDARS"
          className="h-8 w-8 brightness-0 invert opacity-90"
        />
        <span className="text-lg font-semibold tracking-tight">CEDARS</span>
      </div>

      <div className="mx-3 border-t border-sidebar-border" />

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {projectId ? (
          <>
            <NavLink
              to="/projects"
              className="mb-3 flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            >
              <FolderOpen className="h-4 w-4" />
              All Projects
            </NavLink>
            <div className="mb-2 px-2.5 text-xs font-medium uppercase tracking-wider text-sidebar-foreground/40">
              Project
            </div>
            {projectNavSections.map((item) => (
              <NavLink
                key={item.label}
                to={`/projects/${projectId}${item.suffix}`}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors ${
                    isActive
                      ? "bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                      : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                  }`
                }
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            ))}
          </>
        ) : (
          <NavLink
            to="/projects"
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              }`
            }
          >
            <FolderOpen className="h-4 w-4" />
            Projects
          </NavLink>
        )}
      </nav>

      {/* Footer */}
      <div className="mx-3 border-t border-sidebar-border" />
      <div className="space-y-1 px-3 py-3">
        <button
          onClick={() => setDark(!dark)}
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          {dark ? "Light mode" : "Dark mode"}
        </button>
        <div className="flex items-center gap-2.5 px-2.5 py-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-sidebar-primary text-[10px] font-bold text-sidebar-primary-foreground">
            {user?.name?.charAt(0).toUpperCase() ?? "?"}
          </div>
          <div className="flex-1 truncate text-xs text-sidebar-foreground/70">
            {user?.name ?? user?.email}
          </div>
          <button
            onClick={logout}
            title="Sign out"
            aria-label="Sign out"
            className="rounded p-1 text-sidebar-foreground/40 transition-colors hover:text-sidebar-foreground"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
