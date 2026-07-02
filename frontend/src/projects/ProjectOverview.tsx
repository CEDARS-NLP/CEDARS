import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ProjectStats } from "@/projects/types";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Database,
  BarChart3,
  MessageSquareText,
  Download,
  CheckCircle2,
  ArrowRight,
  Users,
  Loader2,
  Settings,
  ChevronDown,
  ChevronRight,
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

interface ProjectData {
  id: string;
  name: string;
  description: string;
  settings: Record<string, unknown>;
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_base: string | null;
  llm_api_key_set: boolean;
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "vllm", label: "vLLM" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "bedrock", label: "AWS Bedrock" },
];

function ProjectSettings({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const { data: project } = useQuery<ProjectData>({
    queryKey: ["project", projectId],
    queryFn: () => api.get<ProjectData>(`/projects/${projectId}`),
  });

  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiBase, setApiBase] = useState("");
  // Empty string = leave stored key unchanged. Reset after each successful save.
  const [apiKey, setApiKey] = useState("");
  // Explicit "remove the stored key" toggle — the only way to clear a key that
  // is already set (typing nothing leaves it unchanged).
  const [clearApiKey, setClearApiKey] = useState(false);
  const [skipAfterEvent, setSkipAfterEvent] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Bedrock authenticates via the deploy's AWS credentials (task role), so it
  // uses no api_base and no api_key. Track which fields the provider needs.
  const providerUsesEndpoint = provider !== "bedrock" && provider !== "";
  const providerUsesKey = provider !== "bedrock" && provider !== "ollama" && provider !== "";

  // Sync local state when project loads
  const syncFromProject = (p: ProjectData) => {
    setProvider(p.llm_provider || "");
    setModel(p.llm_model || "");
    setApiBase(p.llm_api_base || "");
    setApiKey("");
    setClearApiKey(false);
    setSkipAfterEvent(!!p.settings?.skip_after_event_date);
    setDirty(false);
  };

  // When the provider changes, drop connection fields that don't apply to the
  // new provider (prevents a stale Ollama api_base leaking into a Bedrock call).
  const onProviderChange = (next: string) => {
    setProvider(next);
    if (next === "bedrock") {
      setApiBase("");
      setClearApiKey(true); // remove any stored key on save
      setApiKey("");
    } else if (next === "ollama") {
      setClearApiKey(true);
      setApiKey("");
    }
    setDirty(true);
  };

  // Initialize on first load
  if (project && !dirty && provider === "" && model === "") {
    syncFromProject(project);
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        llm_provider: provider || null,
        llm_model: model || null,
        // Send "" (not null) to explicitly clear the stored api_base — the
        // backend treats "" as "unset" and drops null. Providers that don't use
        // an endpoint (e.g. Bedrock) always clear it.
        llm_api_base: providerUsesEndpoint ? apiBase : "",
        settings: { ...project?.settings, skip_after_event_date: skipAfterEvent },
      };
      // Key handling: a typed value sets it; clearApiKey sends "" to remove the
      // stored key; otherwise omit so an untouched field stays unchanged.
      if (apiKey) {
        payload.llm_api_key = apiKey;
      } else if (clearApiKey) {
        payload.llm_api_key = "";
      }
      return api.put(`/projects/${projectId}`, payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      setDirty(false);
    },
  });

  const missingLlm = !project?.llm_provider || !project?.llm_model;

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-5 py-3 text-left"
      >
        <Settings className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">Project settings</span>
        {missingLlm && (
          <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
            LLM not configured
          </span>
        )}
        <span className="ml-auto">
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-5 py-4 space-y-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
              LLM configuration
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Provider</Label>
                <select
                  value={provider}
                  onChange={(e) => onProviderChange(e.target.value)}
                  className="flex w-full rounded-md border bg-background px-3 py-1.5 text-sm"
                >
                  <option value="">— Select —</option>
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Model</Label>
                <Input
                  value={model}
                  onChange={(e) => { setModel(e.target.value); setDirty(true); }}
                  placeholder={
                    provider === "bedrock"
                      ? "us.anthropic.claude-haiku-4-5-20251001-v1:0"
                      : "gpt-4o-mini"
                  }
                  className="h-8 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">API base (optional)</Label>
                <Input
                  value={apiBase}
                  onChange={(e) => { setApiBase(e.target.value); setDirty(true); }}
                  placeholder="http://localhost:11434"
                  disabled={!providerUsesEndpoint}
                  className="h-8 text-sm"
                />
                {provider === "bedrock" && (
                  <p className="text-[10px] text-muted-foreground">
                    Not used for Bedrock — calls use the deployment's AWS credentials.
                  </p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">API key (optional)</Label>
                <Input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => { setApiKey(e.target.value); setClearApiKey(false); setDirty(true); }}
                  placeholder={
                    clearApiKey
                      ? "will be cleared on save"
                      : project?.llm_api_key_set
                      ? "•••••••• (set)"
                      : "sk-…"
                  }
                  disabled={!providerUsesKey || clearApiKey}
                  className="h-8 text-sm"
                />
                {provider === "bedrock" ? (
                  <p className="text-[10px] text-muted-foreground">
                    Not used for Bedrock — authenticates via the AWS task role.
                  </p>
                ) : project?.llm_api_key_set && !apiKey ? (
                  <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={clearApiKey}
                      onChange={(e) => { setClearApiKey(e.target.checked); setDirty(true); }}
                      className="h-3 w-3 rounded border-border"
                    />
                    Clear the stored key
                  </label>
                ) : null}
              </div>
            </div>
          </div>

          <div className="border-t border-border pt-4">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
              Annotation behavior
            </p>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={skipAfterEvent}
                onChange={(e) => { setSkipAfterEvent(e.target.checked); setDirty(true); }}
                className="h-4 w-4 rounded border-border"
              />
              <div>
                <span className="text-sm text-foreground">Skip annotations after event date</span>
                <p className="text-xs text-muted-foreground">
                  When a reviewer sets an event date, automatically skip annotations from notes
                  on or after that date and show only earlier notes for verification.
                </p>
              </div>
            </label>
          </div>

          {dirty && (
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending ? "Saving..." : "Save"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => { if (project) syncFromProject(project); }}
              >
                Cancel
              </Button>
            </div>
          )}

          {saveMutation.isError && (
            <p className="text-sm text-destructive">
              {(saveMutation.error as Error).message}
            </p>
          )}
        </div>
      )}
    </div>
  );
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
      {/* Project settings */}
      <ProjectSettings projectId={projectId!} />

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
          <p className="text-sm text-muted-foreground">Target sentences</p>
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
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Latest job</h3>
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
            Annotator activity
          </h3>
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Name</th>
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Email</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Reviewed</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Events found</th>
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
                        className="mt-1.5 ml-7 inline-flex items-center gap-1 text-sm text-link transition-colors hover:underline"
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
