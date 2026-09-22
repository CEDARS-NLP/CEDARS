import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { UnifiedSession, SearchQueryItem, SuggestedQuery } from "@/projects/types";
import NotePreviewList from "./NotePreviewList";
import {
  ChevronDown,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";

interface SearchQueriesSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
  /** Set when the saved queries no longer match the last search that was run. */
  searchStale: boolean;
  onQueriesSaved: () => void;
  onSearchRun: () => void;
  matchedPatients: number | null;
}

function signature(queries: SearchQueryItem[]): string {
  return JSON.stringify(queries.map((q) => [q.type, q.query.trim()]));
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
}: SearchQueriesSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const [draft, setDraft] = useState<SearchQueryItem[]>(session.search_queries);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestedQuery[]>([]);

  const saved = signature(session.search_queries);
  const [syncedKey, setSyncedKey] = useState(saved);

  // Adopt the server's queries when they change, during render rather than in an
  // effect, so a refetch never lands a stale draft in the inputs.
  if (saved !== syncedKey) {
    setSyncedKey(saved);
    setDraft(session.search_queries);
  }

  const dirty = signature(draft) !== saved;

  const saveMutation = useMutation({
    mutationFn: (queries: SearchQueryItem[]) =>
      api.put(`/projects/${projectId}/evaluation/sessions/${session.id}/queries`, {
        search_queries: queries,
      }),
    onSuccess: () => {
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
  const busy = saveMutation.isPending || executeMutation.isPending;

  function update(index: number, patch: Partial<SearchQueryItem>) {
    setDraft((prev) => prev.map((q, i) => (i === index ? { ...q, ...patch } : q)));
  }

  function remove(index: number) {
    setDraft((prev) => prev.filter((_, i) => i !== index));
    setExpanded(null);
  }

  function add(item: SearchQueryItem = { query: "", type: "include" }) {
    setDraft((prev) => [...prev, item]);
  }

  /** Save if needed, then search — the two halves of one intention. */
  async function saveAndRun() {
    const cleaned = draft.map((q) => ({ ...q, query: q.query.trim() })).filter((q) => q.query);
    if (signature(cleaned) !== saved) {
      await saveMutation.mutateAsync(cleaned);
      setDraft(cleaned);
    }
    executeMutation.mutate();
  }

  const hasExcludes = usable.some((q) => q.type === "exclude");

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        Only notes matching one of these queries reach the model, so this is what
        keeps a full run affordable. Cast a wide net — the model does the precise
        work in step 3.
      </p>

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

              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2"
                onClick={() => setExpanded(expanded === i ? null : i)}
                disabled={dirty || !q.query.trim()}
                title={
                  dirty
                    ? "Run the search to see what this matches"
                    : "Show matched notes"
                }
              >
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${
                    expanded === i ? "" : "-rotate-90"
                  }`}
                />
              </Button>

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

            {expanded === i && !dirty && (
              <div className="border-t border-border p-3">
                <NotePreviewList
                  projectId={projectId}
                  sessionId={session.id}
                  queryIndex={i}
                />
              </div>
            )}
          </div>
        ))}

        {draft.length === 0 && (
          <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            No queries yet. Write one below, or let the model draft them from your
            event definition.
          </p>
        )}
      </div>

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
                : "Fill in the event definition in step 1 first"
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
              <div>!suspected — drops negated mentions</div>
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

      {hasExcludes && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Exclude queries are saved with the session but do not yet narrow the
          search. To drop negated mentions, put <code>!suspected</code> inside an
          include query.
        </p>
      )}

      {/* Run */}
      {isEditable && (
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <Button onClick={saveAndRun} disabled={usable.length === 0 || busy}>
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
      )}

      {(saveMutation.isError || executeMutation.isError) && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {((saveMutation.error || executeMutation.error) as Error).message}
        </p>
      )}
    </div>
  );
}
