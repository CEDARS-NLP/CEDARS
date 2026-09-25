import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, FlaskConical, Loader2, Play, Plus, RotateCcw } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface EvaluationPatient {
  patient_id: string;
  note_count: number;
}

interface EvaluationNote {
  note_id: string;
  patient_id: string;
  note_date: string;
  text: string;
}

interface EvaluationSession {
  eval_session_id: string;
  event_name: string;
  event_description: string;
  include_criteria: string;
  exclude_criteria: string;
  search_queries: { query: string; type: "include" | "exclude" }[];
  sample_patient_ids: string[];
  metrics: Record<string, number>;
  status: "draft" | "reviewing" | "completed";
  created_at: string;
}

interface EvaluationResult {
  evaluation_result_id: string;
  patient_id: string;
  note_id: string;
  model_name: string;
  predicted_score: number;
  predicted_label: string;
  classification_threshold: number;
  review_judgment: "correct" | "wrong" | "skipped" | null;
}

interface EvaluationMetrics {
  total_results: number;
  reviewed: number;
  correct: number;
  incorrect: number;
  skipped: number;
  accuracy: number | null;
}

const stepLabels = ["Define event", "Select patients", "Run classifier", "Review results", "Finalize"];

export default function EvaluationPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();
  const [selectedPatients, setSelectedPatients] = useState<string[]>([]);
  const [selectedNotes, setSelectedNotes] = useState<string[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [eventName, setEventName] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [includeCriteria, setIncludeCriteria] = useState("");
  const [excludeCriteria, setExcludeCriteria] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/projects/${projectId}/evaluation`;

  const patientsQuery = useQuery<EvaluationPatient[]>({
    queryKey: ["evaluation-patients", projectId],
    queryFn: () => api.get<EvaluationPatient[]>(`${base}/patients?limit=200`),
    enabled: Boolean(projectId),
  });
  const sessionsQuery = useQuery<EvaluationSession[]>({
    queryKey: ["evaluation-sessions", projectId],
    queryFn: () => api.get<EvaluationSession[]>(`${base}/sessions`),
    enabled: Boolean(projectId),
  });
  const notesQuery = useQuery<EvaluationNote[]>({
    queryKey: ["evaluation-notes", projectId, activeSessionId],
    queryFn: () => api.get<EvaluationNote[]>(`${base}/sessions/${activeSessionId}/notes`),
    enabled: Boolean(projectId && activeSessionId),
  });
  const resultsQuery = useQuery<EvaluationResult[]>({
    queryKey: ["evaluation-results", projectId, activeSessionId],
    queryFn: () => api.get<EvaluationResult[]>(`${base}/sessions/${activeSessionId}/results`),
    enabled: Boolean(projectId && activeSessionId),
  });
  const metricsQuery = useQuery<EvaluationMetrics>({
    queryKey: ["evaluation-metrics", projectId, activeSessionId],
    queryFn: () => api.get<EvaluationMetrics>(`${base}/sessions/${activeSessionId}/metrics`),
    enabled: Boolean(projectId && activeSessionId),
  });

  const activeSession = sessionsQuery.data?.find((session) => session.eval_session_id === activeSessionId);
  const completeStep = activeSession?.status === "completed" ? 5
    : resultsQuery.data?.some((result) => result.review_judgment) ? 4
      : resultsQuery.data?.length ? 3
        : activeSession ? 2
          : 1;

  function invalidateEvaluation() {
    queryClient.invalidateQueries({ queryKey: ["evaluation-sessions", projectId] });
    queryClient.invalidateQueries({ queryKey: ["evaluation-results", projectId, activeSessionId] });
    queryClient.invalidateQueries({ queryKey: ["evaluation-metrics", projectId, activeSessionId] });
  }

  async function createSession() {
    if (!projectId || !eventName.trim() || !selectedPatients.length) return;
    setBusy(true);
    setNotice("");
    try {
      const session = await api.post<EvaluationSession>(`${base}/sessions`, {
        event_name: eventName,
        event_description: eventDescription,
        include_criteria: includeCriteria,
        exclude_criteria: excludeCriteria,
        search_queries: [],
        sample_patient_ids: selectedPatients,
      });
      setActiveSessionId(session.eval_session_id);
      setSelectedNotes([]);
      invalidateEvaluation();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not create evaluation session");
    } finally {
      setBusy(false);
    }
  }

  async function runClassifier() {
    if (!activeSessionId || !selectedNotes.length) return;
    setBusy(true);
    setNotice("");
    try {
      await api.post(`${base}/sessions/${activeSessionId}/run`, { note_ids: selectedNotes });
      invalidateEvaluation();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "PINES evaluation failed");
    } finally {
      setBusy(false);
    }
  }

  async function judge(resultId: string, judgment: "correct" | "wrong" | "skipped") {
    if (!activeSessionId) return;
    try {
      await api.post(`${base}/sessions/${activeSessionId}/results/${resultId}/judge`, { judgment });
      invalidateEvaluation();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not save review");
    }
  }

  async function finalize() {
    if (!activeSessionId) return;
    setBusy(true);
    setNotice("");
    try {
      await api.post(`${base}/sessions/${activeSessionId}/finalize`);
      invalidateEvaluation();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not finalize evaluation");
    } finally {
      setBusy(false);
    }
  }

  function togglePatient(patientId: string) {
    setSelectedPatients((current) => current.includes(patientId)
      ? current.filter((id) => id !== patientId)
      : [...current, patientId]);
  }

  function toggleNote(noteId: string) {
    setSelectedNotes((current) => current.includes(noteId)
      ? current.filter((id) => id !== noteId)
      : [...current, noteId]);
  }

  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Project evaluation</p>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">Evaluation</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Evaluate a selected sample without changing the project annotation workflow.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Session
          <select
            className="h-9 min-w-52 rounded-md border border-input bg-background px-3 text-sm text-foreground"
            value={activeSessionId ?? ""}
            onChange={(event) => {
              const nextSessionId = event.target.value || null;
              setActiveSessionId(nextSessionId);
              setSelectedNotes([]);
            }}
          >
            <option value="">New evaluation</option>
            {(sessionsQuery.data ?? []).map((session) => (
              <option key={session.eval_session_id} value={session.eval_session_id}>
                {session.event_name} · {session.status}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-5" aria-label="Evaluation steps">
        {stepLabels.map((label, index) => {
          const number = index + 1;
          const done = number < completeStep;
          const current = number === completeStep;
          return (
            <div key={label} className={`flex items-center gap-2 border-t-2 px-2 py-3 text-sm ${
              done ? "border-emerald-600 text-emerald-700 dark:text-emerald-400"
                : current ? "border-primary font-medium text-foreground"
                  : "border-border text-muted-foreground"
            }`}>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs">
                {done ? <Check className="h-3.5 w-3.5" /> : number}
              </span>
              {label}
            </div>
          );
        })}
      </div>

      {notice && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{notice}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)]">
        <div className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="text-base">1. Define event</CardTitle></CardHeader>
            <CardContent className="grid gap-3">
              <label className="grid gap-1 text-sm font-medium">Event name
                <input className="h-9 rounded-md border border-input bg-background px-3 font-normal" value={eventName} onChange={(event) => setEventName(event.target.value)} disabled={Boolean(activeSessionId)} />
              </label>
              <label className="grid gap-1 text-sm font-medium">Description
                <textarea className="min-h-20 rounded-md border border-input bg-background px-3 py-2 font-normal" value={eventDescription} onChange={(event) => setEventDescription(event.target.value)} disabled={Boolean(activeSessionId)} />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm font-medium">Include criteria
                  <textarea className="min-h-20 rounded-md border border-input bg-background px-3 py-2 font-normal" value={includeCriteria} onChange={(event) => setIncludeCriteria(event.target.value)} disabled={Boolean(activeSessionId)} />
                </label>
                <label className="grid gap-1 text-sm font-medium">Exclude criteria
                  <textarea className="min-h-20 rounded-md border border-input bg-background px-3 py-2 font-normal" value={excludeCriteria} onChange={(event) => setExcludeCriteria(event.target.value)} disabled={Boolean(activeSessionId)} />
                </label>
              </div>
              {!activeSessionId && (
                <p className="text-xs text-muted-foreground">
                  These fields are saved with the evaluation session. PINES currently evaluates each note independently and does not use these criteria.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">2. Select patient sample</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {patientsQuery.isError ? (
                <p role="alert" className="text-sm text-destructive">Could not load project patients.</p>
              ) : patientsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading patients...</p>
              ) : !patientsQuery.data?.length ? (
                <p className="text-sm text-muted-foreground">No patient records are available in this project.</p>
              ) : (
                <div className="max-h-56 divide-y overflow-auto rounded-md border border-border">
                  {patientsQuery.data.map((patient) => (
                    <label key={patient.patient_id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-muted/40">
                      <input type="checkbox" checked={activeSessionId ? activeSession?.sample_patient_ids.includes(patient.patient_id) : selectedPatients.includes(patient.patient_id)} onChange={() => !activeSessionId && togglePatient(patient.patient_id)} disabled={Boolean(activeSessionId)} />
                      <span className="flex-1 font-mono">{patient.patient_id}</span>
                      <span className="text-xs text-muted-foreground">{patient.note_count} notes</span>
                    </label>
                  ))}
                </div>
              )}
              {!activeSessionId ? (
                <Button onClick={createSession} disabled={busy || !eventName.trim() || !selectedPatients.length}>
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
                  Create evaluation session
                </Button>
              ) : (
                <p className="text-sm text-muted-foreground">{activeSession?.sample_patient_ids.length ?? 0} patients in this session.</p>
              )}
            </CardContent>
          </Card>

          {activeSessionId && (
            <Card>
              <CardHeader><CardTitle className="text-base">3. Run classifier</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {notesQuery.isError ? (
                  <p role="alert" className="text-sm text-destructive">Could not load session notes.</p>
                ) : notesQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading notes...</p>
                ) : !notesQuery.data?.length ? (
                  <p className="text-sm text-muted-foreground">The selected patients have no notes to evaluate.</p>
                ) : (
                  <div className="max-h-64 divide-y overflow-auto rounded-md border border-border">
                    {notesQuery.data.map((note) => (
                      <label key={note.note_id} className="flex cursor-pointer items-start gap-3 px-3 py-2 text-sm hover:bg-muted/40">
                        <input className="mt-1" type="checkbox" checked={selectedNotes.includes(note.note_id)} onChange={() => toggleNote(note.note_id)} disabled={activeSession?.status === "completed"} />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap justify-between gap-2 font-medium"><span>{note.patient_id} / {note.note_id}</span><span className="text-xs text-muted-foreground">{note.note_date}</span></span>
                          <span className="mt-1 block line-clamp-2 text-xs text-muted-foreground">{note.text}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={runClassifier} disabled={busy || !selectedNotes.length || activeSession?.status === "completed"}>
                    {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                    Evaluate selected notes
                  </Button>
                  <span className="text-xs text-muted-foreground">Up to 50 notes per request; results are stored only in this evaluation.</span>
                </div>
              </CardContent>
            </Card>
          )}

          {activeSessionId && (
            <Card>
              <CardHeader><CardTitle className="text-base">4. Review results</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {resultsQuery.isError ? (
                  <p role="alert" className="text-sm text-destructive">Could not load evaluation results.</p>
                ) : !resultsQuery.data?.length ? (
                  <p className="text-sm text-muted-foreground">Run the classifier on selected notes to see results here.</p>
                ) : resultsQuery.data.map((result) => (
                  <div key={result.evaluation_result_id} className="grid gap-3 border-b border-border pb-3 last:border-0 sm:grid-cols-[1fr_auto] sm:items-center">
                    <div className="min-w-0 text-sm">
                      <p className="font-medium">{result.patient_id} / {result.note_id}</p>
                      <p className="text-xs text-muted-foreground">{result.model_name} · {result.predicted_label} · score {result.predicted_score.toFixed(3)} · threshold {result.classification_threshold.toFixed(3)}</p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(["correct", "wrong", "skipped"] as const).map((judgment) => (
                        <Button key={judgment} size="sm" variant={result.review_judgment === judgment ? "default" : "outline"} onClick={() => judge(result.evaluation_result_id, judgment)} disabled={activeSession?.status === "completed"}>
                          {judgment[0].toUpperCase() + judgment.slice(1)}
                        </Button>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-4 border-t border-border pt-3 text-sm">
                  <span>Reviewed: {metricsQuery.data?.reviewed ?? 0} / {metricsQuery.data?.total_results ?? 0}</span>
                  <span>Correct: {metricsQuery.data?.correct ?? 0}</span>
                  <span>Accuracy: {metricsQuery.data?.accuracy == null ? "—" : `${(metricsQuery.data.accuracy * 100).toFixed(1)}%`}</span>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <aside className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><FlaskConical className="h-4 w-4" />Session status</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              {activeSession ? (
                <>
                  <div className="flex justify-between gap-3"><span className="text-muted-foreground">Event</span><span className="text-right font-medium">{activeSession.event_name}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-muted-foreground">Status</span><span className="capitalize">{activeSession.status}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-muted-foreground">Created</span><span>{new Date(activeSession.created_at).toLocaleString()}</span></div>
                  {activeSession.status !== "completed" && (
                    <Button className="w-full" variant="outline" onClick={finalize} disabled={busy || !resultsQuery.data?.length}>
                      {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
                      Finalize evaluation
                    </Button>
                  )}
                  {activeSession.status === "completed" && <p className="text-xs text-muted-foreground">Finalized. No project workflow or pipeline was started.</p>}
                </>
              ) : (
                <p className="text-muted-foreground">Create a session after defining an event and selecting patients.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Previous evaluations</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {sessionsQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading sessions...</p>
                : sessionsQuery.isError ? <p className="text-sm text-destructive">Could not load sessions.</p>
                  : !sessionsQuery.data?.length ? <p className="text-sm text-muted-foreground">No sessions yet.</p>
                    : sessionsQuery.data.map((session) => (
                      <button key={session.eval_session_id} className="flex w-full items-center justify-between gap-3 border-b border-border py-2 text-left text-sm last:border-0 hover:text-primary" onClick={() => {
                        setActiveSessionId(session.eval_session_id);
                        setEventName(session.event_name);
                        setEventDescription(session.event_description);
                        setIncludeCriteria(session.include_criteria);
                        setExcludeCriteria(session.exclude_criteria);
                        setSelectedPatients(session.sample_patient_ids);
                        setSelectedNotes([]);
                      }}>
                        <span className="min-w-0 truncate">{session.event_name}</span>
                        <span className="shrink-0 text-xs capitalize text-muted-foreground">{session.status}</span>
                      </button>
                    ))}
              {activeSessionId && <Button variant="ghost" size="sm" className="mt-1" onClick={() => {
                setActiveSessionId(null);
                setEventName("");
                setEventDescription("");
                setIncludeCriteria("");
                setExcludeCriteria("");
                setSelectedPatients([]);
                setSelectedNotes([]);
              }}><RotateCcw className="mr-2 h-3.5 w-3.5" />New session</Button>}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}