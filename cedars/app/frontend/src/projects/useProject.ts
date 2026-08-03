import { useOutletContext } from "react-router-dom";
import type { ProjectDetail } from "./ProjectLayout";

/** Access the current project provided by ProjectLayout's outlet context. */
export function useProject(): ProjectDetail {
  const { project } = useOutletContext<{ project: ProjectDetail }>();
  return project;
}
