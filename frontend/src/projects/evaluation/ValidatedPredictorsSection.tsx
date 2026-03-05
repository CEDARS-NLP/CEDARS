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
import type { ValidatedPredictor } from "@/projects/types";

export default function ValidatedPredictorsSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [activateTarget, setActivateTarget] = useState<string | null>(null);

  const { data: validated } = useQuery<ValidatedPredictor[]>({
    queryKey: ["validated-predictors", projectId],
    queryFn: () =>
      api.get<ValidatedPredictor[]>(`/projects/${projectId}/evaluation/validated`),
  });

  const activateMutation = useMutation({
    mutationFn: (validatedId: string) =>
      api.post<{ validated: ValidatedPredictor }>(
        `/projects/${projectId}/evaluation/validated/${validatedId}/activate`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["validated-predictors", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotations", projectId] });
      setActivateTarget(null);
    },
  });

  if (!validated || validated.length === 0) return null;

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
              This will set the selected configuration as the active predictor
              for this project. To run predictions on target sentences, go to
              the Annotations page after activation.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button variant="outline" onClick={() => setActivateTarget(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => activateTarget && activateMutation.mutate(activateTarget)}
              disabled={activateMutation.isPending}
            >
              {activateMutation.isPending ? "Activating\u2026" : "Activate Predictor"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Activation feedback */}
      <div aria-live="polite" aria-atomic="true">
        {activateMutation.isSuccess && activateMutation.data && (
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
            Predictor activated. Go to Annotations to run predictions.
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
