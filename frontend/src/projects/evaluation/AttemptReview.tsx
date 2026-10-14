import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X, SkipForward, Play, Square, RotateCcw, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isAttemptRunning, isSuccessfulResult, type AttemptMatches, type AttemptResult, type EvaluationAttempt, type MatchedNote } from "./v2Types";

export default function AttemptReview({ projectId, sessionId, initialAttempt, editable, reviewable, onCommitted, onRefresh }: {
  projectId: string;
  sessionId: string;
  initialAttempt: EvaluationAttempt;
  editable: boolean;
  reviewable: boolean;
  onCommitted: (attempt: EvaluationAttempt) => void;
  onRefresh: () => void;
}) {
  const qc = useQueryClient();
  const root = `/projects/${projectId}/evaluation/sessions/${sessionId}/v2`;
  const attemptId = initialAttempt.id;
  const attemptKey = ["eval-v2-attempt", projectId, sessionId, attemptId];
  const resultsKey = ["eval-v2-results", projectId, sessionId, attemptId];
  const [notePage, setNotePage] = useState({ attemptId, page: 1 });
  const page = notePage.attemptId === attemptId ? notePage.page : 1;
  const matchesKey = ["eval-v2-matches", projectId, sessionId, attemptId];
  const { data: attempt = initialAttempt, error: attemptError } = useQuery({
    queryKey: attemptKey,
    queryFn: () => api.get<EvaluationAttempt>(`${root}/attempts/${attemptId}`),
    initialData: initialAttempt,
    refetchInterval: (query) => query.state.data && isAttemptRunning(query.state.data) ? 3000 : false,
  });
  const running = isAttemptRunning(attempt);
  const { data: matchedNotes, error: matchesError, isLoading: matchesLoading } = useQuery({
    queryKey: [...matchesKey, page],
    queryFn: () => api.get<AttemptMatches>(`${root}/attempts/${attemptId}/matches?page=${page}&page_size=10`),
    refetchInterval: running ? 3000 : false,
  });
  const { data: results = [], error: resultsError, isLoading } = useQuery({
    queryKey: resultsKey,
    queryFn: () => api.get<AttemptResult[]>(`${root}/attempts/${attemptId}/results`),
    refetchInterval: running ? 3000 : false,
  });
  useEffect(() => {
    if (!running) {
      qc.invalidateQueries({ queryKey: ["eval-v2-results", projectId, sessionId, attemptId] });
      qc.invalidateQueries({ queryKey: ["eval-v2-matches", projectId, sessionId, attemptId] });
    }
  }, [running, qc, projectId, sessionId, attemptId]);
  const [selectedResultId, setSelectedResultId] = useState<string | number | null>(null);
  const current = results.find((result) => result.id === selectedResultId) ?? results[0];
  const successful = results.filter(isSuccessfulResult);
  const commit = useMutation({
    mutationFn: () => api.post<EvaluationAttempt>(`${root}/commit`, { attempt_id: attemptId }),
    onSuccess: onCommitted,
  });
  const judge = useMutation({
    mutationFn: (body: { resultId: string | number; judgment: string; event_date_override: string | null }) =>
      api.post<AttemptResult>(`${root}/attempts/${attemptId}/results/${body.resultId}/judge`, {
        judgment: body.judgment, event_date_override: body.event_date_override,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: resultsKey });
      qc.invalidateQueries({ queryKey: attemptKey });
      onRefresh();
    },
  });
  const control = useMutation({
    mutationFn: (action: "cancel" | "resume" | "retry") =>
      api.post<EvaluationAttempt>(`${root}/attempts/${attemptId}/${action}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: attemptKey });
      qc.invalidateQueries({ queryKey: resultsKey });
      qc.invalidateQueries({ queryKey: matchesKey });
      qc.invalidateQueries({ queryKey: ["eval-v2-state", projectId, sessionId] });
      onRefresh();
    },
  });
  const canCommit = editable && attempt.mode === "llm" && attempt.scope === "sample"
    && ["completed", "succeeded", "success"].includes(attempt.status)
    && successful.length > 0 && !resultsError && !attemptError && !running;
  const evidence = results.flatMap((result) => (result.finding_evidence ?? [])
    .map((item) => ({ ...item, patient_id: result.patient_id })));
  const notes = [...new Map(evidence.map((item) => [`${item.patient_id}:${item.note_id}:${item.text}`, item])).values()];
  const metrics = attempt.metrics ?? {};
  const visibleNotes = matchedNotes?.notes ?? [];
  const totalPages = Math.max(1, matchedNotes?.total_pages ?? 1);

  return <div className="space-y-5">
    <div className="space-y-2 border-b pb-4" aria-label="Selected attempt revisions">
      <h3 className="font-medium">Attempt {attempt.sequence}: {attempt.status}</h3>
      <p className="text-sm">Query revision {attempt.query_revision.revision} | {attempt.mode} | {attempt.scope}</p>
      <pre className="whitespace-pre-wrap break-words text-sm">{attempt.query_revision.query}</pre>
      <p className="text-sm text-muted-foreground">Exclude negated keywords: {attempt.query_revision.exclude_negated ? "Yes" : "No"}</p>
      {attempt.prompt_revision && <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="font-medium">Prompt revision {attempt.prompt_revision.revision}</dt>
          <dd>{attempt.prompt_revision.llm_provider} {attempt.prompt_revision.llm_model}</dd></div>
        <div><dt className="font-medium">Event name</dt><dd>{attempt.prompt_revision.event_name}</dd></div>
        <div><dt className="font-medium">What happened to the patient</dt><dd>{attempt.prompt_revision.event_description}</dd></div>
        <div><dt className="font-medium">Counts as the event</dt><dd>{attempt.prompt_revision.include_criteria}</dd></div>
        <div><dt className="font-medium">Does not count</dt><dd>{attempt.prompt_revision.exclude_criteria}</dd></div>
      </dl>}
      <p className="text-xs text-muted-foreground">{new Date(attempt.created_at).toLocaleString("en-US", {
        month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
      }).replace("AM", "am").replace("PM", "pm")}</p>
    </div>
    {(attemptError || resultsError) && <p role="alert" className="text-destructive">Unable to load attempt details. Try refreshing the page.</p>}
    {(attempt.status === "failed" || attempt.error_message) && <p role="alert" className="text-destructive">
      {attempt.status === "failed" ? "Attempt failed. Contact your project administrator or retry the attempt." : "The attempt reported an error. Contact your project administrator."}
    </p>}
    {editable && <div className="flex flex-wrap gap-2" aria-label="Attempt controls">
      {running && <Button variant="outline" disabled={control.isPending || !!attemptError}
        onClick={() => control.mutate("cancel")}><Square className="mr-2 h-4 w-4" />Cancel attempt</Button>}
      {attempt.status === "cancelled" && <Button variant="outline" disabled={control.isPending || !!attemptError}
        onClick={() => control.mutate("resume")}><Play className="mr-2 h-4 w-4" />Resume attempt</Button>}
      {attempt.status === "failed" && <Button variant="outline" disabled={control.isPending || !!attemptError}
        onClick={() => control.mutate("retry")}><RotateCcw className="mr-2 h-4 w-4" />Retry attempt</Button>}
    </div>}
    {control.error && <p role="alert" className="text-destructive">Unable to update the attempt. Try again.</p>}
    {attempt.progress && <section aria-label="Attempt progress" className="space-y-2">
      <h3 className="font-medium">Progress</h3>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Object.entries(attempt.progress).filter(([, value]) => typeof value === "number")
          .map(([key, value]) => <div key={key}><dt className="text-xs text-muted-foreground">{key.replaceAll("_", " ")}</dt>
            <dd className="font-semibold">{String(value)}</dd></div>)}
      </dl>
    </section>}
    <section aria-label="Attempt metrics" className="space-y-2">
      <h3 className="font-medium">Metrics</h3>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Object.entries(metrics).filter(([, value]) => typeof value === "number" || typeof value === "string")
          .map(([key, value]) => <div key={key} className="rounded-md border bg-muted/30 p-3">
            <dt className="text-xs text-muted-foreground">{key.replaceAll("_", " ")}</dt>
            <dd className="font-semibold">{["accuracy", "precision", "recall", "f1"].includes(key)
              && typeof value === "number" ? `${(value * 100).toFixed(0)}%` : String(value)}</dd>
          </div>)}
      </dl>
    </section>
    <section aria-label="Saved results" className="space-y-3">
      <h3 className="font-medium">Saved results</h3>
      {isLoading ? <p className="text-sm">Loading results</p> : results.length === 0 && !resultsError
        ? <p className="text-sm text-muted-foreground">{running ? "Processing patients" : "No saved results"}</p> : null}
      {results.length > 0 && <>
        <Label htmlFor="result-selection">Patient</Label>
        <select id="result-selection" className="w-full rounded-md border bg-background p-2 text-sm"
          value={current?.id ?? ""} onChange={(event) => setSelectedResultId(results.find((result) => String(result.id) === event.target.value)!.id)}>
          {results.map((result) => <option key={result.id} value={result.id}>
            {result.patient_id} | {result.finding_label ?? result.status} | {result.review_judgment ?? "Not judged"}
          </option>)}
        </select>
        {current && <ResultReview key={current.id} result={current}
          reviewable={reviewable && attempt.mode === "llm" && attempt.scope === "sample" && !running && isSuccessfulResult(current)}
          pending={judge.isPending} onJudge={(judgment, date) => judge.mutate({
            resultId: current.id, judgment, event_date_override: date || null,
          })} />}
      </>}
      {judge.error && <p role="alert" className="text-destructive">Unable to save the judgment. Try again.</p>}
    </section>
    <section aria-label="Matched notes" className="space-y-3">
      <h3 className="font-medium">Matched notes</h3>
      {matchesLoading ? <p className="text-sm">Loading matched notes</p> : matchesError
        ? <p role="alert" className="text-destructive">Unable to load matched notes. Try refreshing the page.</p>
        : <>
          <p className="text-sm text-muted-foreground">{matchedNotes?.total_notes ?? 0} matched notes total | {new Set(visibleNotes.map((note) => note.patient_id)).size} distinct patients on this page | {visibleNotes.reduce((count, note) => count + note.matches.length, 0)} keyword matches on this page</p>
          {visibleNotes.length === 0 && <p className="text-sm text-muted-foreground">{running ? "Searching for matched notes" : "No matched notes"}</p>}
          {visibleNotes.map((note) => <details key={note.note_id} className="border-b pb-3 text-sm">
            <summary className="cursor-pointer break-words">Patient {note.patient_id} | Note {note.note_id}
              {note.note_date && ` | ${new Date(note.note_date).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })}`}
            </summary>
            <p className="mt-2 whitespace-pre-wrap break-words"><HighlightedNote note={note} /></p>
          </details>)}
          <nav aria-label="Matched notes pagination" className="flex items-center gap-3">
            <Button variant="outline" size="icon" aria-label="Previous matched notes page" title="Previous matched notes page"
              disabled={page <= 1} onClick={() => setNotePage({ attemptId, page: page - 1 })}><ChevronLeft className="h-4 w-4" /></Button>
            <span className="text-sm">Page {matchedNotes?.page ?? page} of {totalPages}</span>
            <Button variant="outline" size="icon" aria-label="Next matched notes page" title="Next matched notes page"
              disabled={page >= totalPages} onClick={() => setNotePage({ attemptId, page: page + 1 })}><ChevronRight className="h-4 w-4" /></Button>
          </nav>
        </>}
    </section>
    <section aria-label="Cited note evidence" className="space-y-3">
      <h3 className="font-medium">Cited note evidence</h3>
      {notes.length === 0 ? <p className="text-sm text-muted-foreground">No cited note evidence</p>
        : notes.map((note, index) => (
          <details key={`${note.note_id}:${index}`} className="border-b pb-3 text-sm">
            <summary className="cursor-pointer break-words">Patient {note.patient_id} | Note {note.note_id}</summary>
            <p className="mt-2 whitespace-pre-wrap break-words">{note.text}</p>
          </details>
        ))}
    </section>
    {attempt.mode === "llm" && attempt.scope === "sample" && <div className="space-y-2 border-t pt-4">
      <Button disabled={!canCommit || commit.isPending} onClick={() => commit.mutate()}>
        <Play className="mr-2 h-4 w-4" />Commit selected attempt
      </Button>
      <p className="text-sm text-muted-foreground">{successful.length} successful results; {results.filter((result) => result.status.toLowerCase() === "failed").length} failed results</p>
      {commit.error && <p role="alert" className="text-destructive">Unable to commit the attempt. Try again.</p>}
    </div>}
  </div>;
}

function HighlightedNote({ note }: { note: MatchedNote }) {
  const ranges = note.matches.filter((match) => Number.isInteger(match.note_start_index)
    && Number.isInteger(match.note_end_index) && match.note_start_index >= 0
    && match.note_end_index > match.note_start_index && match.note_end_index <= note.text.length)
    .map((match) => ({ start: match.note_start_index, end: match.note_end_index }))
    .sort((first, second) => first.start - second.start);
  const merged: { start: number; end: number }[] = [];
  for (const range of ranges) {
    const previous = merged[merged.length - 1];
    if (previous && range.start <= previous.end) previous.end = Math.max(previous.end, range.end);
    else merged.push({ ...range });
  }
  let offset = 0;
  const fragments = merged.map((range) => {
    const prefix = note.text.slice(offset, range.start);
    offset = range.end;
    return <span key={range.start}>{prefix}<mark>{note.text.slice(range.start, range.end)}</mark></span>;
  });
  return <>{fragments}{note.text.slice(offset)}</>;
}

function ResultReview({ result, reviewable, pending, onJudge }: {
  result: AttemptResult;
  reviewable: boolean;
  pending: boolean;
  onJudge: (judgment: string, date: string) => void;
}) {
  const [date, setDate] = useState("");
  const confidence = result.finding_confidence ?? result.predicted_score;
  return <div className="space-y-3">
    <p className="text-sm">{result.finding_label ?? result.status}{confidence != null ? ` | ${(confidence * 100).toFixed(0)}% confidence` : ""}</p>
    <p className="whitespace-pre-wrap text-sm">{result.finding_reasoning}</p>
    <p className="text-sm">Judgment: {result.review_judgment ?? "Not judged"}</p>
    {reviewable && <>
      <Label htmlFor="event-date-override">Event date override</Label>
      <Input id="event-date-override" type="date" value={date} disabled={pending} onChange={(event) => setDate(event.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={pending} onClick={() => onJudge("correct", date)}><Check className="mr-2 h-4 w-4" />Correct</Button>
        <Button variant="outline" disabled={pending} onClick={() => onJudge("wrong", date)}><X className="mr-2 h-4 w-4" />Wrong</Button>
        <Button variant="outline" disabled={pending} onClick={() => onJudge("skipped", date)}><SkipForward className="mr-2 h-4 w-4" />Skip</Button>
      </div>
    </>}
  </div>;
}