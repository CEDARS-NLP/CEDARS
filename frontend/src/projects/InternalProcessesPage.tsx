import { useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Lock, RefreshCw, Database, Trash2, Activity } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";

interface SimpleJobResponse {
  status: string;
  detail: string;
  affected: number | null;
}

interface QueueInfo {
  queues: { name: string; queued: number; running?: number }[];
  workers: unknown[];
}

/**
 * Internal processes page (platform-admin only) — v2 port of ops.py
 * `internal_processes` plus the technical-admin operations.
 */
export default function InternalProcessesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const base = `/projects/${projectId}/workflow/internal`;

  const { data: queues, refetch, isFetching, error: queueError } = useQuery<QueueInfo>({
    queryKey: ["workflow-queues", projectId],
    queryFn: () => api.get<QueueInfo>(`${base}/queues`),
    enabled: !!projectId,
    refetchInterval: 5000,
    retry: false,
  });

  const unlockAll = useMutation({
    mutationFn: () => api.post<SimpleJobResponse>(`${base}/unlock-all`),
    onSuccess: () => refetch(),
  });
  const rebuild = useMutation({
    mutationFn: () => api.post<SimpleJobResponse>(`${base}/rebuild-results`),
    onSuccess: () => refetch(),
  });
  const rerun = useMutation({
    mutationFn: () => api.post<SimpleJobResponse>(`${base}/rerun-nlp`),
    onSuccess: () => refetch(),
  });
  const drop = useMutation({
    mutationFn: () => api.post<SimpleJobResponse>(`${base}/drop-data`),
    onSuccess: () => refetch(),
  });

  const lastResult =
    unlockAll.data ?? rebuild.data ?? rerun.data ?? drop.data ?? null;
  const lastError =
    unlockAll.error ?? rebuild.error ?? rerun.error ?? drop.error ?? queueError;

  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Internal processes</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Technical administration. Platform-admin only — these operations affect
          all data in this project.
        </p>
      </div>

      {lastError && (
        <p className="text-sm text-destructive">
          {lastError instanceof Error ? lastError.message : "Operation failed"}
        </p>
      )}
      {lastResult && (
        <p className="text-sm text-emerald-600">
          {lastResult.detail}
          {lastResult.affected != null ? ` (${lastResult.affected})` : ""}
        </p>
      )}

      {/* Queue status */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-medium">
            <Activity className="h-4 w-4" />
            Queue & workers
          </h2>
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
        <div className="space-y-1 text-sm">
          {(queues?.queues ?? []).map((q) => (
            <div key={q.name} className="flex justify-between">
              <span className="text-muted-foreground">{q.name}</span>
              <span className="tabular-nums">queued: {q.queued}</span>
            </div>
          ))}
          <div className="pt-1 text-xs text-muted-foreground">
            Active workers: {queues?.workers.length ?? 0}
          </div>
        </div>
      </section>

      {/* Operations */}
      <section className="space-y-3">
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <div>
            <div className="text-sm font-medium">Unlock all patients</div>
            <div className="text-xs text-muted-foreground">
              Release every locked patient (use if reviews were interrupted).
            </div>
          </div>
          <Button variant="outline" disabled={unlockAll.isPending} onClick={() => unlockAll.mutate()}>
            <Lock className="mr-2 h-4 w-4" />
            Unlock all
          </Button>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <div>
            <div className="text-sm font-medium">Rebuild results</div>
            <div className="text-xs text-muted-foreground">
              Recompute the per-patient results table used for export.
            </div>
          </div>
          <Button variant="outline" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>
            <Database className="mr-2 h-4 w-4" />
            Rebuild
          </Button>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <div>
            <div className="text-sm font-medium">Re-run NLP</div>
            <div className="text-xs text-muted-foreground">
              Clear annotations and reprocess all patients with the current query.
            </div>
          </div>
          <Button variant="outline" disabled={rerun.isPending} onClick={() => rerun.mutate()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Re-run
          </Button>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-destructive/40 bg-card p-4">
          <div>
            <div className="text-sm font-medium text-destructive">Drop project data</div>
            <div className="text-xs text-muted-foreground">
              Permanently delete all patients, notes, annotations, and results.
            </div>
          </div>
          <Button
            variant="outline"
            disabled={drop.isPending}
            onClick={() => {
              if (
                window.confirm(
                  "This permanently deletes all patients, notes, annotations, and results for this project. Continue?"
                )
              ) {
                drop.mutate();
              }
            }}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Drop data
          </Button>
        </div>
      </section>
    </div>
  );
}
