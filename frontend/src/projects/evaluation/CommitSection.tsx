import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { UnifiedSession, CommitResult, SessionCost } from "@/projects/types";
import { approxCost, formatCost, formatTokens } from "@/lib/cost";
import { CheckCircle2, Loader2, Lock } from "lucide-react";

interface ReprocessImpact {
  annotations: number;
  predictions: number;
  sentences: number;
}

interface CommitSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
  cost?: SessionCost | null;
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
  cost,
}: CommitSectionProps) {
  const projection = cost?.projection ?? null;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const qc = useQueryClient();
  const reviewed = session.metrics?.total_reviewed ?? 0;
  const pending = session.metrics?.total_pending ?? 0;

  const impactPreview = useMutation({
    mutationFn: () =>
      api.get<ReprocessImpact>(`/projects/${projectId}/nlp/reprocess-impact`),
    retry: false,
  });

  const commitMutation = useMutation({
    mutationFn: (impact: ReprocessImpact) =>
      api.post<CommitResult>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/commit`,
        {
          reprocess: {
            confirmed: true,
            expected_annotations: impact.annotations,
            expected_predictions: impact.predictions,
            expected_sentences: impact.sentences,
          },
        }
      ),
    retry: false,
    onSuccess: () => {
      setConfirmOpen(false);
      for (const key of [
        "nlp-queries", "nlp-stats", "nlp-background-job", "annotation-stats",
        "project-stats", "project", "eval-sessions",
      ]) {
        qc.invalidateQueries({ queryKey: [key, projectId] });
      }
      qc.invalidateQueries({ queryKey: ["annotation-context"] });
      for (const key of [
        "eval-session", "eval-results", "eval-metrics", "eval-next-result",
        "eval-result-notes", "funnel", "cost",
      ]) {
        qc.invalidateQueries({ queryKey: [key, projectId, session.id] });
      }
      onRefresh();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        impactPreview.mutate();
      }
    },
  });

  function openConfirmation() {
    commitMutation.reset();
    impactPreview.reset();
    setConfirmOpen(true);
    impactPreview.mutate();
  }

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        Committing freezes this session&rsquo;s queries and event definition, then
        runs them over every patient in the project. The sample results and your
        judgments stay as the record for the performance of this query and prompt on the sample before the pipeline was run on all of the patients.
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

      {projection && (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <p>
            <span className="text-muted-foreground">Projected cost to run on all </span>
            <span className="tabular-nums">{projection.total_patients}</span>
            <span className="text-muted-foreground"> patients: </span>
            <span className="font-medium tabular-nums">
              {projection.estimated_cost != null
                ? approxCost(projection.estimated_cost)
                : "no per-token price for this model"}
            </span>
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {projection.basis !== "sample"
              ? "A rough guess: the model hasn't run on a sample yet. Run step 3 for a figure based on real token counts."
              : projection.patients_to_classify === 0
              ? "Every patient the search is expected to match was already classified in the sample, so committing adds no model cost."
              : `Based on the ${projection.sample_patients_classified} sample patients the model read (${formatTokens(
                  projection.tokens_per_patient
                )} tokens each). About ${projection.projected_matched_patients} patients should match the search; ${projection.patients_to_classify} still need the model, the rest reuse the sample's answers.`}
          </p>
        </div>
      )}

      {reviewed === 0 && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          Not enough sample patients have been judged yet, so there is no evidence
          about the performance for this model. You need to judge more patients to get a performance estimate.
        </p>
      )}
      {reviewed > 0 && pending > 0 && (
        <p className="text-sm text-muted-foreground">
          {pending} sample {pending === 1 ? "patient is" : "patients are"} still
          unjudged. You can commit now and finish reviewing later.
        </p>
      )}

      <Button onClick={openConfirmation} disabled={commitMutation.isSuccess}>
        <Lock className="mr-2 h-4 w-4" /> Save and process all patients
      </Button>

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!commitMutation.isPending) setConfirmOpen(open);
        }}
      >
        <DialogContent showCloseButton={!commitMutation.isPending}>
          <DialogHeader>
            <DialogTitle>Save and process all patients?</DialogTitle>
            <DialogDescription>
              This locks the queries and event definition, then sends the matched
              notes for every patient to the model. You cannot undo this action.
            </DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Patients in the project</dt>
            <dd className="tabular-nums">{projection?.total_patients ?? "—"}</dd>
            <dt className="text-muted-foreground">Still to send to the model</dt>
            <dd className="tabular-nums">{projection?.patients_to_classify ?? "—"}</dd>
            <dt className="text-muted-foreground">Estimated tokens</dt>
            <dd className="tabular-nums">
              {projection
                ? formatTokens(projection.prompt_tokens + projection.completion_tokens)
                : "—"}
            </dd>
            <dt className="text-muted-foreground">Estimated cost</dt>
            <dd className="font-medium tabular-nums">
              {projection?.estimated_cost != null
                ? approxCost(projection.estimated_cost)
                : "no per-token price for this model"}
            </dd>
          </dl>
          <p className="text-xs text-muted-foreground">
            {projection?.basis !== "sample"
              ? "A rough guess: the model hasn't run on a sample yet, so no real token counts exist."
              : projection.patients_to_classify === 0
              ? "Every patient the search is expected to match was already classified in the sample, so this adds no model cost."
              : "Scaled from the tokens the model used on your sample, so it is a ballpark. Patients already classified in the sample are reused and cost nothing more."}
          </p>
          {impactPreview.isPending && (
            <p role="status" className="text-sm text-muted-foreground">
              Checking existing results
            </p>
          )}
          {impactPreview.isSuccess && Object.values(impactPreview.data).some((count) => count > 0) && (
            <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              This replaces {impactPreview.data.annotations} annotations, {impactPreview.data.predictions} predictions,
              and {impactPreview.data.sentences} sentences. You will lose existing project results and review decisions.
              Your sample results and judgments stay in this session.
            </p>
          )}
          {impactPreview.isSuccess && Object.values(impactPreview.data).every((count) => count === 0) && (
            <p className="text-sm text-muted-foreground">
              No existing project results or review decisions to replace.
            </p>
          )}
          {impactPreview.isError && (
            <div role="alert" className="space-y-2 text-sm text-destructive">
              <p>Could not check existing results. Try again before committing.</p>
              <p>{impactPreview.error.message}</p>
              <Button variant="outline" onClick={() => impactPreview.mutate()}>
                Try again
              </Button>
            </div>
          )}
          {commitMutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {commitMutation.error instanceof ApiError && commitMutation.error.status === 409
                ? "Project results changed. Review the updated counts and confirm again."
                : commitMutation.error.message}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={commitMutation.isPending}
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (impactPreview.isSuccess && !commitMutation.isPending) {
                  commitMutation.mutate(impactPreview.data);
                }
              }}
              disabled={commitMutation.isPending || !impactPreview.isSuccess}
            >
              {commitMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Committing
                </>
              ) : (
                "Run on all patients"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {commitMutation.isSuccess && commitMutation.data && (
        <p className="flex items-center gap-2 rounded-md border border-emerald-600/30 bg-emerald-600/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300">
          <CheckCircle2 className="h-4 w-4" />
          Started. Processing {commitMutation.data.total_patients} patients
          {commitMutation.data.estimated_cost != null &&
            ` · estimated ${formatCost(commitMutation.data.estimated_cost)} more`}
          .
        </p>
      )}
    </div>
  );
}
