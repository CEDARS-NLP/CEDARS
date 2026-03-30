import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { UnifiedSession, SearchQueryItem, SuggestedQuery } from "@/projects/types";
import NotePreviewList from "./NotePreviewList";
import { Plus, Trash2, Sparkles, Search, ChevronDown, ChevronRight } from "lucide-react";

interface SearchQueriesSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

export default function SearchQueriesSection({ projectId, session, onRefresh }: SearchQueriesSectionProps) {
  const qc = useQueryClient();
  const [newQuery, setNewQuery] = useState("");
  const [newType, setNewType] = useState<"include" | "exclude">("include");
  const [expandedQuery, setExpandedQuery] = useState<number | null>(null);
  const [suggestDesc, setSuggestDesc] = useState("");
  const [showSuggest, setShowSuggest] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestedQuery[]>([]);

  const isEditable = ["draft", "reviewing"].includes(session.status);

  const updateMutation = useMutation({
    mutationFn: (queries: SearchQueryItem[]) =>
      api.put(`/projects/${projectId}/evaluation/sessions/${session.id}/queries`, {
        search_queries: queries,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${session.id}/queries/execute`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["funnel", projectId, session.id] });
      qc.invalidateQueries({ queryKey: ["query-matches"] });
      onRefresh();
    },
  });

  const suggestMutation = useMutation({
    mutationFn: (description: string) =>
      api.post<{ suggestions: SuggestedQuery[] }>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/queries/suggest`,
        {
          description,
          llm_provider: session.llm_provider || "openai",
          llm_model: session.llm_model || "gpt-4o-mini",
        }
      ),
    onSuccess: (data) => setSuggestions(data.suggestions),
  });

  function addQuery() {
    if (!newQuery.trim()) return;
    const updated = [...session.search_queries, { query: newQuery.trim(), type: newType }];
    updateMutation.mutate(updated);
    setNewQuery("");
  }

  function removeQuery(index: number) {
    const updated = session.search_queries.filter((_, i) => i !== index);
    updateMutation.mutate(updated);
  }

  function acceptSuggestion(suggestion: SuggestedQuery) {
    const updated = [...session.search_queries, suggestion];
    updateMutation.mutate(updated);
    setSuggestions((prev) => prev.filter((s) => s.query !== suggestion.query));
  }

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Search Queries</h2>
        <div className="flex gap-2">
          {isEditable && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowSuggest(!showSuggest)}
            >
              <Sparkles className="mr-1 h-4 w-4" />
              Suggest Queries
            </Button>
          )}
          <Button
            size="sm"
            onClick={() => executeMutation.mutate()}
            disabled={session.search_queries.length === 0 || executeMutation.isPending}
          >
            <Search className="mr-1 h-4 w-4" />
            {executeMutation.isPending ? "Running..." : "Run Search"}
          </Button>
        </div>
      </div>

      {/* Syntax help */}
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        <strong>Syntax:</strong>{" "}
        <code>troponin OR MI</code> |{" "}
        <code>(ECG OR EKG) AND elevation</code> |{" "}
        <code>embol*</code> (wildcard) |{" "}
        <code>!suspected</code> (exclude)
      </div>

      {/* Suggest panel */}
      {showSuggest && isEditable && (
        <div className="space-y-2 rounded-md border border-dashed p-3">
          <div className="text-sm font-medium">Describe the event in plain English:</div>
          <div className="flex gap-2">
            <Input
              value={suggestDesc}
              onChange={(e) => setSuggestDesc(e.target.value)}
              placeholder="e.g., Myocardial infarction with troponin elevation and ECG changes"
            />
            <Button
              size="sm"
              onClick={() => suggestMutation.mutate(suggestDesc)}
              disabled={!suggestDesc.trim() || suggestMutation.isPending}
            >
              {suggestMutation.isPending ? "Generating..." : "Generate"}
            </Button>
          </div>
          {suggestions.length > 0 && (
            <div className="space-y-1">
              {suggestions.map((s, i) => (
                <div key={i} className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant={s.type === "include" ? "default" : "destructive"} className="text-xs">
                      {s.type}
                    </Badge>
                    <code>{s.query}</code>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => acceptSuggestion(s)}>
                      Accept
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Query list */}
      <div className="space-y-2">
        {session.search_queries.map((q, i) => (
          <div key={i}>
            <div
              className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2 text-sm cursor-pointer"
              onClick={() => setExpandedQuery(expandedQuery === i ? null : i)}
            >
              <div className="flex items-center gap-2">
                {expandedQuery === i ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
                <Badge variant={q.type === "include" ? "default" : "destructive"} className="text-xs">
                  {q.type}
                </Badge>
                <code>{q.query}</code>
              </div>
              {isEditable && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={(e) => { e.stopPropagation(); removeQuery(i); }}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              )}
            </div>
            {expandedQuery === i && (
              <div className="ml-6 mt-2">
                <NotePreviewList
                  projectId={projectId}
                  sessionId={session.id}
                  queryIndex={i}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Add query */}
      {isEditable && (
        <div className="flex gap-2">
          <select
            value={newType}
            onChange={(e) => setNewType(e.target.value as "include" | "exclude")}
            className="rounded-md border bg-background px-2 text-sm"
          >
            <option value="include">Include</option>
            <option value="exclude">Exclude</option>
          </select>
          <Input
            value={newQuery}
            onChange={(e) => setNewQuery(e.target.value)}
            placeholder="troponin OR MI"
            onKeyDown={(e) => e.key === "Enter" && addQuery()}
          />
          <Button size="sm" onClick={addQuery} disabled={!newQuery.trim()}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
