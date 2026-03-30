import { useState, useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Sparkles,
  Play,
  Lock,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  BarChart3,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type {
  EventConfig,
  PipelineRun,
  PipelineRunStats,
  RunMetrics,
  PatientTaskSummary,
} from "@/projects/types";

// ── Helpers ──────────────────────────────────────────────────────

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300";
    case "running":
    case "processing":
      return "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300";
    case "queued":
      return "bg-blue-100 text-blue-800 dark:bg-blue-500/20 dark:text-blue-300";
    case "failed":
      return "bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-300";
    case "cancelled":
      return "bg-gray-100 text-gray-600 dark:bg-gray-500/20 dark:text-gray-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

// ── Event Config Form ────────────────────────────────────────────

interface EventFormState {
  name: string;
  description: string;
  include_criteria: string;
  exclude_criteria: string;
  llm_provider: string;
  llm_model: string;
  llm_api_base: string;
}

const EMPTY_FORM: EventFormState = {
  name: "",
  description: "",
  include_criteria: "",
  exclude_criteria: "",
  llm_provider: "ollama",
  llm_model: "llama3",
  llm_api_base: "http://localhost:11434",
};

function EventConfigForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (ec: EventConfig) => void;
}) {
  const [form, setForm] = useState<EventFormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<EventConfig>(`/projects/${projectId}/pipeline/events`, {
        ...form,
        search_patterns: {},
        llm_api_base: form.llm_api_base || null,
      }),
    onSuccess: (ec) => {
      setForm(EMPTY_FORM);
      setError(null);
      onCreated(ec);
    },
    onError: (e: Error) => setError(e.message),
  });

  const set = (field: keyof EventFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Plus className="h-4 w-4" />
          New Event Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="ec-name">Event Name</Label>
            <Input id="ec-name" value={form.name} onChange={set("name")} placeholder="e.g. Myocardial Infarction" />
          </div>
          <div>
            <Label htmlFor="ec-desc">Description</Label>
            <Input id="ec-desc" value={form.description} onChange={set("description")} placeholder="Confirmed MI event" />
          </div>
        </div>
        <div>
          <Label htmlFor="ec-include">Include Criteria</Label>
          <textarea
            id="ec-include"
            className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={form.include_criteria}
            onChange={set("include_criteria")}
            placeholder="Positive troponin, ECG changes, clinical diagnosis..."
          />
        </div>
        <div>
          <Label htmlFor="ec-exclude">Exclude Criteria</Label>
          <textarea
            id="ec-exclude"
            className="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={form.exclude_criteria}
            onChange={set("exclude_criteria")}
            placeholder="Rule-out, family history only..."
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <Label htmlFor="ec-provider">LLM Provider</Label>
            <Input id="ec-provider" value={form.llm_provider} onChange={set("llm_provider")} />
          </div>
          <div>
            <Label htmlFor="ec-model">LLM Model</Label>
            <Input id="ec-model" value={form.llm_model} onChange={set("llm_model")} />
          </div>
          <div>
            <Label htmlFor="ec-api-base">API Base URL</Label>
            <Input id="ec-api-base" value={form.llm_api_base} onChange={set("llm_api_base")} />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !form.name}>
          {createMutation.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Plus className="mr-1.5 h-4 w-4" />}
          Create Event Config
        </Button>
      </CardContent>
    </Card>
  );
}

// ── Search Patterns Display ──────────────────────────────────────

function PatternsCard({ patterns }: { patterns: EventConfig["search_patterns"] }) {
  if (!patterns.keywords?.length && !patterns.regex_patterns?.length) {
    return <p className="text-sm text-muted-foreground">No patterns generated yet.</p>;
  }
  return (
    <div className="space-y-3">
      {patterns.keywords && patterns.keywords.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Keywords</p>
          <div className="flex flex-wrap gap-1.5">
            {patterns.keywords.map((kw) => (
              <Badge key={kw} variant="secondary" className="text-xs">
                {kw}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {patterns.regex_patterns && patterns.regex_patterns.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Regex Patterns</p>
          <div className="flex flex-wrap gap-1.5">
            {patterns.regex_patterns.map((p) => (
              <code key={p} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                {p}
              </code>
            ))}
          </div>
        </div>
      )}
      {patterns.exclusion_patterns && patterns.exclusion_patterns.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Exclusions</p>
          <div className="flex flex-wrap gap-1.5">
            {patterns.exclusion_patterns.map((p) => (
              <code key={p} className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-300">
                {p}
              </code>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pipeline Run Progress Banner ─────────────────────────────────

function RunProgressBanner({
  projectId,
  run,
}: {
  projectId: string;
  run: PipelineRun;
}) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  const { data: stats } = useQuery<PipelineRunStats>({
    queryKey: ["run-stats", run.id],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs/${run.id}/stats`),
    refetchInterval: run.status === "running" || run.status === "queued" ? 3000 : false,
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.post<PipelineRun>(`/projects/${projectId}/pipeline/runs/${run.id}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs", projectId] });
    },
  });

  // WebSocket for live progress
  useEffect(() => {
    const isActive = run.status === "queued" || run.status === "running";
    if (!isActive) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/ws/projects/${projectId}/pipeline/${run.id}`
    );
    wsRef.current = ws;

    ws.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ["run-stats", run.id] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs", projectId] });
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [run.id, run.status, projectId, queryClient]);

  const isActive = run.status === "queued" || run.status === "running";
  const progress = stats && stats.total > 0
    ? Math.round(((stats.completed + stats.failed + stats.no_match) / stats.total) * 100)
    : 0;

  const borderClass = run.status === "completed"
    ? "border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10"
    : run.status === "failed"
      ? "border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10"
      : "border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10";

  return (
    <div className={`rounded-lg border px-4 py-3 ${borderClass}`}>
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium">
              {run.run_type === "sample" ? "Sample" : "Full"} Run
            </p>
            <Badge className={`text-xs ${statusColor(run.status)}`}>{run.status}</Badge>
          </div>
          {stats && (
            <p className="text-xs text-muted-foreground">
              {stats.completed + stats.no_match} done, {stats.failed} failed, {stats.queued + stats.processing} remaining
            </p>
          )}
        </div>
        {isActive && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
          >
            {cancelMutation.isPending ? "Cancelling..." : "Cancel"}
          </Button>
        )}
      </div>
      {isActive && <Progress value={progress} className="mt-2 h-1.5" />}
    </div>
  );
}

// ── Metrics Display ──────────────────────────────────────────────

function MetricsCard({ metrics }: { metrics: RunMetrics }) {
  if (metrics.total_reviewed === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No annotations have been reviewed yet. Review sample results to see metrics.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        <div>
          <p className="text-xs text-muted-foreground">TP</p>
          <p className="text-lg font-semibold text-emerald-600">{metrics.true_positives}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">FP</p>
          <p className="text-lg font-semibold text-red-600">{metrics.false_positives}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">FN</p>
          <p className="text-lg font-semibold text-amber-600">{metrics.false_negatives}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">TN</p>
          <p className="text-lg font-semibold">{metrics.true_negatives}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Reviewed</p>
          <p className="text-lg font-semibold">{metrics.total_reviewed}</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-muted-foreground">Precision</p>
          <p className="text-lg font-semibold">
            {metrics.precision !== null ? `${(metrics.precision * 100).toFixed(1)}%` : "--"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Recall</p>
          <p className="text-lg font-semibold">
            {metrics.recall !== null ? `${(metrics.recall * 100).toFixed(1)}%` : "--"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">F1</p>
          <p className="text-lg font-semibold">
            {metrics.f1_score !== null ? `${(metrics.f1_score * 100).toFixed(1)}%` : "--"}
          </p>
        </div>
      </div>
      {metrics.suggested_threshold !== null && (
        <p className="text-sm text-muted-foreground">
          Suggested threshold: <span className="font-medium">{metrics.suggested_threshold.toFixed(2)}</span>
        </p>
      )}
    </div>
  );
}

// ── Event Config Detail Panel ────────────────────────────────────

function EventConfigDetail({
  projectId,
  config,
}: {
  projectId: string;
  config: EventConfig;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(true);
  const [sampleSize, setSampleSize] = useState(10);
  const [threshold, setThreshold] = useState(0.5);
  const [showCommit, setShowCommit] = useState(false);

  const { data: runs } = useQuery<PipelineRun[]>({
    queryKey: ["pipeline-runs", projectId, config.id],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs?event_config_id=${config.id}`),
  });

  const latestRun = runs?.[0];

  const { data: metrics } = useQuery<RunMetrics>({
    queryKey: ["run-metrics", latestRun?.id],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs/${latestRun!.id}/metrics`),
    enabled: !!latestRun && latestRun.status === "completed",
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      api.post<EventConfig>(`/projects/${projectId}/pipeline/events/${config.id}/generate-patterns`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["event-configs", projectId] });
    },
  });

  const sampleMutation = useMutation({
    mutationFn: () =>
      api.post<PipelineRun>(
        `/projects/${projectId}/pipeline/events/${config.id}/run-sample`,
        { sample_size: sampleSize }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs", projectId, config.id] });
    },
  });

  const fullRunMutation = useMutation({
    mutationFn: () =>
      api.post<PipelineRun>(`/projects/${projectId}/pipeline/events/${config.id}/run-full`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs", projectId, config.id] });
    },
  });

  const commitMutation = useMutation({
    mutationFn: () =>
      api.post<EventConfig>(`/projects/${projectId}/pipeline/events/${config.id}/commit`, {
        confidence_threshold: threshold,
      }),
    onSuccess: () => {
      setShowCommit(false);
      queryClient.invalidateQueries({ queryKey: ["event-configs", projectId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/pipeline/events/${config.id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["event-configs", projectId] });
    },
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2"
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <CardTitle className="text-base">{config.name}</CardTitle>
          </button>
          <div className="flex items-center gap-2">
            {config.is_committed ? (
              <Badge className="gap-1 bg-emerald-600 text-white">
                <Lock className="h-3 w-3" />
                Committed
              </Badge>
            ) : (
              <Badge variant="outline">Draft</Badge>
            )}
            {!config.is_committed && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-6">
          {/* Event definition */}
          <div className="space-y-2 text-sm">
            <p className="text-muted-foreground">{config.description}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Include</p>
                <p>{config.include_criteria}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Exclude</p>
                <p>{config.exclude_criteria || "None"}</p>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {config.llm_provider}/{config.llm_model}
              {config.llm_api_base ? ` @ ${config.llm_api_base}` : ""}
            </p>
          </div>

          {/* Search patterns */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-medium">Search Patterns</h4>
              {!config.is_committed && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  {generateMutation.isPending ? "Generating..." : "Generate Patterns"}
                </Button>
              )}
            </div>
            {generateMutation.isError && (
              <p className="mb-2 text-sm text-destructive">
                <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
                {generateMutation.error.message}
              </p>
            )}
            <PatternsCard patterns={config.search_patterns} />
          </div>

          {/* Sample run */}
          {!config.is_committed && (
            <div>
              <h4 className="mb-2 text-sm font-medium">Sample Run</h4>
              <div className="flex items-center gap-3">
                <Label htmlFor={`sample-${config.id}`} className="text-sm">
                  Sample size:
                </Label>
                <Input
                  id={`sample-${config.id}`}
                  type="number"
                  min={1}
                  max={1000}
                  value={sampleSize}
                  onChange={(e) => setSampleSize(Number(e.target.value))}
                  className="h-8 w-24"
                />
                <Button
                  size="sm"
                  className="gap-1.5"
                  onClick={() => sampleMutation.mutate()}
                  disabled={sampleMutation.isPending}
                >
                  {sampleMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Run Sample
                </Button>
              </div>
              {sampleMutation.isError && (
                <p className="mt-1 text-sm text-destructive">{sampleMutation.error.message}</p>
              )}
            </div>
          )}

          {/* Active run progress */}
          {latestRun && (latestRun.status === "queued" || latestRun.status === "running") && (
            <RunProgressBanner projectId={projectId} run={latestRun} />
          )}

          {/* Metrics from sample reviews */}
          {metrics && (
            <div>
              <h4 className="mb-2 flex items-center gap-2 text-sm font-medium">
                <BarChart3 className="h-4 w-4" />
                Sample Metrics
              </h4>
              <MetricsCard metrics={metrics} />
            </div>
          )}

          {/* Commit section */}
          {!config.is_committed && (
            <div className="border-t border-border pt-4">
              {!showCommit ? (
                <Button variant="outline" className="gap-1.5" onClick={() => setShowCommit(true)}>
                  <Lock className="h-3.5 w-3.5" />
                  Commit Configuration
                </Button>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Committing locks this configuration. You can then run the full pipeline.
                  </p>
                  <div className="flex items-center gap-3">
                    <Label htmlFor={`threshold-${config.id}`} className="text-sm">
                      Confidence threshold:
                    </Label>
                    <Input
                      id={`threshold-${config.id}`}
                      type="number"
                      step={0.05}
                      min={0}
                      max={1}
                      value={threshold}
                      onChange={(e) => setThreshold(Number(e.target.value))}
                      className="h-8 w-24"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      className="gap-1.5"
                      onClick={() => commitMutation.mutate()}
                      disabled={commitMutation.isPending}
                    >
                      {commitMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Lock className="h-3.5 w-3.5" />}
                      Confirm Commit
                    </Button>
                    <Button variant="ghost" onClick={() => setShowCommit(false)}>
                      Cancel
                    </Button>
                  </div>
                  {commitMutation.isError && (
                    <p className="text-sm text-destructive">{commitMutation.error.message}</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Full pipeline run (committed only) */}
          {config.is_committed && (
            <div className="border-t border-border pt-4">
              <div className="flex items-center gap-3">
                <Button
                  className="gap-1.5"
                  onClick={() => fullRunMutation.mutate()}
                  disabled={fullRunMutation.isPending}
                >
                  {fullRunMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Run Full Pipeline
                </Button>
                {config.confidence_threshold !== null && (
                  <span className="text-sm text-muted-foreground">
                    Threshold: {config.confidence_threshold}
                  </span>
                )}
              </div>
              {fullRunMutation.isError && (
                <p className="mt-1 text-sm text-destructive">{fullRunMutation.error.message}</p>
              )}
            </div>
          )}

          {/* Run history */}
          {runs && runs.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-medium">Run History</h4>
              <div className="space-y-1.5">
                {runs.map((r) => (
                  <div key={r.id} className="flex items-center gap-3 text-sm">
                    <Badge className={`text-xs ${statusColor(r.status)}`}>{r.status}</Badge>
                    <span className="text-muted-foreground">{r.run_type}</span>
                    <span className="text-muted-foreground">
                      {r.total_patients} patients
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// ── Main Page ────────────────────────────────────────────────────

export default function EventConfigPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();

  const { data: configs, isLoading } = useQuery<EventConfig[]>({
    queryKey: ["event-configs", projectId],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/events`),
  });

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="pipeline" projectId={projectId!} />

      <div>
        <h2 className="text-lg font-semibold text-foreground">Agentic Pipeline</h2>
        <p className="text-sm text-muted-foreground">
          Define clinical events, generate search patterns, calibrate on a sample, then run at scale.
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : (
        <>
          {/* Existing configs */}
          {configs && configs.length > 0 && (
            <div className="space-y-4">
              {configs.map((ec) => (
                <EventConfigDetail key={ec.id} projectId={projectId!} config={ec} />
              ))}
            </div>
          )}

          {/* Create new */}
          <EventConfigForm
            projectId={projectId!}
            onCreated={() => {
              queryClient.invalidateQueries({ queryKey: ["event-configs", projectId] });
            }}
          />
        </>
      )}
    </div>
  );
}
