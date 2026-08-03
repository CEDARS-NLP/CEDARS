import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCw, ClipboardCheck } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface NlpStatus {
  total_patients: number;
  tasks_in_progress: number;
  tasks_completed: number;
}

/** Monitor NLP processing progress and re-run it if needed. */
export default function NlpRunPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const { data } = useQuery<NlpStatus>({
    queryKey: ["nlp-status", projectId],
    queryFn: () => api.get<NlpStatus>(`/projects/${projectId}/nlp/status`),
    enabled: !!projectId,
    refetchInterval: 4000,
  });

  async function rerun() {
    setError("");
    setRunning(true);
    try {
      await api.post(`/projects/${projectId}/nlp/run`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run NLP");
    } finally {
      setRunning(false);
    }
  }

  const total = data?.total_patients ?? 0;
  const completed = data?.tasks_completed ?? 0;
  const inProgress = data?.tasks_in_progress ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const idle = inProgress === 0;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Process notes</h1>
        <p className="text-sm text-muted-foreground">
          Runs the spaCy keyword &amp; negation pipeline across all patients.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Progress</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Progress value={pct} />
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-semibold text-foreground">{total}</p>
              <p className="text-xs text-muted-foreground">Patients</p>
            </div>
            <div>
              <p className="text-2xl font-semibold text-foreground">{inProgress}</p>
              <p className="text-xs text-muted-foreground">In progress</p>
            </div>
            <div>
              <p className="text-2xl font-semibold text-foreground">{completed}</p>
              <p className="text-xs text-muted-foreground">Completed</p>
            </div>
          </div>

          <div className="flex gap-3">
            <Button onClick={rerun} disabled={running} variant="outline">
              {running ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Dispatching...
                </>
              ) : (
                <>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Re-run NLP
                </>
              )}
            </Button>
            <Button asChild disabled={!idle}>
              <Link to={`/projects/${projectId}/adjudicate`}>
                <ClipboardCheck className="mr-2 h-4 w-4" />
                Go to Adjudication
              </Link>
            </Button>
          </div>
          {!idle && (
            <p className="text-xs text-muted-foreground">
              Processing is running. This page updates automatically.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
