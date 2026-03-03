import { useQuery } from "@tanstack/react-query";
import {
  Link,
  NavLink,
  Outlet,
  useParams,
} from "react-router-dom";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";

interface ProjectDetail {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  created_at: string;
}

const navItems = [
  { label: "Overview", to: "" },
  { label: "Data", to: "data" },
  { label: "Pipeline", to: "pipeline" },
  { label: "Annotations", to: "annotations" },
  { label: "Evaluation", to: "evaluation" },
  { label: "Export", to: "export" },
];

export default function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();
  const { logout } = useAuth();

  const {
    data: project,
    isLoading,
    error,
  } = useQuery<ProjectDetail>({
    queryKey: ["project", projectId],
    queryFn: () => api.get<ProjectDetail>(`/projects/${projectId}`),
    enabled: !!projectId,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading project...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-destructive">
          Failed to load project: {error instanceof Error ? error.message : "Unknown error"}
        </p>
        <Button variant="outline" asChild>
          <Link to="/projects">Back to Projects</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Link
              to="/projects"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Projects
            </Link>
            <span className="text-muted-foreground">/</span>
            <h1 className="text-lg font-semibold">
              {project?.name ?? "Project"}
            </h1>
          </div>
          <Button variant="ghost" size="sm" onClick={logout}>
            Sign out
          </Button>
        </div>
      </header>

      <nav className="border-b">
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-6">
          {navItems.map((item) => (
            <NavLink
              key={item.label}
              to={item.to}
              end={item.to === ""}
              className={({ isActive }) =>
                `whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet context={{ project }} />
      </main>
    </div>
  );
}
