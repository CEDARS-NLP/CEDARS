import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Plus, FolderOpen } from "lucide-react";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface Project {
  id: string;
  name: string;
  description: string;
  owner: string;
  role: string;
  created_at: string;
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case "owner":
      return "bg-primary/10 text-primary dark:bg-primary/20";
    case "admin":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300";
    case "annotator":
      return "bg-link/10 text-link dark:bg-link/20";
    default:
      return "bg-secondary text-secondary-foreground";
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ProjectListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const {
    data: projects,
    isLoading,
    error,
  } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });

  return (
    <div className="px-8 py-8">
      {/* Page header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage your clinical event detection projects
          </p>
        </div>
        {user?.is_admin && (
          <Button asChild>
            <Link to="/projects/new">
              <Plus className="mr-1.5 h-4 w-4" />
              New project
            </Link>
          </Button>
        )}
      </div>
      <div aria-live="polite">
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <p className="text-muted-foreground">Loading projects...</p>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Failed to load projects:{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-16">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
            <FolderOpen className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="mb-1 text-lg font-medium text-foreground">
            No projects yet
          </p>
          <p className="mb-6 text-sm text-muted-foreground">
            Create your first project to get started.
          </p>
          <Button asChild>
            <Link to="/projects/new">
              <Plus className="mr-1.5 h-4 w-4" />
              Create project
            </Link>
          </Button>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              className="cursor-pointer border-border/60 transition-all hover:border-accent/40 hover:shadow-md focus-within:ring-2 focus-within:ring-ring"
              tabIndex={0}
              role="link"
              aria-label={project.name}
              onClick={() => navigate(`/projects/${project.id}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/projects/${project.id}`);
                }
              }}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base leading-snug">
                    {project.name}
                  </CardTitle>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${roleBadgeClass(project.role)}`}
                  >
                    {project.role}
                  </span>
                </div>
                <CardDescription className="line-clamp-2">
                  {project.description || "No description"}
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0">
                <p className="text-xs text-muted-foreground">
                  Created {formatDate(project.created_at)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
