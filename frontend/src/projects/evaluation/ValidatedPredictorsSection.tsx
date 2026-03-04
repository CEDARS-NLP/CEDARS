import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, Star } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ValidatedPredictor, BulkEstimate } from "@/projects/types";

export default function ValidatedPredictorsSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [activateTarget, setActivateTarget] = useState<string | null>(null);

  const { data: validated } = useQuery<ValidatedPredictor[]>({
    queryKey: ["validated-predictors", projectId],
    queryFn: () =>
      api.get<ValidatedPredictor[]>(`/projects/${projectId}/evaluation/validated`),
  });

  const { data: estimate } = useQuery<BulkEstimate>({
    queryKey: ["bulk-estimate", projectId],
    queryFn: () =>
      api.get<BulkEstimate>(`/projects/${projectId}/annotations/estimate`),
    enabled: !!activateTarget,
  });

  const activateMutation = useMutation({
    mutationFn: (validatedId: string) =>
      api.post<{ validated: ValidatedPredictor; bulk_run: { annotations_created: number; total_sentences: number; token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } } | null }>(
        `/projects/${projectId}/evaluation/validated/${validatedId}/activate`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["validated-predictors", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotations", projectId] });
      queryClient.invalidateQueries({ queryKey: ["bulk-estimate", projectId] });
      setActivateTarget(null);
    },
  });

  if (!validated || validated.length === 0) return null;

  const bulkRun = activateMutation.data as { bulk_run?: { annotations_created: number; token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } } } | undefined;

  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Shield className="h-4 w-4" aria-hidden="true" />
        Validated Configurations
      </h3>
      <div className="space-y-2">
        {validated.map((vp) => (
          <div
            key={vp.id}
            className="flex items-center gap-4 rounded-lg border border-border bg-card px-5 py-3"
          >
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">{vp.name}</span>
                {vp.is_active && (
                  <Badge className="gap-1 bg-emerald-600 text-white">
                    <Star className="h-3 w-3" aria-hidden="true" />
                    Active
                  </Badge>
                )}
              </div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                F1: {((vp.metrics_snapshot.f1 ?? 0) * 100).toFixed(1)}% &mdash;
                Threshold: {vp.threshold}
              </p>
            </div>
            <span className="text-xs text-muted-foreground">
              {new Date(vp.created_at).toLocaleDateString()}
            </span>
            {!vp.is_active && (
              <Button
                variant="outline"
                size="sm"
                aria-label={`Activate ${vp.name}`}
                onClick={() => setActivateTarget(vp.id)}
              >
                <Star className="mr-1.5 h-3.5 w-3.5" />
                Activate
              </Button>
            )}
          </div>
        ))}
      </div>

      {/* Activation confirmation dialog */}
      <Dialog open={!!activateTarget} onOpenChange={(open) => !open && setActivateTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Activate predictor?</DialogTitle>
            <DialogDescription>
              This will run predictions on all target sentences that haven't been
              processed yet. This may create a large number of annotation records.
            </DialogDescription>
          </DialogHeader>

          {/* Token estimate */}
          {estimate && estimate.sentence_count > 0 && (
            <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-sm">
              <p className="mb-2 font-medium text-foreground">Estimated token usage</p>
              <div className="grid grid-cols-2 gap-y-1.5 text-sm">
                <span className="text-muted-foreground">Sentences to process</span>
                <span className="font-medium tabular-nums">{estimate.sentence_count.toLocaleString()}</span>
                <span className="text-muted-foreground">Prompt tokens</span>
                <span className="font-medium tabular-nums">{estimate.estimated_prompt_tokens.toLocaleString()}</span>
                <span className="text-muted-foreground">Completion tokens</span>
                <span className="font-medium tabular-nums">{estimate.estimated_completion_tokens.toLocaleString()}</span>
                <span className="text-muted-foreground">Total tokens</span>
                <span className="font-medium tabular-nums">{estimate.estimated_total_tokens.toLocaleString()}</span>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setActivateTarget(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => activateTarget && activateMutation.mutate(activateTarget)}
              disabled={activateMutation.isPending}
            >
              {activateMutation.isPending ? "Activating\u2026" : "Activate & Run Predictions"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Activation feedback */}
      <div aria-live="polite" aria-atomic="true">
        {activateMutation.isSuccess && activateMutation.data && (
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
            Activated.
            {bulkRun?.bulk_run
              ? ` Created ${bulkRun.bulk_run.annotations_created} annotations.`
              : ""}
            {bulkRun?.bulk_run?.token_usage
              ? ` Used ${bulkRun.bulk_run.token_usage.total_tokens.toLocaleString()} tokens.`
              : ""}
          </p>
        )}
        {activateMutation.isError && (
          <p className="text-sm font-medium text-destructive" role="alert">
            {activateMutation.error instanceof Error
              ? activateMutation.error.message
              : "Activation failed"}
          </p>
        )}
      </div>
    </div>
  );
}
