import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ProjectStats } from "@/projects/types";
import { Progress } from "@/components/ui/progress";
import {
  Database,
  BarChart3,
  MessageSquareText,
  Download,
  CheckCircle2,
  ArrowRight,
  Users,
  Loader2,
} from "lucide-react";

interface DataSource {
  id: string;
  status: string;
  row_count: number | null;
}

interface EvalSessionSummary {
  id: string;
  status: string;
  metrics: { f1?: number } | null;
}

interface AnnotationStats {
  total: number;
  unreviewed: number;
  reviewed: number;
  skipped: number;
  events_found: number;
  is_complete: boolean;
}

const stepConfig = [
  {
    label: "Data",
    description: "Upload clinical notes",
    path: "data",
    icon: Database,
  },
  {
    label: "Evaluation",
    description: "Configure search, LLM, and evaluate",
    path: "evaluation",
    icon: BarChart3,
  },
  {
    label: "Annotations",
    description: "Review predictions",
    path: "annotations",
    icon: MessageSquareText,
  },
  {
    label: "Export",
    description: "Download results",
    path: "export",
    icon: Download,
  },
];

type StepState = "done" | "current" | "locked";

function StepCircle({ num, state }: { num: number; state: StepState }) {
  if (state === "done") {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-600 text-white">
        <CheckCircle2 className="h-4 w-4" />
      </div>
    );
  }
  if (state === "current") {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-accent-foreground text-sm font-semibold">
        {num}
      </div>
    );
  }
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-border text-sm text-muted-foreground">
      {num}
    </div>
  );
}

function jobStatusBadge(status: string) {
  const base = "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium";
  switch (status) {
    case "running":
      return `${base} bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200`;
    case "completed":
      return `${base} bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200`;
    case "failed":
      return `${base} bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200`;
    default:
      return `${base} bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200`;
  }
}

export default function ProjectOverview() {
  const { projectId } = useParams<{ projectId: string }>();

  // Fetch project stats
  const { data: stats } = useQuery<ProjectStats>({
    queryKey: ["project-stats", projectId],
    queryFn: () => api.get<ProjectStats>(`/projects/${projectId}/stats`),
    refetchInterval: 10000,
  });

  // Fetch workflow data
  const { data: sources } = useQuery<DataSource[]>({
    queryKey: ["data-sources", projectId],
    queryFn: () => api.get<DataSource[]>(`/projects/${projectId}/data/sources`),
  });

  const { data: sessions } = useQuery<EvalSessionSummary[]>({
    queryKey: ["eval-sessions", projectId],
    queryFn: () =>
      api.get<EvalSessionSummary[]>(`/projects/${projectId}/evaluation/sessions`),
  });

  const { data: annotationStats } = useQuery<AnnotationStats>({
    queryKey: ["annotation-stats", projectId],
    queryFn: () =>
      api.get<AnnotationStats>(`/projects/${projectId}/annotations/stats`),
  });

  // Compute step states
  const completedSources = sources?.filter((s) => s.status === "completed") ?? [];
  const hasData = completedSources.length > 0;
  const totalNotes = completedSources.reduce((sum, s) => sum + (s.row_count ?? 0), 0);

  const committedSession = sessions?.find((s) => s.status === "committed" || s.status === "completed");
  const hasCommitted = !!committedSession;

  const hasAnnotations = (annotationStats?.total ?? 0) > 0;
  const reviewedCount = annotationStats?.reviewed ?? 0;
  const totalAnnotations = annotationStats?.total ?? 0;

  // Stats-derived values
  const annotationTotal = stats?.annotations.total ?? 0;
  const annotationReviewed = stats?.annotations.reviewed ?? 0;
  const annotationPct = annotationTotal > 0 ? Math.round((annotationReviewed / annotationTotal) * 100) : 0;

  function getStepState(stepIndex: number): StepState {
    switch (stepIndex) {
      case 0: // Data
        return hasData ? "done" : "current";
      case 1: // Evaluation
        if (!hasData) return "locked";
        return hasCommitted ? "done" : "current";
      case 2: // Annotations
        if (!hasCommitted) return "locked";
        return hasAnnotations && (annotationStats?.is_complete ?? false) ? "done" : "current";
      case 3: // Export
        if (!hasAnnotations) return "locked";
        return "current";
      default:
        return "locked";
    }
  }

  function getStepStatus(stepIndex: number): string {
    const state = getStepState(stepIndex);
    switch (stepIndex) {
      case 0:
        return hasData ? `${totalNotes} notes uploaded` : "Upload clinical notes to get started";
      case 1:
        if (state === "locked") return "Waiting for data upload";
        if (hasCommitted && committedSession?.metrics?.f1 !== undefined)
          return `Committed, F1: ${(committedSession.metrics.f1 * 100).toFixed(1)}%`;
        return "Configure search queries and evaluate LLM";
      case 2:
        if (state === "locked") return "Waiting for evaluation";
        if (hasAnnotations)
          return `${reviewedCount + (annotationStats?.skipped ?? 0)}/${totalAnnotations} reviewed`;
        return "No annotations yet";
      case 3:
        if (state === "locked") return "Waiting for annotations";
        return "Download results";
      default:
        return "";
    }
  }

  return (
    <div className="space-y-6">
      {/* Stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-border bg-card px-5 py-4">
          <p className="text-sm text-muted-foreground">Patients</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {stats?.patients.total ?? 0}
          </p>
          {stats?.patients.by_status && Object.keys(stats.patients.by_status).length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              {Object.entries(stats.patients.by_status)
                .map(([status, count]) => `${count} ${status}`)
                .join(", ")}
            </p>
          )}
        </div>
        <div className="rounded-lg border border-border bg-card px-5 py-4">
          <p className="text-sm text-muted-foreground">Notes</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {stats?.notes.total ?? 0}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-5 py-4">
          <p className="text-sm text-muted-foreground">Target Sentences</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {stats?.sentences.target ?? 0}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            of {stats?.sentences.total ?? 0} total
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-5 py-4">
          <p className="text-sm text-muted-foreground">Annotations</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {annotationReviewed} <span className="text-sm font-normal text-muted-foreground">/ {annotationTotal}</span>
          </p>
          {annotationTotal > 0 && (
            <div className="mt-2">
              <Progress value={annotationPct} className="h-1.5" />
              <p className="mt-1 text-xs text-muted-foreground">{annotationPct}% reviewed</p>
            </div>
          )}
        </div>
      </div>

      {/* Job status */}
      {stats?.jobs.latest && (
        <div>
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Latest Job</h3>
          <div className="rounded-lg border border-border bg-card px-5 py-4">
            <div className="flex items-center gap-3">
              {stats.jobs.latest.status === "running" && (
                <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              )}
              <span className="text-sm font-medium text-foreground">
                {stats.jobs.latest.job_type}
              </span>
              <span className={jobStatusBadge(stats.jobs.latest.status)}>
                {stats.jobs.latest.status}
              </span>
            </div>
            {stats.jobs.latest.status === "running" && (
              <div className="mt-3">
                <Progress value={Math.round(stats.jobs.latest.progress * 100)} className="h-1.5" />
                <p className="mt-1 text-xs text-muted-foreground">
                  {Math.round(stats.jobs.latest.progress * 100)}% complete
                </p>
              </div>
            )}
            {(stats.jobs.active_count > 0 || stats.jobs.failed_count > 0) && (
              <p className="mt-2 text-xs text-muted-foreground">
                {stats.jobs.active_count > 0 && `${stats.jobs.active_count} active`}
                {stats.jobs.active_count > 0 && stats.jobs.failed_count > 0 && " · "}
                {stats.jobs.failed_count > 0 && `${stats.jobs.failed_count} failed`}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Annotator activity */}
      {stats?.annotators && stats.annotators.length > 0 && (
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Users className="h-4 w-4" />
            Annotator Activity
          </h3>
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Name</th>
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Email</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Reviewed</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Events Found</th>
                </tr>
              </thead>
              <tbody>
                {stats.annotators.map((a) => (
                  <tr key={a.user_id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 text-foreground">{a.name || "--"}</td>
                    <td className="px-4 py-2 text-muted-foreground">{a.email}</td>
                    <td className="px-4 py-2 text-right text-foreground">{a.reviewed_count}</td>
                    <td className="px-4 py-2 text-right text-foreground">{a.events_found}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Workflow stepper */}
      <div>
        <h3 className="mb-4 text-sm font-medium text-muted-foreground">
          Workflow
        </h3>
        <div role="list" className="space-y-1">
          {stepConfig.map((step, i) => {
            const state = getStepState(i);
            const status = getStepStatus(i);
            const isLast = i === stepConfig.length - 1;

            return (
              <div key={step.path} role="listitem" aria-current={state === "current" ? "step" : undefined}>
                <div className="flex items-start gap-4">
                  {/* Step indicator + connector */}
                  <div className="flex flex-col items-center">
                    <StepCircle num={i + 1} state={state} />
                    {!isLast && (
                      <div
                        className={`w-0.5 flex-1 min-h-8 ${
                          state === "done" ? "bg-emerald-600" : "bg-border"
                        }`}
                      />
                    )}
                  </div>

                  {/* Step content */}
                  <div className="flex-1 pb-6">
                    <div className="flex items-center gap-3">
                      <step.icon
                        className={`h-4 w-4 ${
                          state === "locked" ? "text-muted-foreground/50" : "text-foreground"
                        }`}
                        aria-hidden="true"
                      />
                      <span
                        className={`text-sm font-medium ${
                          state === "locked" ? "text-muted-foreground/60" : "text-foreground"
                        }`}
                      >
                        {step.label}
                      </span>
                    </div>
                    <p className="mt-1 ml-7 text-sm text-muted-foreground">
                      {status}
                    </p>
                    {state !== "locked" && (
                      <Link
                        to={`/projects/${projectId}/${step.path}`}
                        className="mt-1.5 ml-7 inline-flex items-center gap-1 text-sm text-accent transition-colors hover:underline"
                      >
                        {state === "done" ? "View" : "Get started"}
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
