import { useOutletContext } from "react-router-dom";
import type { ProjectDetail, ProjectRole } from "./types";

export interface ProjectPermissions {
  role: ProjectRole | null;
  isAdminLevel: boolean;
  canManageMembers: boolean;
  canAdjudicate: boolean;
  canRunJobs: boolean;
  canExport: boolean;
  canViewProject: boolean;
}

export function useProjectPermissions(): ProjectPermissions {
  const { project } = useOutletContext<{ project: ProjectDetail }>();
  const role = project?.role ?? null;
  const isAdminLevel = role === "admin" || role === "investigator";

  return {
    role,
    isAdminLevel,
    canManageMembers: isAdminLevel,
    canAdjudicate: role === "admin" || role === "investigator" || role === "annotator",
    canRunJobs: isAdminLevel,
    canExport: isAdminLevel,
    canViewProject: Boolean(role),
  };
}
