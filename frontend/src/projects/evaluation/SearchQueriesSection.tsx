import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { UnifiedSession, SearchQueryItem, SuggestedQuery, BackgroundJobStatus } from "@/projects/types";
import NotePreviewList from "./NotePreviewList";
import {
  ChevronDown,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Play,
  ArrowRight,
} from "lucide-react";

interface ReprocessImpact {
  annotations: number;
  predictions: number;
  sentences: number;
}

interface SearchQueriesSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
  /** Set when the saved queries no longer match the last search that was run. */
  searchStale: boolean;
  onQueriesSaved: () => void;
  onSearchRun: () => void;
  matchedPatients: number | null;
  onContinue: () => void;
}

function signature(queries: SearchQueryItem[]): string {
  return JSON.stringify(queries.map((q) => [q.type, q.query.trim()]));
}

function displaySections(session: UnifiedSession): SearchQueryItem[] {
  return session.query_sections.length > 0
    ? session.query_sections
    : session.search_queries;
}

/** Compose the plain-English event definition the suggester reads. */
function eventBrief(session: UnifiedSession): string {
  return [
    session.event_name,
    session.event_description,
    session.include_criteria && `Counts as the event: ${session.include_criteria}`,
    session.exclude_criteria && `Does not count: ${session.exclude_criteria}`,
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * Step 2 — which notes are worth sending to the model.
 *
 * Rewritten around a local draft. The previous version PUT the whole session on
 * every add and delete, and had no way to edit a query you had already added —
 * you deleted it and retyped it. One real session in production logged 35 saves
 * against a single search run.
 */
export default function SearchQueriesSection({
  projectId,
  session,
  onRefresh,
  searchStale,
  onQueriesSaved,
  onSearchRun,
  matchedPatients,
  onContinue,
}: SearchQueriesSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const initialSections = displaySections(session);
  const [draft, setDraft] = useState<SearchQueryItem[]>(initialSections);
  const [excludeNegated, setExcludeNegated] = useState(session.exclude_negated);
  const [expanded, setExpanded] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestedQuery[]>([]);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const [jobStarted, setJobStarted] = useState(false);

  const { data: backgroundJob } = useQuery({
    queryKey: ["nlp-background-job", projectId],
    queryFn: () => api.get<BackgroundJobStatus | null>(`/projects/${projectId}/nlp/job/status`),
    enabled: jobStarted,
    refetchInterval: (query) => ["pending", "running"].includes(query.state.data?.status ?? "") ? 2000 : false,
  });

  const impactPreview = useMutation({
    mutationFn: () => api.get<ReprocessImpact>(`/projects/${projectId}/nlp/reprocess-impact`),
  });

  const runAllMutation = useMutation({
    mutationFn: (impact: ReprocessImpact | undefined) => api.post<{ status: string }>(
      `/projects/${projectId}/evaluation/sessions/${session.id}/queries/run-all`,
      impact ? {
        confirmed: true,
        expected_annotations: impact.annotations,
        expected_predictions: impact.predictions,
        expected_sentences: impact.sentences,
      } : {},
    ),
    onSuccess: () => {
      setReprocessOpen(false);
      setJobStarted(true);
      for (const key of ["nlp-queries", "nlp-stats", "nlp-background-job", "annotation-stats", "project-stats"]) {
        qc.invalidateQueries({ queryKey: [key, projectId] });
      }
      onRefresh();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409 && reprocessOpen) {
        impactPreview.mutate();
      }
    },
  });

  const saved = signature(displaySections(session));
  const [syncedKey, setSyncedKey] = useState(saved);
  const [savedSectionsKey, setSavedSectionsKey] = useState(saved);

  // Adopt the server's queries when they change, during render rather than in an
  // effect, so a refetch never lands a stale draft in the inputs.
  if (saved !== syncedKey) {
    setSyncedKey(saved);
    setSavedSectionsKey(saved);
    setDraft(displaySections(session));
  }

  // Same render-time sync for the negation option, so a refetch never lands a
  // stale checkbox next to a fresh query list.
  const savedNegated = session.exclude_negated;
  const [syncedNegated, setSyncedNegated] = useState(savedNegated);
  if (savedNegated !== syncedNegated) {
    setSyncedNegated(savedNegated);
    setExcludeNegated(savedNegated);
  }

  const dirty = signature(draft) !== savedSectionsKey || excludeNegated !== savedNegated;

  const saveMutation = useMutation({
    mutationFn: (payload: { queries: SearchQueryItem[]; excludeNegated: boolean }) =>
      api.put<UnifiedSession>(`/projects/${projectId}/evaluation/sessions/${session.id}/queries`, {
        search_queries: payload.queries,
        exclude_negated: payload.excludeNegated,
      }),
    onSuccess: (data) => {
      const sections = displaySections(data);
      const sectionsKey = signature(sections);
      setDraft(sections);
      setSavedSectionsKey(sectionsKey);
      qc.setQueryData(["eval-session", projectId, session.id], data);
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onQueriesSaved();
      onRefresh();
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${session.id}/queries/execute`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["funnel", projectId, session.id] });
      qc.invalidateQueries({ queryKey: ["query-matches"] });
      onSearchRun();
      onRefresh();
    },
  });

  const suggestMutation = useMutation({
    mutationFn: (description: string) =>
      api.post<{ suggestions: SuggestedQuery[] }>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/queries/suggest`,
        { description }
      ),
    onSuccess: (data) => setSuggestions(data.suggestions),
  });

  const brief = eventBrief(session);
  const usable = draft.filter((q) => q.query.trim());
  const busy = saveMutation.isPending || executeMutation.isPending || runAllMutation.isPending || impactPreview.isPending;
  const hasIncludes = usable.some((query) => query.type === "include");
  const jobRunning = jobStarted && ["pending", "running"].includes(backgroundJob?.status ?? "");

  function update(index: number, patch: Partial<SearchQueryItem>) {
    setDraft((prev) => prev.map((q, i) => (i === index ? { ...q, ...patch } : q)));
  }

  function remove(index: number) {
    setDraft((prev) => prev.filter((_, i) => i !== index));
    setExpanded(false);
  }

  function add(item: SearchQueryItem = { query: "", type: "include" }) {
    setDraft((prev) => [...prev, item]);
  }

  async function saveDraft() {
    const cleaned = draft.map((q) => ({ ...q, query: q.query.trim() })).filter((q) => q.query);
    if (signature(cleaned) !== savedSectionsKey || excludeNegated !== savedNegated) {
      await saveMutation.mutateAsync({ queries: cleaned, excludeNegated });
    }
  }

  async function saveAndRun() {
    try {
      await saveDraft();
      executeMutation.mutate();
    } catch { return; }
  }

  async function continueToEvent() {
    try {
      await saveDraft();
      onContinue();
    } catch { return; }
  }

  async function runAll() {
    runAllMutation.reset();
    try {
      await saveDraft();
      const impact = await impactPreview.mutateAsync();
      if (Object.values(impact).some((count) => count > 0)) {
        setReprocessOpen(true);
      } else {
        runAllMutation.mutate(undefined);
      }
    } catch { return; }
  }

  return (
    <div className="space-y-4">
      {/* Queries */}
      <div className="space-y-2">
        {draft.map((q, i) => (
          <div key={i} className="rounded-md border border-border">
            <div className="flex items-center gap-2 p-2">
              <select
                value={q.type}
                onChange={(e) =>
                  update(i, { type: e.target.value as SearchQueryItem["type"] })
                }
                disabled={!isEditable}
                aria-label={`Query ${i + 1} type`}
                className="h-8 rounded-md border bg-background px-2 text-xs"
              >
                <option value="include">Include</option>
                <option value="exclude">Exclude</option>
              </select>

              <Input
                value={q.query}
                onChange={(e) => update(i, { query: e.target.value })}
                disabled={!isEditable}
                placeholder="pulmonary embolism OR (filling AND defect)"
                aria-label={`Query ${i + 1}`}
                className="h-8 flex-1 font-mono text-sm"
              />

              {isEditable && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-destructive"
                  onClick={() => remove(i)}
                  aria-label={`Remove query ${i + 1}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>

          </div>
        ))}

        {draft.length === 0 && (
          <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            No queries yet. Write one below, or let the model draft them from your
            event definition.
          </p>
        )}
      </div>

      {usable.length > 0 && (
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2"
            onClick={() => setExpanded((value) => !value)}
            disabled={dirty}
            title={dirty ? "Run the search to see matched notes" : "Show matched notes"}
          >
            <ChevronDown
              className={`mr-1 h-4 w-4 transition-transform ${expanded ? "" : "-rotate-90"}`}
            />
            Show matched notes
          </Button>
          {expanded && !dirty && (
            <div className="border-t border-border p-3">
              <NotePreviewList
                projectId={projectId}
                sessionId={session.id}
                queryIndex={0}
              />
            </div>
          )}
        </div>
      )}

      {isEditable && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => add()}>
            <Plus className="mr-1.5 h-4 w-4" />
            Add query
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => suggestMutation.mutate(brief)}
            disabled={!brief.trim() || suggestMutation.isPending}
            title={
              brief.trim()
                ? undefined
                : "Define the event in step 2 first"
            }
          >
            {suggestMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-1.5 h-4 w-4" />
            )}
            Suggest from event definition
          </Button>
          <details className="ml-auto text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none hover:text-foreground">
              Query syntax
            </summary>
            <div className="mt-2 space-y-1 rounded-md bg-muted/50 p-3 font-mono">
              <div>troponin OR MI</div>
              <div>(ECG OR EKG) AND elevation</div>
              <div>embol* — matches embolism, embolic</div>
              <div>!suspected - excludes sentences mentioning suspected</div>
            </div>
          </details>
        </div>
      )}

      {suggestMutation.isError && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(suggestMutation.error as Error).message}
        </p>
      )}

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <div className="space-y-2 rounded-md border border-dashed border-border p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">
              Suggested for &ldquo;{session.event_name || "this event"}&rdquo;
            </span>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDraft((prev) => [...prev, ...suggestions]);
                  setSuggestions([]);
                }}
              >
                Add all
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSuggestions([])}>
                Dismiss
              </Button>
            </div>
          </div>
          {suggestions.map((s, i) => (
            <div
              key={i}
              className="flex items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-1.5"
            >
              <code className="truncate text-sm">{s.query}</code>
              <Button
                size="sm"
                variant="ghost"
                className="h-7"
                onClick={() => {
                  add(s);
                  setSuggestions((prev) => prev.filter((x) => x.query !== s.query));
                }}
              >
                Add
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Run */}
      {isEditable && (
        <div className="space-y-3 border-t border-border pt-4">
          <label className="flex items-start gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={excludeNegated}
              onChange={(e) => setExcludeNegated(e.target.checked)}
            />
            <span>
              Remove negated matches
              <span className="block text-xs text-muted-foreground">
                Unchecked keeps sentences like &ldquo;no evidence of&rdquo; matches, shown struck through in previews.
              </span>
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={saveAndRun} disabled={!hasIncludes || busy || jobRunning}>
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {saveMutation.isPending ? "Saving" : "Searching"}
              </>
            ) : (
              <>
                <Search className="mr-2 h-4 w-4" />
                {dirty ? "Save and run search" : "Run search"}
              </>
            )}
          </Button>

          <Button onClick={runAll} disabled={!hasIncludes || busy || jobRunning}>
            <Play className="mr-2 h-4 w-4" />
            Run on all patients
          </Button>
          <Button variant="outline" onClick={continueToEvent} disabled={!hasIncludes || busy || jobRunning}>
            Continue to event definition
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>

          {matchedPatients !== null && !dirty && !searchStale && (
            <span className="text-xs text-muted-foreground">
              Last search matched {matchedPatients} patients in the sample.
            </span>
          )}
          {(dirty || searchStale) && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              {dirty
                ? "Unsaved edits — run the search to see their effect."
                : "Queries changed since the last search. Run it again before testing."}
            </span>
          )}
          </div>
        </div>
      )}

      {jobStarted && (
        <div className="flex flex-wrap items-center gap-3 text-sm" role="status">
          <span>{runAllMutation.data?.status === "completed" || backgroundJob?.status === "completed"
            ? "Search complete"
            : backgroundJob?.status === "failed" ? "Search failed" : "Searching all patients"}</span>
          {backgroundJob?.error_message && <span className="text-destructive">{backgroundJob.error_message}</span>}
          <Button asChild variant="outline" size="sm"><Link to={`/projects/${projectId}/annotations`}>Review annotations</Link></Button>
        </div>
      )}

      {(saveMutation.isError || executeMutation.isError || impactPreview.isError || runAllMutation.isError) && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {((saveMutation.error || executeMutation.error || impactPreview.error || runAllMutation.error) as Error).message}
        </p>
      )}

      <Dialog open={reprocessOpen} onOpenChange={(open) => { if (!runAllMutation.isPending) setReprocessOpen(open); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Replace existing search results?</DialogTitle>
            <DialogDescription>
              This removes {impactPreview.data?.annotations ?? 0} annotations, {impactPreview.data?.predictions ?? 0} predictions,
              and {impactPreview.data?.sentences ?? 0} sentences, including review decisions. It then searches all notes again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" disabled={runAllMutation.isPending} onClick={() => setReprocessOpen(false)}>Keep existing results</Button>
            <Button variant="destructive" disabled={busy || impactPreview.isError || !impactPreview.data} onClick={() => runAllMutation.mutate(impactPreview.data)}>
              {runAllMutation.isPending ? "Searching" : "Replace and run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
