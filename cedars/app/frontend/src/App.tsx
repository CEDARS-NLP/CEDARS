import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider } from "antd";
import { getDsmTheme } from "@mskcc/theme-antd";
import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import LoginPage from "@/auth/LoginPage";
import RegisterPage from "@/auth/RegisterPage";
import AppLayout from "@/components/AppLayout";
import ProjectListPage from "@/projects/ProjectListPage";
import CreateProjectPage from "@/projects/CreateProjectPage";
import ProjectLayout from "@/projects/ProjectLayout";
import ProjectHome from "@/projects/ProjectHome";
import DataPage from "@/projects/DataPage";
import QueryPage from "@/projects/QueryPage";
import AdjudicatePage from "@/projects/AdjudicatePage";
import StatsPage from "@/projects/StatsPage";
import ExportPage from "@/projects/ExportPage";
import InternalProcessesPage from "@/projects/InternalProcessesPage";
import ProjectDetailsPage from "@/projects/ProjectDetailsPage";
import AboutPage from "@/projects/AboutPage";

const queryClient = new QueryClient();

function useThemeMode(): "light" | "dark" {
  // index.html inline script sets data-theme before React mounts — read it directly
  const [scheme, setScheme] = React.useState<"light" | "dark">(() =>
    document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"
  );

  React.useEffect(() => {
    // Watch for data-theme attribute changes driven by the sidebar toggle
    const observer = new MutationObserver(() => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
      setScheme(next);
    });
    observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  return scheme;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function GuestRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/projects" replace />;
  }

  return children;
}

export default function App() {
  const colorScheme = useThemeMode();
  const antdTheme = getDsmTheme("pro", colorScheme);

  return (
    <ConfigProvider theme={antdTheme}>
      <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Auth routes — no sidebar */}
            <Route
              path="/login"
              element={
                <GuestRoute>
                  <LoginPage />
                </GuestRoute>
              }
            />
            <Route
              path="/register"
              element={
                <GuestRoute>
                  <RegisterPage />
                </GuestRoute>
              }
            />

            {/* App routes — with sidebar */}
            <Route
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<Navigate to="/projects" replace />} />
              <Route path="/projects" element={<ProjectListPage />} />
              <Route path="/projects/new" element={<CreateProjectPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/projects/:projectId" element={<ProjectLayout />}>
                <Route index element={<ProjectHome />} />
                <Route path="data" element={<DataPage />} />
                <Route path="query" element={<QueryPage />} />
                <Route path="adjudicate" element={<AdjudicatePage />} />
                <Route path="stats" element={<StatsPage />} />
                <Route path="export" element={<ExportPage />} />
                <Route path="internal" element={<InternalProcessesPage />} />
                <Route path="details" element={<ProjectDetailsPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
    </ConfigProvider>
  );
}
