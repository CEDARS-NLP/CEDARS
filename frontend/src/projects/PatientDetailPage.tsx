import { useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  CalendarDays,
} from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import ReviewProvenance, { type ReviewMetadata } from "./ReviewProvenance";

// ── Types ───────────────────────────────────────────────────────

interface NoteResponse {
  id: string;
  patient_id: string;
  text_id: string;
  note_date: string;
  text: string;
  source_ref: string | null;
  created_at: string;
}

interface PatientAnnotation extends ReviewMetadata {
  id: string;
  note_id: string;
  sentence_text: string;
  matched_tokens: string;
  is_negated: boolean;
  predicted_score: number | null;
  predicted_label: number | null;
  predictor_model: string;
  reasoning: string;
  review_status: string;
  event_date: string | null;
  note_date: string | null;
  note_text_id: string;
  sentence_number: number;
}

interface PatientReviewStats {
  total: number;
  unreviewed: number;
  reviewed: number;
  skipped: number;
  current_event_date: string | null;
  event_annotation_id: string | null;
}

interface PatientListItem extends ReviewMetadata {
  id: string;
  patient_id_ext: string;
  status: string;
  note_count: number;
  created_at: string;
}

interface PatientListResponse {
  items: PatientListItem[];
  total: number;
  limit: number;
  offset: number;
}

// ── Helpers ─────────────────────────────────────────────────────

function statusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function reviewBadgeVariant(
  s: string,
): "default" | "secondary" | "destructive" | "outline" {
  switch (s) {
    case "reviewed":
      return "default";
    case "skipped":
      return "secondary";
    default:
      return "outline";
  }
}

function groupAnnotationsByNote(
  annotations: PatientAnnotation[],
): Map<string, PatientAnnotation[]> {
  const map = new Map<string, PatientAnnotation[]>();
  for (const a of annotations) {
    const list = map.get(a.note_id) || [];
    list.push(a);
    map.set(a.note_id, list);
  }
  return map;
}

// ── Component ───────────────────────────────────────────────────

export default function PatientDetailPage() {
  const { projectId, patientId } = useParams<{
    projectId: string;
    patientId: string;
  }>();
  const queryClient = useQueryClient();
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [reopenOpen, setReopenOpen] = useState(false);
  const reopenSubmitting = useRef(false);

  const { data: project } = useQuery<{ role: string | null }>({
    queryKey: ["project", projectId],
    queryFn: () => api.get(`/projects/${projectId}`),
    enabled: !!projectId,
  });
  const isAdmin = project?.role === "admin";

  // Fetch patient info from list endpoint (filter by ID to get status)
  const { data: patientData } = useQuery<PatientListResponse>({
    queryKey: ["patient-info", projectId, patientId],
    queryFn: () =>
      api.get(`/projects/${projectId}/data/patients?limit=50&offset=0`),
    enabled: !!projectId && !!patientId,
  });
  const patient = patientData?.items.find((p) => p.id === patientId);

  // Fetch notes
  const { data: notes, isLoading: notesLoading } = useQuery<NoteResponse[]>({
    queryKey: ["patient-notes", projectId, patientId],
    queryFn: () =>
      api.get(`/projects/${projectId}/data/patients/${patientId}/notes`),
    enabled: !!projectId && !!patientId,
  });

  // Fetch annotations
  const { data: annotations } = useQuery<PatientAnnotation[]>({
    queryKey: ["patient-annotations", projectId, patientId],
    queryFn: () =>
      api.get(
        `/projects/${projectId}/annotations/patient/${patientId}/annotations`,
      ),
    enabled: !!projectId && !!patientId,
  });

  // Fetch stats
  const { data: stats } = useQuery<PatientReviewStats>({
    queryKey: ["patient-stats", projectId, patientId],
    queryFn: () =>
      api.get(
        `/projects/${projectId}/annotations/patient/${patientId}/stats`,
      ),
    enabled: !!projectId && !!patientId,
  });

  // Reopen mutation
  const reopenMutation = useMutation({
    mutationFn: () =>
      api.post(
        `/projects/${projectId}/annotations/patient/${patientId}/reopen`,
        {},
      ),
    onSuccess: () => {
      setReopenOpen(false);
      queryClient.invalidateQueries({
        queryKey: ["patient-info", projectId, patientId],
      });
      queryClient.invalidateQueries({
        queryKey: ["patient-stats", projectId, patientId],
      });
      queryClient.invalidateQueries({ queryKey: ["patients", projectId] });
      queryClient.invalidateQueries({ queryKey: ["patient-annotations", projectId, patientId] });
      queryClient.invalidateQueries({ queryKey: ["annotation-context"] });
      queryClient.invalidateQueries({ queryKey: ["patient-matched-notes", projectId, patientId] });
      queryClient.invalidateQueries({ queryKey: ["patient-next", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project-stats", projectId] });
      queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
    },
    onSettled: () => { reopenSubmitting.current = false; },
  });

  const annotationsByNote = annotations
    ? groupAnnotationsByNote(annotations)
    : new Map<string, PatientAnnotation[]>();

  const toggleNote = (noteId: string) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(noteId)) {
        next.delete(noteId);
      } else {
        next.add(noteId);
      }
      return next;
    });
  };

  const handleReopen = () => {
    if (reopenSubmitting.current) return;
    reopenMutation.reset();
    setReopenOpen(true);
  };

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="data" projectId={projectId!} />

      {/* Back link */}
      <Link
        to={`/projects/${projectId}/patients`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to patients
      </Link>

      {/* Patient header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">
            {patient?.patient_id_ext ?? patientId}
          </h1>
          <div className="flex items-center gap-3">
            {patient && (
              <Badge variant="outline">{statusLabel(patient.status)}</Badge>
            )}
            {stats && stats.total > 0 && (
              <span className="text-sm text-muted-foreground">
                {stats.reviewed} reviewed, {stats.skipped} skipped,{" "}
                {stats.unreviewed} unreviewed of {stats.total} annotations
              </span>
            )}
            {stats?.current_event_date && (
              <span className="inline-flex items-center gap-1 text-sm text-amber-600 dark:text-amber-400">
                <CalendarDays className="h-3.5 w-3.5" />
                Event:{" "}
                {new Date(stats.current_event_date).toLocaleDateString()}
              </span>
            )}
          </div>
          {patient && <ReviewProvenance {...patient} />}
        </div>

        {/* Reopen button — admin only (the backend enforces it too) */}
        {isAdmin && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleReopen}
            disabled={reopenMutation.isPending}
          >
            <RotateCcw className="mr-1.5 h-4 w-4" />
            {reopenMutation.isPending ? "Reopening..." : "Reopen for review"}
          </Button>
        )}
      </div>
      {reopenMutation.isError && !reopenOpen && (
        <p role="alert" className="text-sm text-destructive">{reopenMutation.error.message}</p>
      )}
      <Dialog open={reopenOpen} onOpenChange={(open) => {
        if (!reopenSubmitting.current) setReopenOpen(open);
      }}>
        <DialogContent showCloseButton={!reopenMutation.isPending}>
          <DialogHeader>
            <DialogTitle>Reopen this patient for review?</DialogTitle>
            <DialogDescription>
              This returns the patient to the annotation queue and resets review decisions.
              Automated exclusions will be restored for human review. Predictions are preserved.
            </DialogDescription>
          </DialogHeader>
          {reopenMutation.isError && (
            <p role="alert" className="text-sm text-destructive">{reopenMutation.error.message}</p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={reopenMutation.isPending}
              onClick={() => setReopenOpen(false)}>Cancel</Button>
            <Button disabled={reopenMutation.isPending || !projectId || !patientId} onClick={() => {
              if (reopenSubmitting.current || !projectId || !patientId) return;
              reopenSubmitting.current = true;
              reopenMutation.mutate();
            }}>
              {reopenMutation.isPending ? "Reopening..." : "Reopen for review"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Notes list */}
      <div className="space-y-3">
        <h2 className="text-lg font-medium">
          Clinical notes{" "}
          {notes && (
            <span className="text-muted-foreground font-normal">
              ({notes.length})
            </span>
          )}
        </h2>

        {notesLoading ? (
          <p className="text-sm text-muted-foreground">Loading notes...</p>
        ) : !notes?.length ? (
          <p className="text-sm text-muted-foreground">
            No notes found for this patient.
          </p>
        ) : (
          notes.map((note) => {
            const noteAnnotations = annotationsByNote.get(note.id) || [];
            const isExpanded = expandedNotes.has(note.id);

            return (
              <div key={note.id} className="rounded-md border">
                {/* Note header */}
                <button
                  onClick={() => toggleNote(note.id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="font-medium text-sm">{note.text_id}</span>
                  <span className="text-sm text-muted-foreground">
                    {new Date(note.note_date).toLocaleDateString()}
                  </span>
                  {noteAnnotations.length > 0 && (
                    <Badge variant="secondary" className="ml-auto">
                      {noteAnnotations.length} annotation
                      {noteAnnotations.length !== 1 ? "s" : ""}
                    </Badge>
                  )}
                </button>

                {/* Note body (expanded) */}
                {isExpanded && (
                  <div className="border-t px-4 py-4 space-y-4">
                    {/* Full note text */}
                    <pre className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90 font-sans">
                      {note.text}
                    </pre>

                    {/* Annotations for this note */}
                    {noteAnnotations.length > 0 && (
                      <div className="space-y-2 border-t pt-3">
                        <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                          Annotations
                        </h4>
                        {noteAnnotations.map((ann) => (
                          <div
                            key={ann.id}
                            className="rounded border bg-muted/30 px-3 py-2 text-sm space-y-1"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="font-medium text-foreground/90 italic">
                                &ldquo;{ann.sentence_text}&rdquo;
                              </p>
                              <Badge
                                variant={reviewBadgeVariant(ann.review_status)}
                                className="shrink-0"
                              >
                                {statusLabel(ann.review_status)}
                              </Badge>
                            </div>
                            <ReviewProvenance {...ann} />
                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                              {ann.predicted_label !== null && (
                                <span>
                                  Prediction:{" "}
                                  {ann.predicted_label === 1
                                    ? "Positive"
                                    : "Negative"}
                                  {ann.predicted_score !== null &&
                                    ` (${(ann.predicted_score * 100).toFixed(0)}% likely)`}
                                </span>
                              )}
                              {ann.is_negated && <span>Negated</span>}
                              {ann.event_date && (
                                <span className="text-amber-600 dark:text-amber-400">
                                  Event:{" "}
                                  {new Date(
                                    ann.event_date,
                                  ).toLocaleDateString()}
                                </span>
                              )}
                              {ann.reasoning && (
                                <span className="basis-full">
                                  {ann.reasoning}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
