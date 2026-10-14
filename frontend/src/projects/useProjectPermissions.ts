import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";

export default function useProjectPermissions(projectId: string) {
  const { user } = useAuth();
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<{ role: string | null }>(`/projects/${projectId}`),
    enabled: !!projectId,
  });
  const isAdmin = user?.platform_role === "platform_admin" || project?.role === "admin";
  return {
    canManage: isAdmin,
    canReview: isAdmin || project?.role === "annotator",
  };
}