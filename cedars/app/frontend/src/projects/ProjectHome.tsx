import { Navigate, useParams } from "react-router-dom";
import { useProject } from "./useProject";

/**
 * Project landing route. Mirrors the original Flask homepage redirect: admins
 * land on Statistics, annotators land on Adjudication.
 */
export default function ProjectHome() {
  const { projectId } = useParams<{ projectId: string }>();
  const project = useProject();
  const isAdminLevelRole = project?.role === "admin" || project?.role === "investigator";
  const target = isAdminLevelRole ? "stats" : "adjudicate";
  return <Navigate to={`/projects/${projectId}/${target}`} replace />;
}
