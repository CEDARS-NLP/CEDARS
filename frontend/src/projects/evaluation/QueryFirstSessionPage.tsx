import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2, Play, Search } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import useProjectPermissions from "@/projects/useProjectPermissions";
import type { SearchQueryItem, UnifiedSession } from "@/projects/types";
import AttemptReview from "./AttemptReview";
import { STATUS_STYLES, statusLabel } from "./sessionStatus";
import {
  isAttemptRunning,
  type EvaluationAttempt,
  type EvaluationState,
  type EventDefinition,
  type PromptRevision,
  type QueryRevision,
} from "./v2Types";

const FIELD_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm disabled:opacity-60";

export default function QueryFirstSessionPage({ projectId, session }: {
  projectId: string;
  session: UnifiedSession;
}) {
  const qc = useQueryClient();
  const permissions = useProjectPermissions(projectId);
  const editable = permissions.canManage && ["draft", "reviewing"].includes(session.status);
  const reviewable = permissions.canReview && ["draft", "reviewing"].includes(session.status);
  const root = `/projects/${projectId}/evaluation/sessions/${session.id}`;
  const stateKey = ["eval-v2-state", projectId, session.id];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [defineEvent, setDefineEvent] = useState(false);
  const [queryDirty, setQueryDirty] = useState(false);
  const { data: state, error, isLoading } = useQuery({
    queryKey: stateKey,
    queryFn: () => api.get<EvaluationState>(`${root}/v2/state`),
    refetchInterval: (query) => query.state.data?.attempts.some(isAttemptRunning) ? 3000 : false,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: stateKey });
    qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
    qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
  }

  function addedAttempt(attempt: EvaluationAttempt) {
    qc.setQueryData<EvaluationState>(stateKey, (previous) => previous && ({
      ...previous,
      attempts: [...previous.attempts.filter((item) => item.id !== attempt.id), attempt],
    }));
    qc.setQueryData(["eval-v2-attempt", projectId, session.id, attempt.id], attempt);
    setSelectedId(attempt.id);
    refresh();
  }

  const run = useMutation({
    mutationFn: ({ action, queryId, promptId }: {
      action: "preview" | "run-all" | "run-llm";
      queryId: string;
      promptId?: string;
    }) => api.post<EvaluationAttempt>(`${root}/v2/${action}`, {
      query_id: queryId,
      ...(promptId ? { prompt_revision_id: promptId } : {}),
    }),
    onSuccess: addedAttempt,
  });

  if (isLoading) return <p className="p-6 text-muted-foreground">Loading session</p>;
  if (error) return <p role="alert" className="p-6 text-destructive">{error.message}</p>;
  if (!state) return null;

  const attempts = [...state.attempts].sort((first, second) => second.sequence - first.sequence);
  const selected = attempts.find((item) => item.id === selectedId) ?? attempts[0];
  const busy = run.isPending || attempts.some(isAttemptRunning);

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h1 className="text-xl font-semibold">{state.prompt_revision?.event_name || "Untitled session"}</h1>
        <Badge className={STATUS_STYLES[session.status] ?? ""}>{statusLabel(session.status)}</Badge>
      </header>
      <section aria-labelledby="query-heading" className="space-y-4 border-b pb-6">
        <h2 id="query-heading" className="text-lg font-semibold">Search queries</h2>
        <QueryEditor
          key={state.query_revision?.id ?? "new"}
          root={root}
          revision={state.query_revision}
          editable={editable}
          onDraftChanged={setQueryDirty}
          onSaved={(revision) => {
            setQueryDirty(false);
            qc.setQueryData<EvaluationState>(stateKey, { ...state, query_revision: revision });
            refresh();
          }}
        >
          {state.query_revision && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={!editable || busy} onClick={() => run.mutate({
                action: "preview", queryId: state.query_revision!.id,
              })}><Search className="mr-2 h-4 w-4" />Preview sample</Button>
              <Button disabled={!editable || busy} onClick={() => run.mutate({
                action: "run-all", queryId: state.query_revision!.id,
              })}><Play className="mr-2 h-4 w-4" />Run on all patients</Button>
              <Button variant="outline" disabled={!editable || busy} onClick={() => setDefineEvent(true)}>
                Define an event
              </Button>
            </div>
          )}
        </QueryEditor>
      </section>

      {state.query_revision && (defineEvent || state.prompt_revision) && (
        <section aria-labelledby="event-heading" className="space-y-4 border-b pb-6">
          <h2 id="event-heading" className="text-lg font-semibold">Define an event</h2>
          <PromptEditor key={state.prompt_revision?.id ?? "new"} root={root}
            revision={state.prompt_revision} editable={editable}
            onSaved={(revision) => {
              qc.setQueryData<EvaluationState>(stateKey, { ...state, prompt_revision: revision });
              refresh();
            }}>
            {state.prompt_revision && (
              <Button disabled={!editable || busy || queryDirty} onClick={() => run.mutate({
                action: "run-llm", queryId: state.query_revision!.id,
                promptId: state.prompt_revision!.id,
              })}><Play className="mr-2 h-4 w-4" />Run LLM sample</Button>
            )}
          </PromptEditor>
        </section>
      )}
      {run.error && <p role="alert" className="text-sm text-destructive">{run.error.message}</p>}

      <section aria-labelledby="attempt-heading" className="space-y-4">
        <h2 id="attempt-heading" className="text-lg font-semibold">Attempt history</h2>
        {attempts.length === 0 ? <p className="text-sm text-muted-foreground">No attempts yet</p> : (
          <>
            <Label htmlFor="attempt-selection">Selected attempt</Label>
            <select id="attempt-selection" className={FIELD_CLASS} value={selected?.id ?? ""}
              onChange={(event) => setSelectedId(event.target.value)}>
              {attempts.map((attempt) => <option key={attempt.id} value={attempt.id}>
                Attempt {attempt.sequence} | Query {attempt.query_revision.revision}
                {attempt.prompt_revision ? ` | Prompt ${attempt.prompt_revision.revision} | ${attempt.prompt_revision.llm_provider ?? ""} ${attempt.prompt_revision.llm_model ?? ""}` : ""}
                {` | ${attempt.mode} | ${attempt.scope} | ${attempt.status}`}
              </option>)}
            </select>
            {selected && <AttemptReview key={selected.id} projectId={projectId} sessionId={session.id}
              initialAttempt={selected} editable={editable} reviewable={reviewable}
              onCommitted={addedAttempt} onRefresh={refresh} />}
          </>
        )}
      </section>
      {selected?.pipeline_run_id && (
        <Button asChild variant="outline"><Link to={`/projects/${projectId}/annotations`}>Review annotations</Link></Button>
      )}
    </div>
  );
}

function QueryEditor({ root, revision, editable, onDraftChanged, onSaved, children }: {
  root: string;
  revision: QueryRevision | null;
  editable: boolean;
  onDraftChanged: (dirty: boolean) => void;
  onSaved: (revision: QueryRevision) => void;
  children: React.ReactNode;
}) {
  const [rows, setRows] = useState<SearchQueryItem[]>(revision?.source_queries ?? [{ query: "", type: "include" }]);
  const [excludeNegated, setExcludeNegated] = useState(revision?.exclude_negated ?? true);
  const normalized = rows.map((row) => ({ ...row, query: row.query.trim() }));
  const valid = normalized.length > 0 && normalized.every((row) => !!row.query)
    && normalized.some((row) => row.type === "include");
  const dirty = !revision || JSON.stringify(normalized) !== JSON.stringify(revision.source_queries)
    || excludeNegated !== revision.exclude_negated;
  function updateDraft(nextRows: SearchQueryItem[], nextNegated = excludeNegated) {
    setRows(nextRows);
    setExcludeNegated(nextNegated);
    onDraftChanged(!revision || JSON.stringify(nextRows.map((row) => ({ ...row, query: row.query.trim() })))
      !== JSON.stringify(revision.source_queries) || nextNegated !== revision.exclude_negated);
  }
  const save = useMutation({
    mutationFn: () => api.put<QueryRevision>(`${root}/v2/queries`, {
      search_queries: normalized, exclude_negated: excludeNegated,
    }),
    onSuccess: onSaved,
  });
  const disabled = !editable || save.isPending;
  return (
    <div className="space-y-4">
      {rows.map((row, index) => (
        <div key={index} className="grid grid-cols-[7rem_minmax(0,1fr)_2.5rem] gap-2">
          <select aria-label={`Query ${index + 1} type`} className={FIELD_CLASS} value={row.type} disabled={disabled}
            onChange={(event) => updateDraft(rows.map((item, itemIndex) => itemIndex === index
              ? { ...item, type: event.target.value as SearchQueryItem["type"] } : item))}>
            <option value="include">Include</option><option value="exclude">Exclude</option>
          </select>
          <Input aria-label={`Query ${index + 1}`} value={row.query} disabled={disabled}
            onChange={(event) => updateDraft(rows.map((item, itemIndex) => itemIndex === index
              ? { ...item, query: event.target.value } : item))} />
          <Button variant="ghost" size="icon" title={`Remove query ${index + 1}`} aria-label={`Remove query ${index + 1}`}
            disabled={disabled || rows.length === 1} onClick={() => updateDraft(rows.filter((_, itemIndex) => itemIndex !== index))}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      {editable && <Button variant="outline" disabled={disabled}
        onClick={() => updateDraft([...rows, { query: "", type: "include" }])}><Plus className="mr-2 h-4 w-4" />Add query</Button>}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={excludeNegated} disabled={disabled}
          onChange={(event) => updateDraft(rows, event.target.checked)} />Exclude negated keywords
      </label>
      {editable && <Button disabled={disabled || !valid || !dirty} onClick={() => save.mutate()}>
        <Save className="mr-2 h-4 w-4" />{save.isPending ? "Saving queries" : "Save queries"}
      </Button>}
      {save.error && <p role="alert" className="text-sm text-destructive">{save.error.message}</p>}
      {revision && <div className="space-y-2">
        <h3 className="text-sm font-medium">Query revision {revision.revision}</h3>
        <pre className="whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 text-sm">{revision.query}</pre>
      </div>}
      {!dirty && !save.isPending && children}
    </div>
  );
}

function PromptEditor({ root, revision, editable, onSaved, children }: {
  root: string;
  revision: PromptRevision | null;
  editable: boolean;
  onSaved: (revision: PromptRevision) => void;
  children: React.ReactNode;
}) {
  const initial: EventDefinition = {
    event_name: revision?.event_name ?? "", event_description: revision?.event_description ?? "",
    include_criteria: revision?.include_criteria ?? "", exclude_criteria: revision?.exclude_criteria ?? "",
  };
  const [form, setForm] = useState(initial);
  const dirty = !revision || JSON.stringify(form) !== JSON.stringify(initial);
  const save = useMutation({
    mutationFn: () => api.put<PromptRevision>(`${root}/v2/prompt`, form),
    onSuccess: onSaved,
  });
  const fields: { key: keyof EventDefinition; label: string }[] = [
    { key: "event_name", label: "Event name" },
    { key: "event_description", label: "What happened to the patient" },
    { key: "include_criteria", label: "Counts as the event" },
    { key: "exclude_criteria", label: "Does not count" },
  ];
  return <div className="space-y-4">
    <div className="grid gap-4 md:grid-cols-2">{fields.map(({ key, label }) => (
      <div key={key} className="space-y-1.5">
        <Label htmlFor={`v2-${key}`}>{label}</Label>
        {key === "event_name" ? <Input id={`v2-${key}`} value={form[key]} disabled={!editable || save.isPending}
          onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
          : <textarea id={`v2-${key}`} className={FIELD_CLASS} rows={3} value={form[key]}
            disabled={!editable || save.isPending} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />}
      </div>
    ))}</div>
    {editable && <Button disabled={!form.event_name.trim() || !dirty || save.isPending} onClick={() => save.mutate()}>
      <Save className="mr-2 h-4 w-4" />{save.isPending ? "Saving event" : "Save event"}
    </Button>}
    {save.error && <p role="alert" className="text-sm text-destructive">{save.error.message}</p>}
    {revision && <p className="text-sm text-muted-foreground">
      Prompt revision {revision.revision} | {revision.llm_provider} {revision.llm_model}
    </p>}
    {!dirty && !save.isPending && children}
  </div>;
}