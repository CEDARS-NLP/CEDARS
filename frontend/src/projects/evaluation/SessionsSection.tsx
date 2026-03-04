import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Play,
  CheckCircle2,
  XCircle,
  BarChart3,
  Shield,
  ChevronRight,
  ArrowLeft,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type {
  Predictor,
  EvalSession,
  Metrics,
  Judgment,
  JudgmentWithNote,
  TokenUsage,
} from "@/projects/types";

// ── Collapsible Section ────────────────────────────────────────

function CollapsibleSection({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-90" : ""}`}
        />
        {summary}
      </button>
      {open && <div className="mt-2 pl-5">{children}</div>}
    </div>
  );
}

// ── Status Badge ────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    sampling: "bg-blue-100 text-blue-800 dark:bg-blue-500/20 dark:text-blue-300",
    running: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300",
    reviewing: "bg-violet-100 text-violet-800 dark:bg-violet-500/20 dark:text-violet-300",
    completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-300",
  };

  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? "bg-muted text-muted-foreground"}`}>
      {status}
    </span>
  );
}

// ── Metric Display ──────────────────────────────────────────────

function MetricCard({ label, value, format = "pct" }: { label: string; value?: number; format?: "pct" | "int" }) {
  const display = value === undefined
    ? "--"
    : format === "pct"
      ? (value * 100).toFixed(1) + "%"
      : String(value);

  return (
    <div className="text-center">
      <p className="text-2xl font-semibold tabular-nums text-foreground">{display}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: Metrics }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <MetricCard label="Accuracy" value={metrics.accuracy} />
        <MetricCard label="Precision" value={metrics.precision} />
        <MetricCard label="Recall" value={metrics.recall} />
        <MetricCard label="F1 Score" value={metrics.f1} />
      </div>
      <div className="grid grid-cols-4 gap-4 rounded-md bg-muted/50 px-4 py-3">
        <MetricCard label="True Pos" value={metrics.tp} format="int" />
        <MetricCard label="False Pos" value={metrics.fp} format="int" />
        <MetricCard label="True Neg" value={metrics.tn} format="int" />
        <MetricCard label="False Neg" value={metrics.fn} format="int" />
      </div>
    </div>
  );
}

function TokenUsageSummary({ usage }: { usage: TokenUsage }) {
  return (
    <div className="rounded-md bg-muted/30 px-4 py-3">
      <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Token Usage
      </p>
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <span className="text-muted-foreground">Prompt: </span>
          <span className="font-medium tabular-nums">{usage.prompt_tokens.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Completion: </span>
          <span className="font-medium tabular-nums">{usage.completion_tokens.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Total: </span>
          <span className="font-medium tabular-nums">{usage.total_tokens.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
}

// ── Create Session Form ─────────────────────────────────────────

function CreateSessionForm({
  projectId,
  predictors,
  onClose,
}: {
  projectId: string;
  predictors: Predictor[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [predictorId, setPredictorId] = useState(
    predictors.find((p) => p.is_active)?.id ?? predictors[0]?.id ?? ""
  );
  const [sampleSize, setSampleSize] = useState(50);
  const [ratio, setRatio] = useState(0.6);

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`/projects/${projectId}/evaluation/sessions`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
      onClose();
    },
  });

  return (
    <Card className="border-accent/30">
      <CardHeader>
        <CardTitle className="text-base">New Evaluation Session</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="eval-name">Session name</Label>
            <Input
              id="eval-name"
              placeholder="e.g. MI prompt v2"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="eval-predictor">Predictor</Label>
            <select
              id="eval-predictor"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={predictorId}
              onChange={(e) => setPredictorId(e.target.value)}
            >
              {predictors.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.predictor_type}){p.is_active ? " *" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="eval-size">Sample size</Label>
            <Input
              id="eval-size"
              type="number"
              min={5}
              max={500}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="eval-ratio">Keyword match ratio</Label>
            <Input
              id="eval-ratio"
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={ratio}
              onChange={(e) => setRatio(Number(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              Fraction of sample matching NLP keywords (0.0-1.0)
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() =>
              createMutation.mutate({
                name,
                predictor_config_id: predictorId,
                sample_config: {
                  size: sampleSize,
                  keyword_match_ratio: ratio,
                  keywords: [],
                },
              })
            }
            disabled={!predictorId || createMutation.isPending}
          >
            {createMutation.isPending ? "Creating\u2026" : "Create Session"}
          </Button>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
        {createMutation.isError && (
          <p className="text-sm text-destructive" role="alert">
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : "Failed to create session"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Session Detail View ─────────────────────────────────────────

function SessionDetail({
  projectId,
  sessionId,
  onBack,
}: {
  projectId: string;
  sessionId: string;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const [validateName, setValidateName] = useState("");
  const [showReasoning, setShowReasoning] = useState(false);

  const { data: evalSession, isLoading } = useQuery<EvalSession>({
    queryKey: ["eval-session", sessionId],
    queryFn: () =>
      api.get<EvalSession>(`/projects/${projectId}/evaluation/sessions/${sessionId}`),
  });

  const { data: judgments } = useQuery<Judgment[]>({
    queryKey: ["eval-judgments", sessionId],
    queryFn: () =>
      api.get<Judgment[]>(`/projects/${projectId}/evaluation/sessions/${sessionId}/judgments`),
  });

  const { data: nextJudgment } = useQuery<JudgmentWithNote | null>({
    queryKey: ["eval-next", sessionId],
    queryFn: () =>
      api.get<JudgmentWithNote | null>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/next`
      ),
    enabled: evalSession?.status === "reviewing",
  });

  const { data: metrics } = useQuery<Metrics>({
    queryKey: ["eval-metrics", sessionId],
    queryFn: () =>
      api.get<Metrics>(`/projects/${projectId}/evaluation/sessions/${sessionId}/metrics`),
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${sessionId}/run`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["eval-session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["eval-judgments", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["eval-next", sessionId] });
    },
  });

  const judgeMutation = useMutation({
    mutationFn: ({ judgmentId, value }: { judgmentId: string; value: string }) =>
      api.post(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/judgments/${judgmentId}`,
        { judgment: value }
      ),
    onSuccess: () => {
      setShowReasoning(false);
      queryClient.invalidateQueries({ queryKey: ["eval-judgments", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["eval-next", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["eval-metrics", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["eval-session", sessionId] });
    },
  });

  const validateMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/validate`,
        body
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["validated-predictors", projectId] });
      setValidateName("");
    },
  });

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (!evalSession) return null;

  const pendingCount = judgments?.filter((j) => j.judgment === "pending").length ?? 0;
  const canRun = evalSession.status === "sampling";
  const canReview = evalSession.status === "reviewing" && nextJudgment;
  const canValidate = evalSession.status === "completed" || (metrics && (metrics.total_judged ?? 0) > 0);

  // Build metrics summary line
  const metricsSummaryParts: string[] = [];
  if (metrics && (metrics.total_judged ?? 0) > 0) {
    if (metrics.accuracy !== undefined)
      metricsSummaryParts.push(`Accuracy ${(metrics.accuracy * 100).toFixed(1)}%`);
    if (metrics.f1 !== undefined)
      metricsSummaryParts.push(`F1 ${(metrics.f1 * 100).toFixed(1)}%`);
    metricsSummaryParts.push(`${metrics.total_judged ?? 0} judged`);
  }

  return (
    <div className="space-y-0">
      {/* Compact session header: [< Back]  Name  status  12/50 judged */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Back to sessions"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <span className="text-sm font-semibold text-foreground">
          {evalSession.name || "Evaluation Session"}
        </span>
        <StatusBadge status={evalSession.status} />
        <span className="text-sm text-muted-foreground">
          {evalSession.judged_notes}/{evalSession.total_notes} judged
        </span>
      </div>

      {/* Run predictions button */}
      {canRun && (
        <Card className="mt-4">
          <CardContent className="flex items-center gap-3 py-4">
            <Play className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">Run predictions</p>
              <p className="text-xs text-muted-foreground">
                Generate predictions for all {evalSession.total_notes} sampled notes
              </p>
            </div>
            <Button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
            >
              {runMutation.isPending ? "Running\u2026" : "Run"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Review interface */}
      {canReview && nextJudgment && (
        <div className="mt-5 space-y-0">
          {/* Note metadata */}
          <p className="text-sm text-muted-foreground">
            Note{" "}
            <span className="font-mono font-medium text-foreground/70">
              {nextJudgment.note_text_id}
            </span>
            {" "}&mdash; Patient {nextJudgment.patient_id}
          </p>

          {/* Note text (no card wrapper, increased height) */}
          <div
            className="mt-2 max-h-[50vh] overflow-y-auto text-[15px] leading-relaxed text-foreground/80"
            style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
            role="region"
            aria-label="Clinical note under review"
          >
            {nextJudgment.note_text}
          </div>

          {/* Prediction + judgment row */}
          <div className="mt-4 flex items-center gap-3">
            {/* Prediction badge + score */}
            {nextJudgment.predicted_label === 1 ? (
              <Badge className="bg-emerald-600 text-white">Event Detected</Badge>
            ) : (
              <Badge variant="secondary">No Event</Badge>
            )}
            <span className="text-sm font-medium tabular-nums text-muted-foreground">
              {nextJudgment.predicted_score !== null
                ? (nextJudgment.predicted_score * 100).toFixed(1) + "%"
                : "--"}
            </span>

            {/* Why? toggle for reasoning */}
            {nextJudgment.reasoning && (
              <button
                onClick={() => setShowReasoning((v) => !v)}
                className="text-sm text-muted-foreground underline decoration-dotted hover:text-foreground"
              >
                Why?
              </button>
            )}

            <div className="flex-1" />

            {/* Judgment buttons */}
            <Button
              className="gap-1.5"
              onClick={() =>
                judgeMutation.mutate({ judgmentId: nextJudgment.id, value: "correct" })
              }
              disabled={judgeMutation.isPending}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Correct
            </Button>
            <Button
              variant="outline"
              className="gap-1.5"
              onClick={() =>
                judgeMutation.mutate({ judgmentId: nextJudgment.id, value: "wrong" })
              }
              disabled={judgeMutation.isPending}
            >
              <XCircle className="h-4 w-4" aria-hidden="true" />
              Wrong
            </Button>
            <Button
              variant="ghost"
              className="text-muted-foreground"
              onClick={() =>
                judgeMutation.mutate({ judgmentId: nextJudgment.id, value: "skipped" })
              }
              disabled={judgeMutation.isPending}
            >
              Skip
            </Button>
          </div>

          {/* Reasoning (hidden behind Why? toggle) */}
          {showReasoning && nextJudgment.reasoning && (
            <p className="mt-2 rounded-md bg-muted/50 px-3 py-2 text-sm italic text-foreground/70">
              {nextJudgment.reasoning}
            </p>
          )}
        </div>
      )}

      {/* Collapsible metrics summary */}
      {metrics && (metrics.total_judged ?? 0) > 0 && (
        <div className="mt-5">
          <CollapsibleSection
            summary={metricsSummaryParts.join(" \u00b7 ")}
          >
            <div className="space-y-3">
              <MetricsGrid metrics={metrics} />
              {evalSession.metrics?.token_usage && evalSession.metrics.token_usage.total_tokens > 0 && (
                <TokenUsageSummary usage={evalSession.metrics.token_usage} />
              )}
            </div>
          </CollapsibleSection>
        </div>
      )}

      {/* Validate — inline bar, no card wrapper */}
      {canValidate && (
        <div className="mt-5">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Input
              placeholder="Version name (e.g. v1.0)"
              value={validateName}
              onChange={(e) => setValidateName(e.target.value)}
              className="max-w-xs"
            />
            <Button
              onClick={() =>
                validateMutation.mutate({ name: validateName, threshold: 0.5 })
              }
              disabled={!validateName || validateMutation.isPending}
            >
              {validateMutation.isPending ? "Saving\u2026" : "Validate"}
            </Button>
          </div>
          {validateMutation.isSuccess && (
            <p className="mt-1.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">
              Configuration validated and saved.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Sessions Section ───────────────────────────────────────

export default function SessionsSection({ projectId }: { projectId: string }) {
  const [showCreate, setShowCreate] = useState(false);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  const { data: sessions, isLoading } = useQuery<EvalSession[]>({
    queryKey: ["eval-sessions", projectId],
    queryFn: () =>
      api.get<EvalSession[]>(`/projects/${projectId}/evaluation/sessions`),
  });

  const { data: predictors } = useQuery<Predictor[]>({
    queryKey: ["predictors", projectId],
    queryFn: () => api.get<Predictor[]>(`/projects/${projectId}/predictors`),
  });

  // Session detail view
  if (selectedSession) {
    return (
      <SessionDetail
        projectId={projectId}
        sessionId={selectedSession}
        onBack={() => setSelectedSession(null)}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-foreground">Evaluation Sessions</h3>
          <p className="text-sm text-muted-foreground">
            Evaluate predictor accuracy on sampled notes with clinician review
          </p>
        </div>
        <Button
          onClick={() => setShowCreate(true)}
          disabled={showCreate || !predictors?.length}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          New Session
        </Button>
      </div>

      {/* Create form */}
      {showCreate && predictors && (
        <CreateSessionForm
          projectId={projectId}
          predictors={predictors}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Session list */}
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : sessions && sessions.length > 0 ? (
        <div className="space-y-2">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelectedSession(s.id)}
              className="flex w-full items-center gap-4 rounded-lg border border-border bg-card px-5 py-4 text-left transition-colors hover:bg-accent/5"
              role="link"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">
                    {s.name || "Unnamed Session"}
                  </span>
                  <StatusBadge status={s.status} />
                </div>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {s.total_notes} notes &mdash; {s.judged_notes} judged
                  {s.metrics?.f1 !== undefined && (
                    <> &mdash; F1: {(s.metrics.f1 * 100).toFixed(1)}%</>
                  )}
                </p>
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </button>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-12">
          <BarChart3 className="mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="font-medium text-foreground">No evaluation sessions</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Create an evaluation session to test your predictor accuracy.
          </p>
        </div>
      )}
    </div>
  );
}
