import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
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
  owner_id: string;
  role: string;
  created_at: string;
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case "owner":
      return "bg-primary/10 text-primary";
    case "admin":
      return "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400";
    case "annotator":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
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
  const { user, logout } = useAuth();

  const {
    data: projects,
    isLoading,
    error,
  } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  });

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold">CEDARS</h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              {user?.name ?? user?.email}
            </span>
            <Button variant="ghost" size="sm" onClick={logout}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Projects</h2>
            <p className="text-sm text-muted-foreground">
              Manage your clinical event detection projects
            </p>
          </div>
          <Button asChild>
            <Link to="/projects/new">
              <Plus />
              New Project
            </Link>
          </Button>
        </div>

        {isLoading && (
          <p className="text-muted-foreground">Loading projects...</p>
        )}

        {error && (
          <p className="text-sm text-destructive">
            Failed to load projects: {error instanceof Error ? error.message : "Unknown error"}
          </p>
        )}

        {projects && projects.length === 0 && (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <p className="mb-2 text-lg font-medium">No projects yet</p>
              <p className="mb-6 text-sm text-muted-foreground">
                Create your first project to get started with clinical event detection.
              </p>
              <Button asChild>
                <Link to="/projects/new">
                  <Plus />
                  Create Project
                </Link>
              </Button>
            </CardContent>
          </Card>
        )}

        {projects && projects.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <Card
                key={project.id}
                className="cursor-pointer transition-shadow hover:shadow-md"
                onClick={() => navigate(`/projects/${project.id}`)}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-lg">{project.name}</CardTitle>
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${roleBadgeClass(project.role)}`}
                    >
                      {project.role}
                    </span>
                  </div>
                  <CardDescription>
                    {project.description || "No description"}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Created {formatDate(project.created_at)}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
