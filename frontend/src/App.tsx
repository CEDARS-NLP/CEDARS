import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import LoginPage from "@/auth/LoginPage";
import RegisterPage from "@/auth/RegisterPage";
import ProjectListPage from "@/projects/ProjectListPage";
import CreateProjectPage from "@/projects/CreateProjectPage";
import ProjectLayout from "@/projects/ProjectLayout";
import ProjectOverview from "@/projects/ProjectOverview";
import PlaceholderSection from "@/projects/PlaceholderSection";

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
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
      <div className="flex items-center justify-center min-h-screen">
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
            {/* Redirect root to projects */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Navigate to="/projects" replace />
                </ProtectedRoute>
              }
            />

            {/* Project routes */}
            <Route
              path="/projects"
              element={
                <ProtectedRoute>
                  <ProjectListPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/projects/new"
              element={
                <ProtectedRoute>
                  <CreateProjectPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/projects/:projectId"
              element={
                <ProtectedRoute>
                  <ProjectLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<ProjectOverview />} />
              <Route path="data" element={<PlaceholderSection title="Data" />} />
              <Route path="pipeline" element={<PlaceholderSection title="Pipeline" />} />
              <Route path="annotations" element={<PlaceholderSection title="Annotations" />} />
              <Route path="evaluation" element={<PlaceholderSection title="Evaluation" />} />
              <Route path="export" element={<PlaceholderSection title="Export" />} />
            </Route>

            {/* Auth routes */}
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
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
