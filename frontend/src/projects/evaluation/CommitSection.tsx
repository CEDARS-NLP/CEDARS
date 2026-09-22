import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { UnifiedSession, CommitResult } from "@/projects/types";
import { CheckCircle2, Loader2, Lock } from "lucide-react";

interface CommitSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

/**
 * Step 5 — lock the configuration and run it on every patient.
 *
 * The one irreversible action in the workflow, so it says what it freezes and
 * how far along the review is before you press it.
 */
export default function CommitSection({
  projectId,
  session,
  onRefresh,
}: CommitSectionProps) {
  const qc = useQueryClient();
  const reviewed = session.metrics?.total_reviewed ?? 0;
  const pending = session.metrics?.total_pending ?? 0;

  const commitMutation = useMutation({
    mutationFn: () =>
      api.post<CommitResult>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/commit`,
        {}
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        Committing freezes this session&rsquo;s queries and event definition, then
        runs them over every patient in the project. The sample results and your
        judgments stay as the record of why you trusted it.
      </p>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Queries to lock</dt>
          <dd className="mt-0.5 font-medium tabular-nums">
            {session.search_queries.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Patients you judged</dt>
          <dd className="mt-0.5 font-medium tabular-nums">{reviewed}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Agreement so far</dt>
          <dd className="mt-0.5 font-medium tabular-nums">
            {reviewed > 0
              ? `${((session.metrics?.accuracy ?? 0) * 100).toFixed(0)}%`
              : "—"}
          </dd>
        </div>
      </dl>

      {reviewed === 0 && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          You haven&rsquo;t judged any sample patients yet, so there is no evidence
          the model agrees with you. Judge a handful in step 4 first.
        </p>
      )}
      {reviewed > 0 && pending > 0 && (
        <p className="text-sm text-muted-foreground">
          {pending} sample {pending === 1 ? "patient is" : "patients are"} still
          unjudged. You can commit now and finish reviewing later.
        </p>
      )}

      <Button
        onClick={() => commitMutation.mutate()}
        disabled={commitMutation.isPending}
      >
        {commitMutation.isPending ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Committing
          </>
        ) : (
          <>
            <Lock className="mr-2 h-4 w-4" /> Commit and run on all patients
          </>
        )}
      </Button>

      {commitMutation.isError && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(commitMutation.error as Error).message}
        </p>
      )}

      {commitMutation.isSuccess && commitMutation.data && (
        <p className="flex items-center gap-2 rounded-md border border-emerald-600/30 bg-emerald-600/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300">
          <CheckCircle2 className="h-4 w-4" />
          Started. Processing {commitMutation.data.total_patients} patients.
        </p>
      )}
    </div>
  );
}
