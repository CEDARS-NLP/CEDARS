import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { FunnelStats, UnifiedSession } from "@/projects/types";
import { AlertTriangle, Loader2, Play, RotateCcw } from "lucide-react";

interface ProjectLlmConfig {
  id: string;
  name: string;
  llm_provider: string | null;
  llm_model: string | null;
}

interface SampleRunSectionProps {
  projectId: string;
  session: UnifiedSession;
  funnel: FunnelStats | null;
  /** Saved queries differ from the last search that ran. */
  searchStale: boolean;
  onRefresh: () => void;
}

/**
 * Step 3 — try the model on the sample before paying for the whole cohort.
 *
 * Split out of the old EventConfigSection, which put this button directly under
 * the event-definition form: saving a typo in the description and launching a
 * billable run were the same gesture. Here the run stands alone, states what it
 * will cost before you start it, and refuses to run against a stale search.
 */
export default function SampleRunSection({
  projectId,
  session,
  funnel,
  searchStale,
  onRefresh,
}: SampleRunSectionProps) {
  const qc = useQueryClient();

  // Same query key as ProjectLayout, so this reads the warm cache.
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.get<ProjectLlmConfig>(`/projects/${projectId}`),
  });

  const metrics = session.metrics;
  const status = metrics?.llm_status;
  const running = status === "running";
  const total = metrics?.llm_total ?? 0;
  const done = (metrics?.llm_completed ?? 0) + (metrics?.llm_failed ?? 0);
  const hasRun = status === "completed" || (metrics?.llm_completed ?? 0) > 0;

  const runMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${session.id}/run-llm`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  const modelReady = !!project?.llm_provider && !!project?.llm_model;
  const matched = funnel?.matched_patients ?? 0;
  const isEditable = ["draft", "reviewing"].includes(session.status);
  const blocked = !modelReady || matched === 0 || searchStale;

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        The model reads the matched notes for each patient and decides whether your
        event happened. Check its answers on this sample first — the full cohort
        costs the same per note, with far more notes.
      </p>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <Fact label="Model">
          {modelReady ? (
            <span className="font-mono text-xs">{project!.llm_model}</span>
          ) : (
            <span className="text-muted-foreground">Not configured</span>
          )}
        </Fact>
        <Fact label="Patients in sample">{session.sample_size}</Fact>
        <Fact label="Matched the search">{funnel ? matched : "—"}</Fact>
        <Fact label="Estimated cost">
          {funnel?.estimated_cost != null
            ? `~$${funnel.estimated_cost.toFixed(2)}`
            : "—"}
        </Fact>
      </dl>

      {!modelReady && (
        <Notice>
          This project has no LLM provider yet. Choose one in{" "}
          <Link
            to={`/projects/${projectId}`}
            className="font-medium underline underline-offset-2"
          >
            project settings
          </Link>
          , then come back.
        </Notice>
      )}

      {modelReady && matched === 0 && (
        <Notice>
          The search matched no patients, so there is nothing to classify. Widen a
          query in step 2 and run the search again.
        </Notice>
      )}

      {modelReady && matched > 0 && searchStale && (
        <Notice>
          The queries changed after the last search. Run the search again in step 2
          so the model sees the right notes.
        </Notice>
      )}

      {running && (
        <div className="space-y-1.5">
          <Progress value={total > 0 ? (done / total) * 100 : 0} className="h-2" />
          <p className="text-xs text-muted-foreground tabular-nums">
            {total > 0
              ? `${done} of ${total} patients classified`
              : "Starting classification…"}
            {(metrics?.llm_failed ?? 0) > 0 && ` · ${metrics!.llm_failed} failed`}
          </p>
        </div>
      )}

      {status === "completed" && !running && (
        <p className="text-sm text-muted-foreground">
          Classified {metrics?.llm_completed ?? 0} patients
          {(metrics?.llm_failed ?? 0) > 0 && `, ${metrics!.llm_failed} failed`}
          {(metrics?.llm_no_match ?? 0) > 0 &&
            `, ${metrics!.llm_no_match} had no matching notes`}
          .
        </p>
      )}

      {status === "failed" && (
        <Notice tone="error">
          Classification failed before it finished. Check the provider credentials
          and model ID in project settings, then run it again.
        </Notice>
      )}

      {isEditable && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => runMutation.mutate()}
            disabled={blocked || running || runMutation.isPending}
          >
            {running || runMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Classifying
              </>
            ) : hasRun ? (
              <>
                <RotateCcw className="mr-2 h-4 w-4" />
                Run again on {matched} patients
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Run on {matched} patients
              </>
            )}
          </Button>
          {hasRun && !running && (
            <span className="text-xs text-muted-foreground">
              Re-running replaces the current results and clears your reviews.
            </span>
          )}
        </div>
      )}

      {runMutation.isError && (
        <Notice tone="error">{(runMutation.error as Error).message}</Notice>
      )}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums text-foreground">{children}</dd>
    </div>
  );
}

function Notice({
  children,
  tone = "warn",
}: {
  children: React.ReactNode;
  tone?: "warn" | "error";
}) {
  const cls =
    tone === "error"
      ? "border-destructive/30 bg-destructive/10 text-destructive"
      : "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200";
  return (
    <p className={`flex gap-2 rounded-md border px-3 py-2 text-sm ${cls}`}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}
