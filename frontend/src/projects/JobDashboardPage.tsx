import { useState, useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  XCircle,
  RotateCcw,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertTriangle,
  Activity,
  Layers,
} from "lucide-react";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { PipelineRun, PipelineRunStats, PatientTaskSummary } from "@/projects/types";

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

function RunDetail({
  projectId,
  run,
}: {
  projectId: string;
  run: PipelineRun;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const isActive = run.status === "queued" || run.status === "running";
  const prevStatus = useRef(run.status);

  const { data: stats, refetch: refetchStats } = useQuery<PipelineRunStats>({
    queryKey: ["run-stats", run.id],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs/${run.id}/stats`),
    refetchInterval: isActive ? 3000 : false,
  });

  // Refetch stats + tasks when run status transitions (e.g. running → completed)
  useEffect(() => {
    if (prevStatus.current !== run.status) {
      prevStatus.current = run.status;
      refetchStats();
    }
  }, [run.status, refetchStats]);

  const { data: tasks } = useQuery<PatientTaskSummary[]>({
    queryKey: ["run-tasks", run.id],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs/${run.id}/tasks?limit=50`),
    enabled: expanded,
    refetchInterval: expanded && isActive ? 5000 : false,
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.post<PipelineRun>(`/projects/${projectId}/pipeline/runs/${run.id}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["all-runs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => api.post<PipelineRun>(`/projects/${projectId}/pipeline/runs/${run.id}/retry-failed`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["all-runs", projectId] }),
  });

  const rerunMutation = useMutation({
    mutationFn: () => api.post<PipelineRun>(`/projects/${projectId}/pipeline/runs/${run.id}/rerun`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["all-runs", projectId] }),
  });

  const isTerminal = run.status === "completed" || run.status === "failed" || run.status === "cancelled";

  const progress = stats && stats.total > 0
    ? Math.round(((stats.completed + stats.failed + stats.no_match) / stats.total) * 100)
    : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 text-left"
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  {run.run_type === "sample" ? "Sample" : "Full"} Run
                </span>
                <Badge className={`text-xs ${statusColor(run.status)}`}>{run.status}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {run.total_patients} patients &middot; v{run.snapshot_version} &middot;{" "}
                {new Date(run.created_at).toLocaleString()}
              </p>
            </div>
          </button>
          <div className="flex items-center gap-2">
            {isActive && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1 text-xs"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
              >
                <XCircle className="h-3 w-3" />
                Cancel
              </Button>
            )}
            {run.status === "failed" || (stats && stats.failed > 0) ? (
              <Button
                variant="outline"
                size="sm"
                className="gap-1 text-xs"
                onClick={() => retryMutation.mutate()}
                disabled={retryMutation.isPending}
              >
                <RotateCcw className="h-3 w-3" />
                Retry Failed
              </Button>
            ) : null}
            {isTerminal && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1 text-xs"
                onClick={() => rerunMutation.mutate()}
                disabled={rerunMutation.isPending}
              >
                <RefreshCw className="h-3 w-3" />
                Rerun
              </Button>
            )}
          </div>
        </div>
        {isActive && <Progress value={progress} className="mt-2 h-1.5" />}
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4 pt-2">
          {/* Stats grid */}
          {stats && (
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
              {[
                { label: "Total", value: stats.total, icon: Activity },
                { label: "Queued", value: stats.queued, icon: Clock },
                { label: "Processing", value: stats.processing, icon: Activity },
                { label: "Completed", value: stats.completed, icon: CheckCircle2 },
                { label: "Failed", value: stats.failed, icon: AlertTriangle },
                { label: "No Match", value: stats.no_match, icon: XCircle },
              ].map(({ label, value, icon: Icon }) => (
                <div key={label} className="text-center">
                  <Icon className="mx-auto mb-1 h-4 w-4 text-muted-foreground" />
                  <p className="text-lg font-semibold tabular-nums">{value}</p>
                  <p className="text-xs text-muted-foreground">{label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Task list */}
          {tasks && tasks.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Patient Tasks
              </h4>
              <div className="max-h-64 overflow-y-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-1.5 text-left">Patient</th>
                      <th className="px-3 py-1.5 text-left">Status</th>
                      <th className="px-3 py-1.5 text-left">Error</th>
                      <th className="px-3 py-1.5 text-left">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tasks.map((task) => (
                      <tr key={task.id} className="border-t border-border">
                        <td className="px-3 py-1.5 font-mono text-xs">{task.patient_id.slice(0, 8)}</td>
                        <td className="px-3 py-1.5">
                          <Badge className={`text-xs ${statusColor(task.status)}`}>{task.status}</Badge>
                        </td>
                        <td className="max-w-48 truncate px-3 py-1.5 text-xs text-muted-foreground">
                          {task.error_message || "--"}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {task.started_at && task.completed_at
                            ? `${((new Date(task.completed_at).getTime() - new Date(task.started_at).getTime()) / 1000).toFixed(1)}s`
                            : "--"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Config snapshot */}
          <div>
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Config Snapshot
            </h4>
            <pre className="max-h-32 overflow-auto rounded-md bg-muted p-2 text-xs">
              {JSON.stringify(run.config_snapshot, null, 2)}
            </pre>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

interface QueueOverview {
  pipeline_runs: { queued: number; running: number; completed: number; failed: number; cancelled: number };
  background_jobs: { pending: number; running: number; completed: number; failed: number };
  worker_active: boolean;
  arq_queued: number;
}

function QueueStatus({ projectId }: { projectId: string }) {
  const { data: queue } = useQuery<QueueOverview>({
    queryKey: ["queue-overview", projectId],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/queue`),
    refetchInterval: 5000,
  });

  if (!queue) return null;

  const pr = queue.pipeline_runs;
  const bj = queue.background_jobs;

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <div className={`h-2.5 w-2.5 rounded-full ${queue.worker_active ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
              <span className="text-sm font-medium">
                Worker {queue.worker_active ? "Online" : "Offline"}
              </span>
              {queue.arq_queued > 0 && (
                <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-500/20 dark:text-blue-300 text-xs">
                  {queue.arq_queued} in queue
                </Badge>
              )}
            </div>
            <div className="h-4 border-l border-border" />
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">Pipeline:</span>
              {pr.queued + pr.running > 0 && (
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300 text-xs">
                  {pr.queued + pr.running} active
                </Badge>
              )}
              <span className="tabular-nums text-muted-foreground">
                {pr.completed} done · {pr.failed} failed
              </span>
            </div>
            <div className="h-4 border-l border-border" />
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">Jobs:</span>
              {bj.pending + bj.running > 0 && (
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300 text-xs">
                  {bj.pending + bj.running} active
                </Badge>
              )}
              <span className="tabular-nums text-muted-foreground">
                {bj.completed} done · {bj.failed} failed
              </span>
            </div>
          </div>
          <Layers className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

export default function JobDashboardPage() {
  const { projectId } = useParams<{ projectId: string }>();

  const { data: runs, isLoading } = useQuery<PipelineRun[]>({
    queryKey: ["all-runs", projectId],
    queryFn: () => api.get(`/projects/${projectId}/pipeline/runs`),
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">Job Dashboard</h2>
        <p className="text-sm text-muted-foreground">
          Monitor pipeline runs, cancel active jobs, and retry failures.
        </p>
      </div>

      <QueueStatus projectId={projectId!} />

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : runs && runs.length > 0 ? (
        <div className="space-y-3">
          {runs.map((run) => (
            <RunDetail key={run.id} projectId={projectId!} run={run} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-12">
          <Activity className="mb-3 h-8 w-8 text-muted-foreground" />
          <p className="font-medium text-foreground">No pipeline runs yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Create an event configuration and run a sample to get started.
          </p>
        </div>
      )}
    </div>
  );
}
