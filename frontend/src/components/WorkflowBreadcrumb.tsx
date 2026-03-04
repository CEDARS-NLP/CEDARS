import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";

const WORKFLOW_STEPS = [
  { label: "Data", path: "data" },
  { label: "Pipeline", path: "pipeline" },
  { label: "Evaluation", path: "evaluation" },
  { label: "Annotations", path: "annotations" },
  { label: "Export", path: "export" },
];

interface WorkflowBreadcrumbProps {
  currentStep: string;
  projectId: string;
}

export default function WorkflowBreadcrumb({
  currentStep,
  projectId,
}: WorkflowBreadcrumbProps) {
  const idx = WORKFLOW_STEPS.findIndex((s) => s.path === currentStep);
  if (idx === -1) return null;

  const stepNum = idx + 1;
  const prev = idx > 0 ? WORKFLOW_STEPS[idx - 1] : null;
  const next = idx < WORKFLOW_STEPS.length - 1 ? WORKFLOW_STEPS[idx + 1] : null;
  const base = `/projects/${projectId}`;

  return (
    <nav
      aria-label="Workflow steps"
      className="mb-5 flex items-center justify-between text-sm text-muted-foreground"
    >
      <div className="flex items-center gap-1.5">
        {prev ? (
          <Link
            to={`${base}/${prev.path}`}
            className="flex items-center gap-1 transition-colors hover:text-foreground hover:underline"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            {prev.label}
          </Link>
        ) : (
          <span className="w-16" />
        )}
      </div>
      <span>
        Step {stepNum} of {WORKFLOW_STEPS.length}:{" "}
        <span className="font-medium text-foreground">
          {WORKFLOW_STEPS[idx].label}
        </span>
      </span>
      <div className="flex items-center gap-1.5">
        {next ? (
          <Link
            to={`${base}/${next.path}`}
            className="flex items-center gap-1 transition-colors hover:text-foreground hover:underline"
          >
            {next.label}
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        ) : (
          <span className="w-16" />
        )}
      </div>
    </nav>
  );
}
