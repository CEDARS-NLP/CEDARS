import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, ArrowRight, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";

interface NlpRunResponse {
  dispatched_patients: number;
  mode: string;
  job_id: string | null;
}

interface ProjectStats {
  patients: { total: number; by_status: Record<string, number> };
  annotations: { total: number; reviewed: number; unreviewed: number };
}

/**
 * NLP processing page — v2 port of ops.py `do_nlp_processing` / job status.
 */
export default function NlpRunPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const { data: stats, refetch, isFetching } = useQuery<ProjectStats>({
    queryKey: ["project-stats", projectId],
    queryFn: () => api.get<ProjectStats>(`/projects/${projectId}/stats`),
    enabled: !!projectId,
    refetchInterval: 4000,
  });

  const run = useMutation({
    mutationFn: () => api.post<NlpRunResponse>(`/projects/${projectId}/workflow/nlp/run`),
    onSuccess: () => refetch(),
  });

  const byStatus = stats?.patients.by_status ?? {};

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">NLP processing</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Run the spaCy keyword + negation pipeline over patient notes. Matching
          sentences become annotations ready for adjudication.
        </p>
      </div>

      <div className="space-y-6 rounded-lg border border-border bg-card p-6">
        <div className="flex items-center gap-3">
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            <Play className="mr-2 h-4 w-4" />
            {run.isPending ? "Dispatching..." : "Run NLP processing"}
          </Button>
          <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {run.data && (
          <p className="text-sm text-muted-foreground">
            Dispatched {run.data.dispatched_patients} patient(s) ({run.data.mode}).
          </p>
        )}
        {run.error && (
          <p className="text-sm text-destructive">
            {run.error instanceof Error ? run.error.message : "Failed to dispatch"}
          </p>
        )}

        <div>
          <h2 className="mb-2 text-sm font-medium">Patient status</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {["new", "nlp_processing", "nlp_complete", "reviewing", "reviewed"].map((s) => (
              <div key={s} className="rounded-md border border-border p-3">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  {s.replace(/_/g, " ")}
                </div>
                <div className="text-xl font-semibold">{byStatus[s] ?? 0}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 border-t border-border pt-4">
          <Button onClick={() => navigate(`/projects/${projectId}/adjudicate`)}>
            Start adjudication
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
