import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";

export interface ProjectDetail {
  id: string;
  name: string;
  description: string;
  owner: string;
  role: string;
  created_at: string;
}

export default function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();

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
      <div className="flex h-full items-center justify-center" aria-live="polite">
        <p className="text-muted-foreground">Loading project...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-destructive">
          Failed to load project:{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
        <Button variant="outline" asChild>
          <Link to="/projects">Back to projects</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="h-full">
      {/* Project header bar */}
      <div className="border-b border-border bg-card px-8 py-5">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Link to="/projects" className="hover:text-foreground transition-colors">
            Projects
          </Link>
          <span>/</span>
          <span className="font-medium text-foreground">
            {project?.name ?? "Project"}
          </span>
        </div>
        {project?.description && (
          <p className="mt-1 text-sm text-muted-foreground">
            {project.description}
          </p>
        )}
      </div>

      {/* Page content — sidebar nav handles tab selection */}
      <div className="px-8 py-6">
        <Outlet context={{ project }} />
      </div>
    </div>
  );
}
