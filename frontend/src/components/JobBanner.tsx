import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { BackgroundJobStatus } from "@/projects/types";

interface JobBannerProps {
  projectId: string;
  /** React Query cache key for the job status, e.g. ["nlp-job", projectId] */
  jobQueryKey: string[];
  /** GET endpoint for status, e.g. `/projects/${pid}/nlp/job/status` */
  statusUrl: string;
  /** POST endpoint to start the job */
  runUrl: string;
  /** POST endpoint to cancel the job */
  cancelUrl: string;
  /** Display label, e.g. "NLP Processing" */
  label: string;
  /** Optional summary renderer for completed/cancelled states */
  renderSummary?: (summary: Record<string, unknown>) => React.ReactNode;
  /** Called when a WebSocket progress message arrives (for cache invalidation) */
  onProgress?: (msg: BackgroundJobStatus) => void;
  /** Called when the job reaches a terminal state */
  onTerminal?: (status: string) => void;
}

export default function JobBanner({
  projectId,
  jobQueryKey,
  statusUrl,
  runUrl,
  cancelUrl,
  label,
  renderSummary,
  onProgress,
  onTerminal,
}: JobBannerProps) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [lastTerminalHandled, setLastTerminalHandled] = useState<string | null>(null);

  const { data: jobStatus, refetch: refetchStatus } = useQuery<BackgroundJobStatus | null>({
    queryKey: jobQueryKey,
    queryFn: () => api.get<BackgroundJobStatus | null>(statusUrl),
  });

  const runMutation = useMutation({
    mutationFn: () => api.post<BackgroundJobStatus>(runUrl, {}),
    onSuccess: () => {
      setLastTerminalHandled(null);
      refetchStatus();
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.post(cancelUrl, {}),
    onSuccess: () => refetchStatus(),
  });

  const isActive = jobStatus?.status === "running" || jobStatus?.status === "pending";

  // WebSocket for live progress
  useEffect(() => {
    if (!isActive || !jobStatus?.job_id) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/ws/projects/${projectId}/jobs/${jobStatus.job_id}`
    );
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as BackgroundJobStatus;
      queryClient.setQueryData<BackgroundJobStatus | null>(jobQueryKey, (old) =>
        old ? { ...old, ...msg } : null
      );
      onProgress?.(msg);
      if (["completed", "cancelled", "failed"].includes(msg.status)) {
        refetchStatus();
      }
    };

    ws.onerror = () => {
      /* non-fatal */
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [isActive, jobStatus?.job_id, projectId, queryClient, jobQueryKey, refetchStatus, onProgress]);

  // Fire onTerminal callback once when job reaches terminal state
  useEffect(() => {
    if (
      jobStatus &&
      ["completed", "cancelled", "failed"].includes(jobStatus.status) &&
      jobStatus.job_id !== lastTerminalHandled
    ) {
      setLastTerminalHandled(jobStatus.job_id);
      onTerminal?.(jobStatus.status);
    }
  }, [jobStatus, lastTerminalHandled, onTerminal]);

  const summary = jobStatus?.result_summary;
  const summaryNode = summary && renderSummary ? renderSummary(summary) : null;

  // No job — show run button
  if (
    !jobStatus ||
    !["pending", "running", "completed", "cancelled", "failed"].includes(jobStatus.status)
  ) {
    return (
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={() => runMutation.mutate()}
        disabled={runMutation.isPending}
      >
        <Play className="h-3.5 w-3.5" aria-hidden="true" />
        {runMutation.isPending ? "Starting\u2026" : `Run ${label}`}
      </Button>
    );
  }

  // Active (pending/running)
  if (isActive) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
              {label} running{"\u2026"}
            </p>
            {summaryNode && (
              <p className="text-xs text-amber-700 dark:text-amber-300">{summaryNode}</p>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="border-amber-300 text-amber-800 hover:bg-amber-100 dark:border-amber-500/50 dark:text-amber-200 dark:hover:bg-amber-500/20"
          >
            {cancelMutation.isPending ? "Cancelling\u2026" : "Cancel"}
          </Button>
        </div>
        <Progress value={jobStatus.progress} className="mt-2 h-1.5" />
      </div>
    );
  }

  // Completed
  if (jobStatus.status === "completed") {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/30 dark:bg-emerald-500/10">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-sm font-medium text-emerald-900 dark:text-emerald-200">
              {label} complete
            </p>
            {summaryNode && (
              <p className="text-xs text-emerald-700 dark:text-emerald-300">{summaryNode}</p>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
          >
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            Run Again
          </Button>
        </div>
      </div>
    );
  }

  // Cancelled
  if (jobStatus.status === "cancelled") {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
              {label} cancelled
            </p>
            {summaryNode && (
              <p className="text-xs text-amber-700 dark:text-amber-300">{summaryNode}</p>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
          >
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            Run Again
          </Button>
        </div>
      </div>
    );
  }

  // Failed
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-500/30 dark:bg-red-500/10">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <p className="text-sm font-medium text-red-900 dark:text-red-200">
            {label} failed
          </p>
          {summaryNode && (
            <p className="text-xs text-red-700 dark:text-red-300">{summaryNode}</p>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending}
        >
          <Play className="h-3.5 w-3.5" aria-hidden="true" />
          Retry
        </Button>
      </div>
    </div>
  );
}
