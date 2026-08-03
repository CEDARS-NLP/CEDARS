import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Unlock, ExternalLink, Activity } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface InternalStatus {
  rq_dashboard_url: string;
  queue_length: number;
  failed_jobs: number;
  successful_jobs: number;
}

/** Technical admin operations (ports internal_processes.html). */
export default function InternalProcessesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [message, setMessage] = useState("");

  const { data } = useQuery<InternalStatus>({
    queryKey: ["internal", projectId],
    queryFn: () => api.get<InternalStatus>(`/projects/${projectId}/internal`),
    enabled: !!projectId,
    refetchInterval: 5000,
  });

  const { data: pines } = useQuery<{ available: boolean }>({
    queryKey: ["pines-status", projectId],
    queryFn: () => api.get<{ available: boolean }>(`/projects/${projectId}/internal/pines/status`),
    enabled: !!projectId,
  });

  async function runOp(path: string, confirmMsg?: string) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    try {
      const resp = await api.post<{ message: string }>(
        `/projects/${projectId}/internal/${path}`
      );
      setMessage(resp.message);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Operation failed");
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Internal processes</h1>
        <p className="text-sm text-muted-foreground">
          Technical operations for administrators.
        </p>
      </div>

      {message && (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          {message}
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-2xl font-semibold">{data?.queue_length ?? 0}</p>
            <p className="text-xs text-muted-foreground">Queued jobs</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-2xl font-semibold">{data?.successful_jobs ?? 0}</p>
            <p className="text-xs text-muted-foreground">Successful jobs</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-2xl font-semibold text-destructive">
              {data?.failed_jobs ?? 0}
            </p>
            <p className="text-xs text-muted-foreground">Failed jobs</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Operations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Rebuild results</p>
              <p className="text-xs text-muted-foreground">
                Recompute the RESULTS collection for all patients.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => runOp("update_results")}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Rebuild
            </Button>
          </div>
          <div className="flex items-center justify-between border-t border-border pt-3">
            <div>
              <p className="text-sm font-medium">Unlock all patients</p>
              <p className="text-xs text-muted-foreground">
                Release all patient locks. Avoid running while others are
                annotating.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                runOp("unlock_all", "Unlock all patients? This may disrupt active reviewers.")
              }
            >
              <Unlock className="mr-2 h-4 w-4" />
              Unlock all
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Services</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            PINES model server:{" "}
            <span
              className={
                pines?.available ? "font-medium text-emerald-600" : "text-muted-foreground"
              }
            >
              {pines?.available ? "available" : "unavailable"}
            </span>
          </div>
          {data?.rq_dashboard_url && (
            <a
              href={data.rq_dashboard_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-link hover:underline"
            >
              <ExternalLink className="h-4 w-4" />
              Open RQ dashboard
            </a>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
