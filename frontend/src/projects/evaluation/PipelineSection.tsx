import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { XCircle, RefreshCw, Loader2, CheckCircle2 } from "lucide-react";

interface PipelineStats {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  no_match: number;
  is_cancelled: boolean;
}

interface PipelineSectionProps {
  projectId: string;
  sessionId: string;
  sessionStatus: string;
  onRefresh: () => void;
}

export default function PipelineSection({
  projectId,
  sessionId,
  sessionStatus,
  onRefresh,
}: PipelineSectionProps) {
  const qc = useQueryClient();

  const isVisible = ["committed", "completed"].includes(sessionStatus);

  const { data: stats, isLoading } = useQuery<PipelineStats>({
    queryKey: ["pipeline-stats", projectId, sessionId],
    queryFn: () =>
      api.get<PipelineStats>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/pipeline/stats`
      ),
    enabled: isVisible,
    refetchInterval: (query) => {
      const d = query.state.data as PipelineStats | undefined;
      if (!d) return false;
      // Poll while there are queued or processing patients
      return d.queued > 0 || d.processing > 0 ? 3000 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${sessionId}/pipeline/cancel`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline-stats", projectId, sessionId] });
      onRefresh();
    },
  });

  const resumeMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${sessionId}/pipeline/resume`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline-stats", projectId, sessionId] });
      onRefresh();
    },
  });

  const rerunMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${sessionId}/pipeline/rerun`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline-stats", projectId, sessionId] });
      onRefresh();
    },
  });

  if (!isVisible) return null;

  if (isLoading || !stats) {
    return (
      <div className="rounded-lg border p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading pipeline status...
        </div>
      </div>
    );
  }

  const processed = stats.completed + stats.failed + stats.no_match;
  const isRunning = stats.queued > 0 || stats.processing > 0;
  const isDone = !isRunning && stats.total > 0;
  const progress = stats.total > 0 ? (processed / stats.total) * 100 : 0;

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Full Pipeline</h2>
        <div className="flex items-center gap-2">
          {isRunning && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => resumeMutation.mutate()}
                disabled={resumeMutation.isPending}
              >
                {resumeMutation.isPending ? (
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Resuming...</>
                ) : (
                  <><RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Resume</>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="text-amber-700 border-amber-300 hover:bg-amber-50"
              >
                {cancelMutation.isPending ? (
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Cancelling...</>
                ) : (
                  <><XCircle className="mr-1.5 h-3.5 w-3.5" /> Cancel</>
                )}
              </Button>
            </>
          )}
          {isDone && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => rerunMutation.mutate()}
              disabled={rerunMutation.isPending}
            >
              {rerunMutation.isPending ? (
                <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Starting...</>
              ) : (
                <><RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Re-run Pipeline</>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div className="space-y-1.5">
          <Progress value={progress} className="h-2" />
          <p className="text-xs text-muted-foreground">
            {processed} / {stats.total} patients processed
          </p>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-5 gap-3 text-center text-sm">
        <div>
          <div className="text-lg font-semibold tabular-nums">{stats.total}</div>
          <div className="text-muted-foreground">Total</div>
        </div>
        <div>
          <div className="text-lg font-semibold tabular-nums text-green-600">{stats.completed}</div>
          <div className="text-muted-foreground">Matched</div>
        </div>
        <div>
          <div className="text-lg font-semibold tabular-nums text-zinc-500">{stats.no_match}</div>
          <div className="text-muted-foreground">No Match</div>
        </div>
        <div>
          <div className="text-lg font-semibold tabular-nums text-red-600">{stats.failed}</div>
          <div className="text-muted-foreground">Failed</div>
        </div>
        <div>
          <div className="text-lg font-semibold tabular-nums text-amber-600">{stats.queued + stats.processing}</div>
          <div className="text-muted-foreground">Pending</div>
        </div>
      </div>

      {/* Status message */}
      {isDone && !stats.is_cancelled && (
        <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          <CheckCircle2 className="h-4 w-4" />
          Pipeline complete. {stats.completed} patients matched, {stats.no_match} no match.
          {stats.failed > 0 && ` ${stats.failed} failed.`}
        </div>
      )}
      {stats.is_cancelled && (
        <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <XCircle className="h-4 w-4" />
          Pipeline was cancelled. {processed} of {stats.total} patients processed.
        </div>
      )}

      {resumeMutation.isError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Resume failed: {(resumeMutation.error as Error).message}
        </div>
      )}
      {rerunMutation.isError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(rerunMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
