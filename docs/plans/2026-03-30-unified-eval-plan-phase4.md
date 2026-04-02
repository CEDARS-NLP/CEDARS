# Unified Evaluation Session — Phase 4: Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frontend for the unified evaluation session — a session list page and a single scrollable session page with all sections (funnel bar, search queries, LLM config, results/review, metrics, commit).

**Architecture:** New TypeScript types for the unified session API. New `EvaluationListPage.tsx` and `EvaluationSessionPage.tsx` with sub-components. Uses `@tanstack/react-query` for data fetching and `shadcn/ui` components. WebSocket for pipeline progress.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, shadcn/ui, @tanstack/react-query, react-router-dom v6

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Modify | `frontend/src/projects/types.ts` | Add unified session types (append, don't remove old types yet) |
| Create | `frontend/src/projects/evaluation/EvaluationListPage.tsx` | Session list with status badges, new/clone/discard |
| Create | `frontend/src/projects/evaluation/EvaluationSessionPage.tsx` | Main session page — orchestrates all sections |
| Create | `frontend/src/projects/evaluation/FunnelBar.tsx` | Pinned funnel bar (sample → match → LLM positive) |
| Create | `frontend/src/projects/evaluation/SearchQueriesSection.tsx` | Query editor + suggest + per-query stats + note preview |
| Create | `frontend/src/projects/evaluation/NotePreviewList.tsx` | Paginated matched notes with keyword highlights |
| Create | `frontend/src/projects/evaluation/LlmConfigSection.tsx` | Event definition + model selection + run button |
| Create | `frontend/src/projects/evaluation/ResultsSection.tsx` | Patient cards + filter tabs + judgment buttons |
| Create | `frontend/src/projects/evaluation/MetricsPanel.tsx` | Live accuracy/precision/recall/F1 |
| Create | `frontend/src/projects/evaluation/CommitSection.tsx` | Cost estimate + commit button |

---

### Task 10: Unified Session Types

**Files:**
- Modify: `frontend/src/projects/types.ts` (append)

- [ ] **Step 1: Add new types to types.ts**

Append to `frontend/src/projects/types.ts`:

```typescript
// ── Unified Evaluation Session Types ─────────────────────────────

export type UnifiedSessionStatus = "draft" | "reviewing" | "committed" | "completed" | "discarded";

export interface SearchQueryItem {
  query: string;
  type: "include" | "exclude";
}

export interface UnifiedSession {
  id: string;
  project_id: string;
  status: UnifiedSessionStatus;
  search_queries: SearchQueryItem[];
  event_name: string | null;
  event_description: string | null;
  include_criteria: string | null;
  exclude_criteria: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_base: string | null;
  sample_size: number;
  metrics: UnifiedMetrics | null;
  committed_config: Record<string, unknown> | null;
  committed_at: string | null;
  cloned_from_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface UnifiedSessionListItem {
  id: string;
  project_id: string;
  status: UnifiedSessionStatus;
  search_queries: SearchQueryItem[];
  event_name: string | null;
  sample_size: number;
  metrics: UnifiedMetrics | null;
  committed_at: string | null;
  created_at: string;
}

export interface UnifiedMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  total_reviewed: number;
  total_pending: number;
}

export interface FunnelStats {
  sample_patients: number;
  sample_notes: number;
  matched_patients: number;
  matched_notes: number;
  filter_percent: number;
  llm_positive: number | null;
  llm_negative: number | null;
  llm_inconclusive: number | null;
  estimated_cost: number | null;
}

export interface MatchPosition {
  start: number;
  end: number;
  token: string;
}

export interface NoteSearchMatch {
  id: number;
  patient_id: string;
  note_id: string;
  matched_tokens: string[];
  match_positions: MatchPosition[];
  is_negated: boolean;
}

export interface NoteWithMatches {
  note_id: string;
  patient_id: string;
  note_text: string;
  note_date: string | null;
  note_type: string | null;
  matches: NoteSearchMatch[];
}

export interface QueryMatchesResult {
  query_index: number;
  query: string;
  query_type: string;
  total_notes: number;
  total_patients: number;
  notes: NoteWithMatches[];
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SuggestedQuery {
  query: string;
  type: "include" | "exclude";
}

export interface PatientResultItem {
  id: number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_reasoning: string | null;
  finding_evidence: { note_id: string; text: string; note_date: string }[] | null;
  event_date: string | null;
  predicted_score: number | null;
  review_judgment: string | null;
  reviewer_date_override: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  notes_searched: number;
  notes_matched: number;
}

export interface PatientResultsPage {
  results: PatientResultItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface UnifiedPipelineStats {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  no_match: number;
  is_cancelled: boolean;
}

export interface CommitResult {
  session: UnifiedSession;
  pipeline_run_id: string;
  total_patients: number;
  estimated_cost: number | null;
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/projects/types.ts
git commit -m "feat: add TypeScript types for unified evaluation session API

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: EvaluationListPage

**Files:**
- Create: `frontend/src/projects/evaluation/EvaluationListPage.tsx`

- [ ] **Step 1: Write the session list page**

```tsx
// frontend/src/projects/evaluation/EvaluationListPage.tsx
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { UnifiedSessionListItem } from "@/projects/types";
import { Plus, Copy, Trash2 } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-500/20 text-yellow-400",
  reviewing: "bg-blue-500/20 text-blue-400",
  committed: "bg-purple-500/20 text-purple-400",
  completed: "bg-green-500/20 text-green-400",
  discarded: "bg-zinc-500/20 text-zinc-400",
};

export default function EvaluationListPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ["eval-sessions", projectId],
    queryFn: () =>
      api.get<UnifiedSessionListItem[]>(
        `/projects/${projectId}/evaluation/sessions`
      ),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<UnifiedSessionListItem>(
        `/projects/${projectId}/evaluation/sessions`,
        { search_queries: [] }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
      navigate(`/projects/${projectId}/evaluation/${data.id}`);
    },
  });

  const discardMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.delete(`/projects/${projectId}/evaluation/sessions/${sessionId}`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] }),
  });

  const cloneMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.post<UnifiedSessionListItem>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/clone`
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
      navigate(`/projects/${projectId}/evaluation/${data.id}`);
    },
  });

  const hasActive = sessions.some((s) =>
    ["draft", "reviewing"].includes(s.status)
  );
  const hasCommitted = sessions.some((s) => s.status === "committed");

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Evaluation Sessions</h1>
          <p className="text-sm text-muted-foreground">
            Configure search queries, run LLM classification, review results,
            then commit to run on the full corpus.
          </p>
        </div>
        <Button
          onClick={() => createMutation.mutate()}
          disabled={hasActive || hasCommitted || createMutation.isPending}
        >
          <Plus className="mr-2 h-4 w-4" />
          New Session
        </Button>
      </div>

      {hasCommitted && (
        <div className="rounded-md border border-purple-500/30 bg-purple-500/10 px-4 py-3 text-sm text-purple-300">
          A committed pipeline is running. Cancel it before creating a new
          session.
        </div>
      )}

      {isLoading ? (
        <p className="text-muted-foreground">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No evaluation sessions yet. Click "New Session" to get started.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {sessions.map((s) => (
            <Card
              key={s.id}
              className="cursor-pointer transition-colors hover:bg-muted/50"
              onClick={() =>
                navigate(`/projects/${projectId}/evaluation/${s.id}`)
              }
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="flex items-center gap-3">
                  <CardTitle className="text-base">
                    {s.event_name || "Untitled Session"}
                  </CardTitle>
                  <Badge className={STATUS_COLORS[s.status] ?? ""}>
                    {s.status.toUpperCase()}
                  </Badge>
                </div>
                <div
                  className="flex gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {s.status !== "discarded" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => cloneMutation.mutate(s.id)}
                      disabled={hasActive || hasCommitted}
                      title="Clone to new session"
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  )}
                  {["draft", "reviewing"].includes(s.status) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => discardMutation.mutate(s.id)}
                      title="Discard session"
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex items-center gap-6 text-sm text-muted-foreground">
                <span>
                  {s.search_queries.length} quer
                  {s.search_queries.length === 1 ? "y" : "ies"}
                </span>
                <span>Sample: {s.sample_size} patients</span>
                {s.metrics && (
                  <span>
                    F1: {(s.metrics.f1 * 100).toFixed(1)}% | Reviewed:{" "}
                    {s.metrics.total_reviewed}
                  </span>
                )}
                <span className="ml-auto">
                  {new Date(s.created_at).toLocaleDateString()}
                </span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/projects/evaluation/EvaluationListPage.tsx
git commit -m "feat: add EvaluationListPage with session list, create, clone, discard

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 12: FunnelBar Component

**Files:**
- Create: `frontend/src/projects/evaluation/FunnelBar.tsx`

- [ ] **Step 1: Write the funnel bar component**

```tsx
// frontend/src/projects/evaluation/FunnelBar.tsx
import type { FunnelStats } from "@/projects/types";

interface FunnelBarProps {
  stats: FunnelStats | null;
  isLoading: boolean;
}

export default function FunnelBar({ stats, isLoading }: FunnelBarProps) {
  if (isLoading || !stats) {
    return (
      <div className="sticky top-0 z-10 border-b bg-card p-4">
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          Loading funnel stats...
        </div>
      </div>
    );
  }

  const hasLlm = stats.llm_positive !== null;

  return (
    <div className="sticky top-0 z-10 border-b bg-card p-4">
      <div className="flex items-center gap-2">
        {/* Sample */}
        <div className="flex-1 rounded-lg border bg-muted/50 p-3 text-center">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            Sample
          </div>
          <div className="text-xl font-bold">{stats.sample_patients} pts</div>
          <div className="text-xs text-muted-foreground">
            {stats.sample_notes} notes
          </div>
        </div>

        <div className="text-muted-foreground">→</div>

        {/* Search Match */}
        <div className="flex-1 rounded-lg border bg-muted/50 p-3 text-center">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            Search Match
          </div>
          <div className="text-xl font-bold">
            {stats.matched_patients} pts
          </div>
          <div className="text-xs text-muted-foreground">
            {stats.filter_percent.toFixed(0)}% filtered
          </div>
        </div>

        <div className="text-muted-foreground">→</div>

        {/* LLM Positive */}
        <div
          className={`flex-1 rounded-lg border p-3 text-center ${
            hasLlm ? "bg-muted/50" : "bg-muted/20 opacity-50"
          }`}
        >
          <div className="text-xs font-medium uppercase text-muted-foreground">
            LLM Positive
          </div>
          <div className="text-xl font-bold">
            {hasLlm ? `${stats.llm_positive} pts` : "—"}
          </div>
          <div className="text-xs text-muted-foreground">
            {hasLlm && stats.matched_patients > 0
              ? `${((stats.llm_positive! / stats.matched_patients) * 100).toFixed(0)}% of match`
              : "Run LLM first"}
          </div>
        </div>
      </div>

      {stats.estimated_cost !== null && (
        <div className="mt-2 text-center text-xs text-muted-foreground">
          {stats.filter_percent.toFixed(0)}% of notes filtered by search —
          est. LLM cost: ~${stats.estimated_cost.toFixed(2)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/projects/evaluation/FunnelBar.tsx
git commit -m "feat: add FunnelBar component for sample → match → LLM positive

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 13: SearchQueriesSection + NotePreviewList

**Files:**
- Create: `frontend/src/projects/evaluation/SearchQueriesSection.tsx`
- Create: `frontend/src/projects/evaluation/NotePreviewList.tsx`

- [ ] **Step 1: Write the NotePreviewList component**

```tsx
// frontend/src/projects/evaluation/NotePreviewList.tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { QueryMatchesResult, NoteWithMatches } from "@/projects/types";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

interface NotePreviewListProps {
  projectId: string;
  sessionId: string;
  queryIndex: number;
}

function HighlightedText({ text, matches }: { text: string; matches: NoteWithMatches["matches"] }) {
  if (!matches.length) return <span>{text}</span>;

  // Collect all positions, sort by start
  const positions = matches
    .flatMap((m) =>
      m.match_positions.map((p) => ({ ...p, is_negated: m.is_negated }))
    )
    .sort((a, b) => a.start - b.start);

  if (!positions.length) return <span>{text}</span>;

  const parts: React.ReactNode[] = [];
  let lastEnd = 0;

  for (const pos of positions) {
    if (pos.start > lastEnd) {
      parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd, pos.start)}</span>);
    }
    const cls = pos.is_negated
      ? "bg-red-500/20 text-red-300 line-through"
      : "bg-blue-500/20 text-blue-300 font-medium";
    parts.push(
      <span key={`h-${pos.start}`} className={cls}>
        {text.slice(pos.start, pos.end)}
      </span>
    );
    lastEnd = pos.end;
  }
  if (lastEnd < text.length) {
    parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <>{parts}</>;
}

export default function NotePreviewList({ projectId, sessionId, queryIndex }: NotePreviewListProps) {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["query-matches", projectId, sessionId, queryIndex, page],
    queryFn: () =>
      api.get<QueryMatchesResult>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/queries/${queryIndex}/matches?page=${page}&page_size=10`
      ),
  });

  if (isLoading) return <p className="py-4 text-sm text-muted-foreground">Loading matches...</p>;
  if (!data || data.notes.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">No matched notes for this query.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {data.total_notes} notes from {data.total_patients} patients
      </div>

      {data.notes.map((note) => (
        <div key={note.note_id} className="rounded-lg border bg-muted/30 p-3">
          <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
            <span>Patient: {note.patient_id.slice(0, 8)}...</span>
            {note.note_date && <span>Date: {note.note_date}</span>}
            {note.note_type && <span>Type: {note.note_type}</span>}
          </div>
          <div className="text-sm leading-relaxed">
            <HighlightedText text={note.note_text} matches={note.matches} />
          </div>
        </div>
      ))}

      {data.total_pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {data.total_pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= data.total_pages}
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write the SearchQueriesSection component**

```tsx
// frontend/src/projects/evaluation/SearchQueriesSection.tsx
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
```

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/projects/evaluation/SearchQueriesSection.tsx src/projects/evaluation/NotePreviewList.tsx
git commit -m "feat: add SearchQueriesSection with query editor, suggest, and note preview

Query list with per-query expand for note preview. LLM-powered
query suggestion. NotePreviewList with blue/red keyword highlights.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 14: LlmConfigSection

**Files:**
- Create: `frontend/src/projects/evaluation/LlmConfigSection.tsx`

- [ ] **Step 1: Write the LLM config section**

```tsx
// frontend/src/projects/evaluation/LlmConfigSection.tsx
import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UnifiedSession } from "@/projects/types";
import { Play, Loader2 } from "lucide-react";

interface LlmConfigSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "bedrock", label: "AWS Bedrock" },
];

export default function LlmConfigSection({ projectId, session, onRefresh }: LlmConfigSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const [eventName, setEventName] = useState(session.event_name || "");
  const [eventDesc, setEventDesc] = useState(session.event_description || "");
  const [includeCriteria, setIncludeCriteria] = useState(session.include_criteria || "");
  const [excludeCriteria, setExcludeCriteria] = useState(session.exclude_criteria || "");
  const [provider, setProvider] = useState(session.llm_provider || "openai");
  const [model, setModel] = useState(session.llm_model || "gpt-4o-mini");
  const [apiBase, setApiBase] = useState(session.llm_api_base || "");

  useEffect(() => {
    setEventName(session.event_name || "");
    setEventDesc(session.event_description || "");
    setIncludeCriteria(session.include_criteria || "");
    setExcludeCriteria(session.exclude_criteria || "");
    setProvider(session.llm_provider || "openai");
    setModel(session.llm_model || "gpt-4o-mini");
    setApiBase(session.llm_api_base || "");
  }, [session]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/projects/${projectId}/evaluation/sessions/${session.id}/llm-config`, {
        event_name: eventName,
        event_description: eventDesc,
        include_criteria: includeCriteria,
        exclude_criteria: excludeCriteria,
        llm_provider: provider,
        llm_model: model,
        llm_api_base: apiBase || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${session.id}/run-llm`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      qc.invalidateQueries({ queryKey: ["funnel", projectId, session.id] });
      qc.invalidateQueries({ queryKey: ["eval-results", projectId, session.id] });
      onRefresh();
    },
  });

  const canRun = eventName.trim() && provider && model;

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">LLM Classification</h2>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Event Name</Label>
          <Input value={eventName} onChange={(e) => setEventName(e.target.value)} disabled={!isEditable} placeholder="e.g., Myocardial Infarction" />
        </div>
        <div className="space-y-2">
          <Label>Event Description</Label>
          <textarea value={eventDesc} onChange={(e) => setEventDesc(e.target.value)} disabled={!isEditable} placeholder="Describe the clinical event..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Include Criteria</Label>
          <textarea value={includeCriteria} onChange={(e) => setIncludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to look for..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Exclude Criteria</Label>
          <textarea value={excludeCriteria} onChange={(e) => setExcludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to exclude..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2">
          <Label>LLM Provider</Label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={!isEditable} className="flex w-full rounded-md border bg-background px-3 py-2 text-sm">
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label>Model</Label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} disabled={!isEditable} placeholder="gpt-4o-mini" />
        </div>
        <div className="space-y-2">
          <Label>API Base (optional)</Label>
          <Input value={apiBase} onChange={(e) => setApiBase(e.target.value)} disabled={!isEditable} placeholder="http://localhost:11434" />
        </div>
      </div>

      {isEditable && (
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            Save Config
          </Button>
          <Button
            onClick={() => {
              saveMutation.mutateAsync().then(() => runMutation.mutate());
            }}
            disabled={!canRun || runMutation.isPending}
          >
            {runMutation.isPending ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Running LLM...</>
            ) : (
              <><Play className="mr-2 h-4 w-4" /> Run LLM on Sample</>
            )}
          </Button>
        </div>
      )}

      {runMutation.isError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(runMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/projects/evaluation/LlmConfigSection.tsx
git commit -m "feat: add LlmConfigSection with event definition and model selection

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 15: ResultsSection + MetricsPanel + CommitSection

**Files:**
- Create: `frontend/src/projects/evaluation/ResultsSection.tsx`
- Create: `frontend/src/projects/evaluation/MetricsPanel.tsx`
- Create: `frontend/src/projects/evaluation/CommitSection.tsx`

- [ ] **Step 1: Write the ResultsSection**

```tsx
// frontend/src/projects/evaluation/ResultsSection.tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type { PatientResultsPage, PatientResultItem } from "@/projects/types";
import { Check, X, SkipForward, ChevronDown, ChevronRight } from "lucide-react";

interface ResultsSectionProps {
  projectId: string;
  sessionId: string;
  sessionStatus: string;
  onRefresh: () => void;
}

const LABEL_COLORS: Record<string, string> = {
  positive: "bg-green-500/20 text-green-400",
  negative: "bg-red-500/20 text-red-400",
  inconclusive: "bg-yellow-500/20 text-yellow-400",
  no_match: "bg-zinc-500/20 text-zinc-400",
};

const TABS = ["all", "positive", "negative", "inconclusive", "unreviewed"] as const;

function PatientCard({
  result,
  projectId,
  sessionId,
  canJudge,
  onJudged,
}: {
  result: PatientResultItem;
  projectId: string;
  sessionId: string;
  canJudge: boolean;
  onJudged: () => void;
}) {
  const [expanded, setExpanded] = useState(result.finding_label === "positive");
  const [dateOverride, setDateOverride] = useState(result.event_date || "");

  const judgeMutation = useMutation({
    mutationFn: (judgment: string) =>
      api.post(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/${result.id}/judge`,
        { judgment, event_date_override: dateOverride || null }
      ),
    onSuccess: onJudged,
  });

  const isReviewed = !!result.review_judgment;

  return (
    <div
      className={`rounded-lg border ${
        isReviewed ? "border-green-500/30" : ""
      } bg-card`}
    >
      <div
        className="flex cursor-pointer items-center justify-between p-3"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <span className="font-medium">Patient {result.patient_id.slice(0, 8)}...</span>
          {result.finding_label && (
            <Badge className={LABEL_COLORS[result.finding_label] ?? ""}>
              {result.finding_label.toUpperCase()}
            </Badge>
          )}
          {result.predicted_score !== null && (
            <span className="text-xs text-yellow-400">
              Score: {result.predicted_score.toFixed(2)}
            </span>
          )}
          {isReviewed && (
            <span className="text-xs text-green-400">
              Reviewed: {result.review_judgment}
              {result.reviewer_date_override && ` | Date: ${result.reviewer_date_override}`}
            </span>
          )}
        </div>

        {!expanded && canJudge && !isReviewed && (
          <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            <Button size="sm" variant="ghost" className="text-green-400" onClick={() => judgeMutation.mutate("correct")}>
              <Check className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="ghost" className="text-red-400" onClick={() => judgeMutation.mutate("wrong")}>
              <X className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => judgeMutation.mutate("skipped")}>
              <SkipForward className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>

      {expanded && (
        <div className="border-t p-3 space-y-3">
          {result.finding_reasoning && (
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs font-medium uppercase text-muted-foreground mb-1">LLM Reasoning</div>
              <div className="text-sm leading-relaxed">{result.finding_reasoning}</div>
            </div>
          )}

          {result.finding_evidence && result.finding_evidence.length > 0 && (
            <div>
              <div className="text-xs font-medium uppercase text-muted-foreground mb-1">
                Evidence ({result.finding_evidence.length} notes)
              </div>
              <div className="space-y-1">
                {result.finding_evidence.map((e, i) => (
                  <div key={i} className="rounded-md border-l-2 border-blue-500 bg-muted/30 p-2 text-sm">
                    <span className="text-xs text-muted-foreground">{e.note_date}</span>
                    <br />
                    "{e.text}"
                  </div>
                ))}
              </div>
            </div>
          )}

          {canJudge && !isReviewed && (
            <div className="flex items-center justify-between border-t pt-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Event date:</span>
                <Input
                  type="date"
                  value={dateOverride}
                  onChange={(e) => setDateOverride(e.target.value)}
                  className="w-40"
                />
              </div>
              <div className="flex gap-2">
                <Button size="sm" className="bg-green-700 text-green-100" onClick={() => judgeMutation.mutate("correct")}>
                  <Check className="mr-1 h-4 w-4" /> Correct
                </Button>
                <Button size="sm" className="bg-red-700 text-red-100" onClick={() => judgeMutation.mutate("wrong")}>
                  <X className="mr-1 h-4 w-4" /> Wrong
                </Button>
                <Button size="sm" variant="outline" onClick={() => judgeMutation.mutate("skipped")}>
                  Skip
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResultsSection({ projectId, sessionId, sessionStatus, onRefresh }: ResultsSectionProps) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("all");
  const [page, setPage] = useState(1);

  const labelFilter = activeTab === "unreviewed" ? undefined : activeTab === "all" ? undefined : activeTab;
  const reviewedFilter = activeTab === "unreviewed" ? "unreviewed" : undefined;

  const { data, isLoading } = useQuery({
    queryKey: ["eval-results", projectId, sessionId, activeTab, page],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), page_size: "20" });
      if (labelFilter) params.set("label", labelFilter);
      if (reviewedFilter) params.set("reviewed", reviewedFilter);
      return api.get<PatientResultsPage>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results?${params}`
      );
    },
  });

  const canJudge = ["reviewing"].includes(sessionStatus);

  function handleJudged() {
    qc.invalidateQueries({ queryKey: ["eval-results", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["eval-metrics", projectId, sessionId] });
    onRefresh();
  }

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Patient Results</h2>
        <div className="flex gap-1 rounded-md bg-muted p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); setPage(1); }}
              className={`rounded-sm px-3 py-1 text-xs capitalize ${
                activeTab === tab ? "bg-primary text-primary-foreground" : "text-muted-foreground"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading results...</p>
      ) : !data || data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {session.status === "draft"
            ? "Run search queries and LLM classification to see results."
            : "No results match the current filter."}
        </p>
      ) : (
        <>
          <div className="space-y-2">
            {data.results.map((r) => (
              <PatientCard
                key={r.id}
                result={r}
                projectId={projectId}
                sessionId={sessionId}
                canJudge={canJudge}
                onJudged={handleJudged}
              />
            ))}
          </div>
          {data.total_pages > 1 && (
            <div className="flex items-center justify-center gap-2 text-sm">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <span className="text-muted-foreground">
                Page {page} of {data.total_pages}
              </span>
              <Button variant="outline" size="sm" disabled={page >= data.total_pages} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write the MetricsPanel**

```tsx
// frontend/src/projects/evaluation/MetricsPanel.tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { UnifiedMetrics } from "@/projects/types";

interface MetricsPanelProps {
  projectId: string;
  sessionId: string;
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex-1 rounded-lg bg-muted/50 p-3 text-center">
      <div className="text-xs font-medium uppercase text-muted-foreground">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

export default function MetricsPanel({ projectId, sessionId }: MetricsPanelProps) {
  const { data: metrics } = useQuery({
    queryKey: ["eval-metrics", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedMetrics>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/metrics`
      ),
    refetchInterval: 5000,
  });

  if (!metrics || metrics.total_reviewed === 0) {
    return (
      <div className="rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Metrics</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Review patient results to see live metrics.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <h2 className="text-lg font-semibold">Live Metrics</h2>
      <div className="flex gap-3">
        <MetricCard label="Accuracy" value={`${(metrics.accuracy * 100).toFixed(1)}%`} color="text-green-400" />
        <MetricCard label="Precision" value={`${(metrics.precision * 100).toFixed(1)}%`} color="text-blue-400" />
        <MetricCard label="Recall" value={`${(metrics.recall * 100).toFixed(1)}%`} color="text-blue-400" />
        <MetricCard label="F1 Score" value={`${(metrics.f1 * 100).toFixed(1)}%`} color="text-yellow-400" />
      </div>
      <div className="text-center text-xs text-muted-foreground">
        Based on {metrics.total_reviewed} reviewed patients ({metrics.total_pending} remaining)
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write the CommitSection**

```tsx
// frontend/src/projects/evaluation/CommitSection.tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { UnifiedSession, CommitResult } from "@/projects/types";
import { Lock, Loader2 } from "lucide-react";

interface CommitSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

export default function CommitSection({ projectId, session, onRefresh }: CommitSectionProps) {
  const qc = useQueryClient();

  const commitMutation = useMutation({
    mutationFn: () =>
      api.post<CommitResult>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/commit`
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  if (session.status !== "reviewing") return null;

  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Ready to commit?</h2>
          <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
            This will lock the search queries and LLM prompt, then run the
            pipeline on <strong>all patients</strong> in the project.
          </p>
        </div>
        <Button
          size="lg"
          onClick={() => commitMutation.mutate()}
          disabled={commitMutation.isPending}
          className="bg-green-600 text-white hover:bg-green-700"
        >
          {commitMutation.isPending ? (
            <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Committing...</>
          ) : (
            <><Lock className="mr-2 h-4 w-4" /> Commit & Run Full Pipeline</>
          )}
        </Button>
      </div>

      {commitMutation.isError && (
        <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(commitMutation.error as Error).message}
        </div>
      )}

      {commitMutation.isSuccess && commitMutation.data && (
        <div className="mt-3 rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
          Pipeline started! Processing {commitMutation.data.total_patients} patients.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/projects/evaluation/ResultsSection.tsx src/projects/evaluation/MetricsPanel.tsx src/projects/evaluation/CommitSection.tsx
git commit -m "feat: add ResultsSection, MetricsPanel, and CommitSection

Patient cards with judgment buttons, live metrics display,
and commit button for full pipeline execution.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 16: EvaluationSessionPage (Orchestrator)

**Files:**
- Create: `frontend/src/projects/evaluation/EvaluationSessionPage.tsx`

- [ ] **Step 1: Write the main session page**

```tsx
// frontend/src/projects/evaluation/EvaluationSessionPage.tsx
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import type { UnifiedSession, FunnelStats } from "@/projects/types";
import FunnelBar from "./FunnelBar";
import SearchQueriesSection from "./SearchQueriesSection";
import LlmConfigSection from "./LlmConfigSection";
import ResultsSection from "./ResultsSection";
import MetricsPanel from "./MetricsPanel";
import CommitSection from "./CommitSection";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-500/20 text-yellow-400",
  reviewing: "bg-blue-500/20 text-blue-400",
  committed: "bg-purple-500/20 text-purple-400",
  completed: "bg-green-500/20 text-green-400",
  discarded: "bg-zinc-500/20 text-zinc-400",
};

export default function EvaluationSessionPage() {
  const { projectId, sessionId } = useParams<{ projectId: string; sessionId: string }>();
  const qc = useQueryClient();

  const { data: session, isLoading: sessionLoading } = useQuery({
    queryKey: ["eval-session", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedSession>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}`
      ),
  });

  const { data: funnel, isLoading: funnelLoading } = useQuery({
    queryKey: ["funnel", projectId, sessionId],
    queryFn: () =>
      api.get<FunnelStats>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/funnel`
      ),
    enabled: !!session,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["eval-session", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["funnel", projectId, sessionId] });
  }

  if (sessionLoading || !session) {
    return <p className="p-6 text-muted-foreground">Loading session...</p>;
  }

  const isReadOnly = ["committed", "completed", "discarded"].includes(session.status);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">
            {session.event_name || "Untitled Session"}
          </h1>
          <Badge className={STATUS_COLORS[session.status] ?? ""}>
            {session.status.toUpperCase()}
          </Badge>
        </div>
        {isReadOnly && (
          <span className="text-sm text-muted-foreground">Read-only</span>
        )}
      </div>

      {/* Pinned Funnel Bar */}
      <FunnelBar stats={funnel ?? null} isLoading={funnelLoading} />

      {/* Sections */}
      <div className="space-y-6 p-6">
        <SearchQueriesSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />

        <LlmConfigSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />

        {session.status !== "draft" && (
          <>
            <ResultsSection
              projectId={projectId!}
              sessionId={session.id}
              sessionStatus={session.status}
              onRefresh={refresh}
            />

            <MetricsPanel
              projectId={projectId!}
              sessionId={session.id}
            />
          </>
        )}

        <CommitSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/projects/evaluation/EvaluationSessionPage.tsx
git commit -m "feat: add EvaluationSessionPage orchestrating all sections

Single scrollable page: FunnelBar, SearchQueries, LlmConfig,
Results, Metrics, Commit. Shows all sections based on session state.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
