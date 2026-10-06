import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Search,
  Play,
  RefreshCw,
  BarChart3,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  BackgroundJobStatus,
  SearchQuery,
  NlpStats,
  NlpJob,
} from "@/projects/types";

interface ReprocessImpact {
  annotations: number;
  predictions: number;
  sentences: number;
}

export default function NlpQueriesSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [newQuery, setNewQuery] = useState("");
  const [newQueryName, setNewQueryName] = useState("");
  const [excludeNegated, setExcludeNegated] = useState(true);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const reprocessSubmitting = useRef(false);
  const impactPreview = useMutation({
    mutationFn: () => api.get<ReprocessImpact>(`/projects/${projectId}/nlp/reprocess-impact`),
  });

  const { data: queries } = useQuery<SearchQuery[]>({
    queryKey: ["nlp-queries", projectId],
    queryFn: () => api.get<SearchQuery[]>(`/projects/${projectId}/nlp/queries`),
  });

  const { data: stats } = useQuery<NlpStats>({
    queryKey: ["nlp-stats", projectId],
    queryFn: () => api.get<NlpStats>(`/projects/${projectId}/nlp/stats`),
  });

  const { data: latestJob } = useQuery<NlpJob | null>({
    queryKey: ["nlp-job", projectId],
    queryFn: () => api.get<NlpJob | null>(`/projects/${projectId}/nlp/job`),
    refetchInterval: (query) =>
      ["pending", "queued", "running"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  });

  const { data: latestBackgroundJob } = useQuery<BackgroundJobStatus | null>({
    queryKey: ["nlp-background-job", projectId],
    queryFn: () =>
      api.get<BackgroundJobStatus | null>(`/projects/${projectId}/nlp/job/status`),
    refetchInterval: (query) =>
      ["pending", "running"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  });

  const backgroundJobId = latestBackgroundJob?.job_id;
  const backgroundJobStatus = latestBackgroundJob?.status;

  useEffect(() => {
    if (!backgroundJobId || !backgroundJobStatus ||
      ["pending", "running"].includes(backgroundJobStatus)) {
      return;
    }

    void queryClient.invalidateQueries({ queryKey: ["nlp-stats", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["project-stats", projectId] });
  }, [backgroundJobId, backgroundJobStatus, projectId, queryClient]);

  const createQuery = useMutation({
    mutationFn: (body: { query: string; name?: string; exclude_negated: boolean }) =>
      api.post(`/projects/${projectId}/nlp/queries`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["nlp-queries", projectId] });
      setNewQuery("");
      setNewQueryName("");
      setExcludeNegated(true);
    },
  });

  const deleteQuery = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/projects/${projectId}/nlp/queries/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["nlp-queries", projectId] }),
  });

  const runNlp = useMutation({
    mutationFn: () =>
      api.post<BackgroundJobStatus>(`/projects/${projectId}/nlp/run`, {}),
    onSuccess: (job) => {
      queryClient.setQueryData(["nlp-background-job", projectId], job);
      queryClient.invalidateQueries({ queryKey: ["nlp-background-job", projectId] });
      queryClient.invalidateQueries({ queryKey: ["nlp-stats", projectId] });
    },
  });

  const reprocessNlp = useMutation({
    mutationFn: (impact: ReprocessImpact) => api.post(`/projects/${projectId}/nlp/reprocess`, {
      confirmed: true,
      expected_annotations: impact.annotations,
      expected_predictions: impact.predictions,
      expected_sentences: impact.sentences,
    }),
    onSuccess: () => {
      setReprocessOpen(false);
      queryClient.invalidateQueries({ queryKey: ["nlp-stats", projectId] });
      queryClient.invalidateQueries({ queryKey: ["nlp-job", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project-stats", projectId] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        impactPreview.reset();
        impactPreview.mutate();
      }
    },
    onSettled: () => { reprocessSubmitting.current = false; },
  });

  const backgroundJobIsRunning = ["pending", "running"].includes(
    latestBackgroundJob?.status ?? "",
  );
  const isRunning =
    runNlp.isPending || reprocessNlp.isPending || backgroundJobIsRunning ||
    ["pending", "queued", "running"].includes(latestJob?.status ?? "");
  const confirmReprocess = () => {
    if (!impactPreview.data || impactPreview.isPending || impactPreview.isError ||
      isRunning || reprocessSubmitting.current) return;
    reprocessSubmitting.current = true;
    reprocessNlp.mutate(impactPreview.data);
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">NLP search queries</h3>
        <p className="text-sm text-muted-foreground">
          Define keyword patterns to identify target sentences in clinical notes
        </p>
      </div>

      {/* Add query form */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-end gap-3">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">Query pattern</Label>
              <Input
                placeholder="e.g. troponin OR myocardial AND !suspected"
                value={newQuery}
                onChange={(e) => setNewQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newQuery.trim()) {
                    createQuery.mutate({
                      query: newQuery.trim(),
                      name: newQueryName.trim() || undefined,
                      exclude_negated: excludeNegated,
                    });
                  }
                }}
              />
            </div>
            <div className="w-48 space-y-1">
              <Label className="text-xs text-muted-foreground">Name (optional)</Label>
              <Input
                placeholder="e.g. MI detection"
                value={newQueryName}
                onChange={(e) => setNewQueryName(e.target.value)}
              />
            </div>
            <Button
              onClick={() =>
                createQuery.mutate({
                  query: newQuery.trim(),
                  name: newQueryName.trim() || undefined,
                  exclude_negated: excludeNegated,
                })
              }
              disabled={!newQuery.trim() || createQuery.isPending}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add
            </Button>
          </div>
          <label className="mt-3 flex w-fit items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={excludeNegated}
              onChange={(event) => setExcludeNegated(event.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            Hide negated mentions from manual review
          </label>
          <p className="mt-2 text-xs text-muted-foreground">
            Syntax: terms joined by <code className="rounded bg-muted px-1">OR</code> (any match)
            or <code className="rounded bg-muted px-1">AND</code> (all must match).
            Prefix with <code className="rounded bg-muted px-1">!</code> to exclude.
            Use <code className="rounded bg-muted px-1">*</code> for wildcards (e.g. embol*).
          </p>
        </CardContent>
      </Card>

      {/* Query list */}
      {queries && queries.length > 0 && (
        <div className="space-y-2">
          {queries.map((q) => (
            <div
              key={q.id}
              className="flex items-center justify-between rounded-md border bg-card px-4 py-2.5"
            >
              <div className="flex items-center gap-3">
                <Search className="h-4 w-4 text-muted-foreground" />
                <code className="text-sm font-medium">{q.query}</code>
                {q.name && (
                  <span className="text-xs text-muted-foreground">({q.name})</span>
                )}
                {q.exclude_negated && (
                  <span className="text-xs text-muted-foreground">
                    Negated mentions hidden
                  </span>
                )}
                {!q.is_active && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    inactive
                  </span>
                )}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                onClick={() => deleteQuery.mutate(q.id)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Run NLP + Stats */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Play className="h-4 w-4" />
              Run pipeline
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Button onClick={() => runNlp.mutate()} disabled={isRunning}>
                {runNlp.isPending || backgroundJobIsRunning ? "Processing..." : "Run NLP"}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  reprocessNlp.reset();
                  impactPreview.reset();
                  setReprocessOpen(true);
                  impactPreview.mutate();
                }}
                disabled={isRunning}
              >
                <RefreshCw className="mr-1.5 h-4 w-4" />
                {reprocessNlp.isPending ? "Reprocessing..." : "Reprocess all"}
              </Button>
            </div>
            {(runNlp.isError || reprocessNlp.isError) && (
              <p className="text-sm text-destructive">
                {((runNlp.error || reprocessNlp.error) as Error)?.message || "Pipeline failed"}
              </p>
            )}
            {latestBackgroundJob && (
              <div className="text-sm text-muted-foreground">
                Search run: {" "}
                <span
                  className={
                    latestBackgroundJob.status === "completed"
                      ? "text-emerald-600 dark:text-emerald-400"
                      : latestBackgroundJob.status === "failed"
                        ? "text-destructive"
                        : ""
                  }
                >
                  {latestBackgroundJob.status}
                </span>
                {latestBackgroundJob.status === "running" && (
                  <> ({latestBackgroundJob.progress}%)</>
                )}
                {latestBackgroundJob.error_message && (
                  <p className="mt-1 text-destructive">
                    {latestBackgroundJob.error_message}
                  </p>
                )}
              </div>
            )}
            {latestJob && (
              <div className="text-sm text-muted-foreground">
                Last full reprocess: {" "}
                <span
                  className={
                    latestJob.status === "completed"
                      ? "text-emerald-600 dark:text-emerald-400"
                      : latestJob.status === "failed"
                        ? "text-destructive"
                        : ""
                  }
                >
                  {latestJob.status}
                </span>
                {latestJob.completed_at && (
                  <> &mdash; {new Date(latestJob.completed_at).toLocaleString()}</>
                )}
                {latestJob.error_message && (
                  <p className="mt-1 text-destructive">{latestJob.error_message}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              NLP statistics
            </CardTitle>
          </CardHeader>
          <CardContent>
            {stats ? (
              <div className="grid grid-cols-2 gap-y-2 text-sm">
                <span className="text-muted-foreground">Total notes</span>
                <span className="font-medium">{stats.total_notes}</span>
                <span className="text-muted-foreground">Processed</span>
                <span className="font-medium">{stats.processed_notes}</span>
                <span className="text-muted-foreground">Total sentences</span>
                <span className="font-medium">{stats.total_sentences}</span>
                <span className="text-muted-foreground">Target sentences</span>
                <span className="font-medium text-emerald-600 dark:text-emerald-400">
                  {stats.target_sentences}
                </span>
                <span className="text-muted-foreground">Negated</span>
                <span className="font-medium">{stats.negated_sentences}</span>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No data yet. Run the NLP pipeline to process notes.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      <Dialog open={reprocessOpen} onOpenChange={(open) => {
        if (!reprocessSubmitting.current) setReprocessOpen(open);
      }}>
        <DialogContent showCloseButton={!reprocessNlp.isPending}>
          <DialogHeader>
            <DialogTitle>Reprocess all notes?</DialogTitle>
            <DialogDescription>
              This deletes existing annotations, predictions, and sentences, including manual review decisions.
              Source notes remain. The pipeline will regenerate the NLP results.
            </DialogDescription>
          </DialogHeader>
          {impactPreview.isPending && <p role="status">Loading deletion counts...</p>}
          {impactPreview.data && !impactPreview.isPending && !impactPreview.isError && (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt>Annotations to delete</dt><dd>{impactPreview.data.annotations}</dd>
              <dt>Predictions to delete</dt><dd>{impactPreview.data.predictions}</dd>
              <dt>Sentences to delete</dt><dd>{impactPreview.data.sentences}</dd>
            </dl>
          )}
          {impactPreview.isError && (
            <p role="alert" className="text-sm text-destructive">{impactPreview.error.message}</p>
          )}
          {reprocessNlp.isError && (
            <p role="alert" className="text-sm text-destructive">
              {reprocessNlp.error.message}
              {reprocessNlp.error instanceof ApiError && reprocessNlp.error.status === 409 &&
                " Review the refreshed counts and confirm again to proceed."}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={reprocessNlp.isPending}
              onClick={() => setReprocessOpen(false)}>Cancel</Button>
            {impactPreview.isError && (
              <Button variant="outline" onClick={() => impactPreview.mutate()}>Retry counts</Button>
            )}
            <Button variant="destructive" onClick={confirmReprocess}
              disabled={!impactPreview.data || impactPreview.isPending || impactPreview.isError || isRunning}>
              {reprocessNlp.isPending ? "Reprocessing..." : "Confirm reprocess"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
