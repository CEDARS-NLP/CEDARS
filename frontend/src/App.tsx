import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import LoginPage from "@/auth/LoginPage";
import RegisterPage from "@/auth/RegisterPage";
import AppLayout from "@/components/AppLayout";
import ProjectListPage from "@/projects/ProjectListPage";
import CreateProjectPage from "@/projects/CreateProjectPage";
import ProjectLayout from "@/projects/ProjectLayout";
import ProjectOverview from "@/projects/ProjectOverview";
import DataPage from "@/projects/DataPage";
import PipelinePage from "@/projects/PipelinePage";
import AnnotationsPage from "@/projects/AnnotationsPage";
import EvaluationPage from "@/projects/EvaluationPage";
import ExportPage from "@/projects/ExportPage";

const queryClient = new QueryClient();

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
  return (
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
              <Route path="/projects/:projectId" element={<ProjectLayout />}>
                <Route index element={<ProjectOverview />} />
                <Route path="data" element={<DataPage />} />
                <Route path="pipeline" element={<PipelinePage />} />
                <Route path="annotations" element={<AnnotationsPage />} />
                <Route path="evaluation" element={<EvaluationPage />} />
                <Route path="export" element={<ExportPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
