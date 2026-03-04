import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  AlertTriangle,
  Trash2,
  MoreHorizontal,
  HelpCircle,
  X,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ── Types ───────────────────────────────────────────────────────

interface Annotation {
  id: string;
  project_id: string;
  patient_id: string;
  note_id: string;
  sentence_id: string;
  sentence_text: string;
  matched_tokens: string;
  is_negated: boolean;
  predicted_score: number | null;
  predicted_label: number | null;
  predictor_model: string;
  reasoning: string;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  event_date: string | null;
  created_at: string;
}

interface PatientAnnotation extends Annotation {
  note_date: string | null;
  note_text_id: string;
  sentence_number: number;
}

interface PatientInfo {
  patient_id: string | null;
  patient_id_ext: string | null;
  total_annotations: number;
  unreviewed_annotations: number;
  all_complete: boolean;
}

interface ReviewResult {
  annotation: Annotation;
  skipped_count: number;
}

interface DeleteEventDateResult {
  annotation: Annotation;
  reverted_count: number;
}

interface PatientReviewStats {
  total: number;
  unreviewed: number;
  reviewed: number;
  skipped: number;
  current_event_date: string | null;
  event_annotation_id: string | null;
}

interface NoteContext {
  note_id: string;
  patient_id: string;
  patient_id_ext: string;
  text: string;
  text_id: string;
  note_date: string | null;
  sentences: {
    id: string;
    text: string;
    start_pos: number;
    end_pos: number;
    is_target: boolean;
    is_negated: boolean;
    matched_tokens: string[];
  }[];
}

interface AnnotationStats {
  total: number;
  unreviewed: number;
  reviewed: number;
  skipped: number;
  events_found: number;
  is_complete: boolean;
}

// ── Utilities ───────────────────────────────────────────────────

function highlightMatches(text: string, tokens: string): React.ReactNode {
  if (!tokens) return text;
  const tokenList = tokens.split(",").filter(Boolean);
  if (tokenList.length === 0) return text;

  const pattern = new RegExp(
    `(${tokenList.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "gi"
  );
  const parts = text.split(pattern);

  return parts.map((part, i) =>
    tokenList.some((t) => t.toLowerCase() === part.toLowerCase()) ? (
      <mark
        key={i}
        className="rounded-sm bg-amber-200 px-0.5 font-semibold text-amber-950 dark:bg-amber-500/30 dark:text-amber-100"
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function formatScore(score: number | null): string {
  if (score === null) return "--";
  return (score * 100).toFixed(1) + "%";
}

// ── Collapsible Section ────────────────────────────────────────

function CollapsibleSection({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-90" : ""}`}
        />
        {summary}
      </button>
      {open && <div className="mt-2 pl-5">{children}</div>}
    </div>
  );
}

// ── Note Context Viewer ─────────────────────────────────────────

function NoteViewer({
  context,
  targetSentenceId,
}: {
  context: NoteContext;
  targetSentenceId: string;
}) {
  const targetRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    targetRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [targetSentenceId]);

  return (
    <div
      className="max-h-72 overflow-y-auto text-[15px] leading-relaxed"
      style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
      role="region"
      aria-label="Clinical note context"
    >
      {context.sentences.map((sent) => {
        const isTarget = sent.id === targetSentenceId;
        const isOtherTarget = sent.is_target && !isTarget;

        return (
          <span
            key={sent.id}
            ref={isTarget ? targetRef : undefined}
            className={
              isTarget
                ? "rounded-sm bg-accent/20 px-0.5 font-medium text-foreground outline outline-2 outline-accent/50"
                : isOtherTarget
                  ? "text-foreground/60 underline decoration-accent/40 decoration-1 underline-offset-2"
                  : "text-foreground/40"
            }
            aria-current={isTarget ? "true" : undefined}
          >
            {sent.text}{" "}
          </span>
        );
      })}
    </div>
  );
}

// ── Loading Skeleton ────────────────────────────────────────────

function ReviewSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading annotations">
      <div className="flex items-center justify-between">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-8 w-24" />
      </div>
      <Skeleton className="h-px w-full" />
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-5 w-32" />
      <div className="flex justify-between">
        <Skeleton className="h-9 w-28" />
        <Skeleton className="h-9 w-28" />
      </div>
    </div>
  );
}

// ── Keyboard Shortcuts Help Overlay ─────────────────────────────

function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-80 rounded-lg border border-border bg-card p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-foreground">Keyboard Shortcuts</h4>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-1.5 text-sm">
          {[
            ["A", "No Event (adjudicate)"],
            ["E", "Toggle event date input"],
            ["D", "Delete event date"],
            ["\u2190", "Previous annotation"],
            ["\u2192", "Next annotation"],
            ["Shift+\u2190", "Back 10"],
            ["Shift+\u2192", "Forward 10"],
            ["Home", "First annotation"],
            ["End", "Last annotation"],
            ["?", "Toggle this help"],
          ].map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between">
              <span className="text-muted-foreground">{desc}</span>
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {key}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Annotation Status Strip ─────────────────────────────────────

function AnnotationStatusStrip({
  annotations,
  currentIndex,
  onNavigate,
}: {
  annotations: PatientAnnotation[];
  currentIndex: number;
  onNavigate: (index: number) => void;
}) {
  return (
    <div
      className="flex flex-wrap gap-1 rounded-md border border-border bg-muted/50 px-3 py-2"
      role="navigation"
      aria-label="Annotation status overview"
    >
      {annotations.map((ann, i) => {
        const isCurrent = i === currentIndex;
        const colorClass =
          ann.review_status === "reviewed"
            ? "bg-emerald-500"
            : ann.review_status === "skipped"
              ? "bg-muted-foreground/40"
              : "bg-amber-400";

        return (
          <button
            key={ann.id}
            onClick={() => onNavigate(i)}
            className={`h-3 w-3 rounded-full transition-all ${colorClass} ${
              isCurrent ? "ring-2 ring-accent ring-offset-1 ring-offset-background" : "hover:ring-1 hover:ring-border"
            }`}
            aria-label={`Annotation ${i + 1}: ${ann.review_status}`}
            aria-current={isCurrent ? "true" : undefined}
          />
        );
      })}
    </div>
  );
}

// ── Prediction Summary (collapsible) ────────────────────────────

function PredictionSummary({ annotation }: { annotation: PatientAnnotation }) {
  const hasLabel = annotation.predicted_label !== null;
  const labelText = annotation.predicted_label === 1 ? "Event Detected" : "No Event";

  const summaryLine = hasLabel
    ? `${labelText} \u00b7 ${formatScore(annotation.predicted_score)}`
    : `Score: ${formatScore(annotation.predicted_score)}`;

  return (
    <CollapsibleSection summary={summaryLine}>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2.5">
          {hasLabel && (
            <Badge
              variant={annotation.predicted_label === 1 ? "default" : "secondary"}
              className={
                annotation.predicted_label === 1
                  ? "bg-emerald-600 text-white hover:bg-emerald-700 dark:bg-emerald-600"
                  : ""
              }
            >
              {labelText}
            </Badge>
          )}
          <span className="text-sm text-foreground/70">
            Confidence:{" "}
            <span className="font-medium tabular-nums">
              {formatScore(annotation.predicted_score)}
            </span>
          </span>
          {annotation.is_negated && (
            <Badge
              variant="outline"
              className="gap-1 border-amber-400 text-amber-700 dark:border-amber-500 dark:text-amber-300"
            >
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              Negated
            </Badge>
          )}
          {annotation.predictor_model && (
            <span className="font-mono text-xs text-muted-foreground">
              {annotation.predictor_model}
            </span>
          )}
        </div>
        {annotation.reasoning && (
          <p className="rounded-md bg-muted/50 px-3 py-2 text-sm italic text-foreground/70">
            {annotation.reasoning}
          </p>
        )}
      </div>
    </CollapsibleSection>
  );
}

// ── Patient Review Panel ────────────────────────────────────────

function PatientReviewPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showEventDateInput, setShowEventDateInput] = useState(false);
  const [eventDateValue, setEventDateValue] = useState("");
  const [completionMessage, setCompletionMessage] = useState<string | null>(null);
  const [showStatusStrip, setShowStatusStrip] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);

  // 1. Get next patient
  const {
    data: patientInfo,
    isLoading: patientLoading,
    refetch: refetchPatient,
  } = useQuery<PatientInfo>({
    queryKey: ["patient-next", projectId],
    queryFn: () => api.get<PatientInfo>(`/projects/${projectId}/annotations/patient/next`),
  });

  const patientId = patientInfo?.patient_id;

  // 2. Get all annotations for the patient
  const {
    data: annotations,
    isLoading: annotationsLoading,
    refetch: refetchAnnotations,
  } = useQuery<PatientAnnotation[]>({
    queryKey: ["patient-annotations", projectId, patientId],
    queryFn: () =>
      api.get<PatientAnnotation[]>(
        `/projects/${projectId}/annotations/patient/${patientId}/annotations`
      ),
    enabled: !!patientId,
  });

  // 3. Get patient stats
  const { data: patientStats, refetch: refetchStats } = useQuery<PatientReviewStats>({
    queryKey: ["patient-stats", projectId, patientId],
    queryFn: () =>
      api.get<PatientReviewStats>(
        `/projects/${projectId}/annotations/patient/${patientId}/stats`
      ),
    enabled: !!patientId,
  });

  const current = annotations?.[currentIndex] ?? null;

  // 4. Get note context for current annotation
  const { data: context, isLoading: contextLoading } = useQuery<NoteContext>({
    queryKey: ["annotation-context", current?.id],
    queryFn: () =>
      api.get<NoteContext>(
        `/projects/${current!.project_id}/annotations/${current!.id}/context`
      ),
    enabled: !!current,
  });

  // Navigate to first unreviewed when annotations load or change
  useEffect(() => {
    if (annotations && annotations.length > 0) {
      const firstUnreviewed = annotations.findIndex(
        (a) => a.review_status === "unreviewed"
      );
      if (firstUnreviewed >= 0) {
        setCurrentIndex(firstUnreviewed);
      }
    }
  }, [annotations]);

  // After action: refresh and advance
  const handlePostAction = useCallback(async () => {
    const { data: freshAnnotations } = await refetchAnnotations();
    await refetchStats();
    queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });

    if (!freshAnnotations) return;

    const hasUnreviewed = freshAnnotations.some(
      (a) => a.review_status === "unreviewed"
    );
    if (!hasUnreviewed) {
      const reviewed = freshAnnotations.filter((a) => a.review_status === "reviewed").length;
      const skipped = freshAnnotations.filter((a) => a.review_status === "skipped").length;
      const events = freshAnnotations.filter((a) => a.event_date).length;
      setCompletionMessage(
        `Patient ${patientInfo?.patient_id_ext} complete \u2014 ${reviewed} reviewed, ${skipped} skipped, ${events} event${events !== 1 ? "s" : ""}`
      );
      setTimeout(() => {
        setCompletionMessage(null);
        setCurrentIndex(0);
        queryClient.removeQueries({ queryKey: ["patient-annotations", projectId, patientId] });
        queryClient.removeQueries({ queryKey: ["patient-stats", projectId, patientId] });
        refetchPatient();
      }, 2000);
    } else {
      const nextIdx = freshAnnotations.findIndex(
        (a, i) => a.review_status === "unreviewed" && i > currentIndex
      );
      if (nextIdx >= 0) {
        setCurrentIndex(nextIdx);
      } else {
        const firstUnreviewed = freshAnnotations.findIndex(
          (a) => a.review_status === "unreviewed"
        );
        if (firstUnreviewed >= 0) setCurrentIndex(firstUnreviewed);
      }
    }
  }, [
    refetchAnnotations,
    refetchStats,
    queryClient,
    projectId,
    patientId,
    patientInfo,
    currentIndex,
    refetchPatient,
  ]);

  // Adjudicate mutation
  const reviewMutation = useMutation({
    mutationFn: ({
      id,
      event_date,
    }: {
      id: string;
      event_date?: string;
    }) =>
      api.post<ReviewResult>(`/projects/${projectId}/annotations/${id}/review`, {
        event_date: event_date || null,
      }),
    onSuccess: () => {
      setShowEventDateInput(false);
      setEventDateValue("");
      handlePostAction();
    },
  });

  // Delete event date mutation
  const deleteEventDateMutation = useMutation({
    mutationFn: (annotationId: string) =>
      api.post<DeleteEventDateResult>(
        `/projects/${projectId}/annotations/${annotationId}/delete-event-date`,
        {}
      ),
    onSuccess: async () => {
      await refetchAnnotations();
      await refetchStats();
      queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
      if (annotations) {
        const firstUnreviewed = annotations.findIndex(
          (a) => a.review_status === "unreviewed"
        );
        if (firstUnreviewed >= 0) setCurrentIndex(firstUnreviewed);
      }
    },
  });

  const total = annotations?.length ?? 0;

  const handleAdjudicate = useCallback(() => {
    if (!current || reviewMutation.isPending) return;
    reviewMutation.mutate({ id: current.id });
  }, [current, reviewMutation]);

  const handleEventDate = useCallback(() => {
    if (!current || !eventDateValue) return;
    reviewMutation.mutate({
      id: current.id,
      event_date: eventDateValue + "T00:00:00Z",
    });
  }, [current, eventDateValue, reviewMutation]);

  const handleDeleteEventDate = useCallback(() => {
    if (!patientStats?.event_annotation_id || deleteEventDateMutation.isPending) return;
    deleteEventDateMutation.mutate(patientStats.event_annotation_id);
  }, [patientStats, deleteEventDateMutation]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) setCurrentIndex((i) => i - 1);
  }, [currentIndex]);

  const handleNext = useCallback(() => {
    if (currentIndex < total - 1) setCurrentIndex((i) => i + 1);
  }, [currentIndex, total]);

  const handlePrevPage = useCallback(() => {
    setCurrentIndex((i) => Math.max(0, i - 10));
  }, []);

  const handleNextPage = useCallback(() => {
    setCurrentIndex((i) => Math.min(total - 1, i + 10));
  }, [total]);

  const handleFirst = useCallback(() => {
    setCurrentIndex(0);
  }, []);

  const handleLast = useCallback(() => {
    if (total > 0) setCurrentIndex(total - 1);
  }, [total]);

  // Default event date to note date when input is shown
  useEffect(() => {
    if (showEventDateInput && !eventDateValue && current) {
      const noteDate = current.note_date?.slice(0, 10);
      if (noteDate) setEventDateValue(noteDate);
    }
  }, [showEventDateInput, current?.note_date]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard shortcuts
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      switch (e.key.toLowerCase()) {
        case "a":
          e.preventDefault();
          handleAdjudicate();
          break;
        case "e":
          e.preventDefault();
          setShowEventDateInput((v) => !v);
          break;
        case "d":
          e.preventDefault();
          handleDeleteEventDate();
          break;
        case "arrowleft":
          e.preventDefault();
          if (e.shiftKey) handlePrevPage();
          else handlePrev();
          break;
        case "arrowright":
          e.preventDefault();
          if (e.shiftKey) handleNextPage();
          else handleNext();
          break;
        case "home":
          e.preventDefault();
          handleFirst();
          break;
        case "end":
          e.preventDefault();
          handleLast();
          break;
        case "?":
          e.preventDefault();
          setShowShortcuts((v) => !v);
          break;
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [
    handleAdjudicate,
    handleDeleteEventDate,
    handlePrev,
    handleNext,
    handlePrevPage,
    handleNextPage,
    handleFirst,
    handleLast,
  ]);

  // Unlock patient on unmount
  useEffect(() => {
    const pid = patientId;
    return () => {
      if (pid) {
        navigator.sendBeacon(
          `/api/v1/projects/${projectId}/annotations/patient/${pid}/unlock`,
          ""
        );
      }
    };
  }, [patientId, projectId]);

  // Loading state
  if (patientLoading || annotationsLoading) {
    return <ReviewSkeleton />;
  }

  // Completion overlay
  if (completionMessage) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-12 dark:border-emerald-700 dark:bg-emerald-950/20"
        role="status"
      >
        <CheckCircle2 className="mb-3 h-8 w-8 text-emerald-500" aria-hidden="true" />
        <p className="font-medium text-foreground">{completionMessage}</p>
        <p className="mt-1 text-sm text-muted-foreground">Loading next patient...</p>
      </div>
    );
  }

  // All patients complete
  if (patientInfo?.all_complete) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-12"
        role="status"
      >
        <CheckCircle2 className="mb-3 h-8 w-8 text-emerald-500" aria-hidden="true" />
        <p className="font-medium text-foreground">All patients reviewed</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Every patient has been fully annotated.
        </p>
      </div>
    );
  }

  // No patient available
  if (!patientId || !annotations || annotations.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-12"
        role="status"
      >
        <BarChart3 className="mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <p className="font-medium text-foreground">No patients available</p>
        <p className="mt-1 text-sm text-muted-foreground">
          All patients may be locked by other reviewers, or no annotations exist yet.
        </p>
      </div>
    );
  }

  if (!current) return null;

  const isPending = reviewMutation.isPending || deleteEventDateMutation.isPending;
  const reviewed = patientStats ? patientStats.reviewed + patientStats.skipped : 0;
  const patientTotal = patientStats?.total ?? total;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="space-y-0" role="region" aria-label="Patient annotation review">
        {/* Shortcuts overlay */}
        {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}

        {/* Compact nav line: Patient + progress counter + nav + event date + overflow */}
        <div className="flex items-center gap-3 text-sm">
          <span className="font-medium text-foreground">
            Patient <span className="font-mono">{patientInfo?.patient_id_ext ?? patientId.slice(0, 8)}</span>
          </span>
          <span className="text-muted-foreground">&middot;</span>
          <span className="text-muted-foreground">
            {reviewed}/{patientTotal} reviewed
          </span>
          <span className="text-muted-foreground">&middot;</span>

          {/* Compact navigation: < [5/12] > */}
          <div className="flex items-center gap-1" role="navigation" aria-label="Annotation navigation">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handlePrev}
              disabled={currentIndex === 0}
              aria-label="Previous annotation (\u2190)"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-14 text-center font-medium tabular-nums text-foreground">
              {currentIndex + 1}/{total}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handleNext}
              disabled={currentIndex >= total - 1}
              aria-label="Next annotation (\u2192)"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          {/* Event date badge (if set) */}
          {patientStats?.current_event_date && (
            <>
              <span className="text-muted-foreground">&middot;</span>
              <div className="flex items-center gap-1.5">
                <Badge className="gap-1 bg-rose-600 text-white hover:bg-rose-700">
                  <CalendarDays className="h-3 w-3" aria-hidden="true" />
                  Event: {new Date(patientStats.current_event_date).toLocaleDateString()}
                </Badge>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      className="text-muted-foreground hover:text-destructive"
                      onClick={handleDeleteEventDate}
                      disabled={deleteEventDateMutation.isPending}
                      aria-label="Delete event date (D)"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Delete event date (D)</TooltipContent>
                </Tooltip>
              </div>
            </>
          )}

          <div className="flex-1" />

          {/* Toggle status strip */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setShowStatusStrip((v) => !v)}
                aria-label="Toggle annotation status strip"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Status overview</TooltipContent>
          </Tooltip>

          {/* Shortcuts help */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setShowShortcuts((v) => !v)}
                aria-label="Keyboard shortcuts (?)"
              >
                <HelpCircle className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Shortcuts (?)</TooltipContent>
          </Tooltip>
        </div>

        {/* Status strip (hidden by default) */}
        {showStatusStrip && (
          <div className="mt-2">
            <AnnotationStatusStrip
              annotations={annotations}
              currentIndex={currentIndex}
              onNavigate={setCurrentIndex}
            />
          </div>
        )}

        {/* Divider */}
        <div className="mt-3 border-t border-border" />

        {/* Note metadata */}
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <span>
            Note{" "}
            <span className="font-mono font-medium text-foreground/70">
              {current.note_text_id}
            </span>
          </span>
          {current.note_date && (
            <>
              <span>&mdash;</span>
              <span>{new Date(current.note_date).toLocaleDateString()}</span>
            </>
          )}
          <span>&mdash;</span>
          <Badge
            variant="outline"
            className={
              current.review_status === "reviewed"
                ? "border-emerald-400 text-emerald-700 dark:border-emerald-600 dark:text-emerald-300"
                : current.review_status === "skipped"
                  ? "border-muted-foreground/40 text-muted-foreground"
                  : "border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-300"
            }
          >
            {current.review_status}
          </Badge>
        </div>

        {/* Sentence under review */}
        <div className="mt-3">
          <p
            className="text-[17px] leading-relaxed text-foreground"
            style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
          >
            {highlightMatches(current.sentence_text, current.matched_tokens)}
          </p>
        </div>

        {/* Prediction summary (collapsed) */}
        <div className="mt-3">
          <PredictionSummary annotation={current} />
        </div>

        {/* Note context (collapsed) */}
        <div className="mt-4">
          {contextLoading ? (
            <Skeleton className="h-6 w-48 rounded-md" />
          ) : context ? (
            <CollapsibleSection summary="Full note context">
              <NoteViewer context={context} targetSentenceId={current.sentence_id} />
            </CollapsibleSection>
          ) : (
            <p className="text-sm text-muted-foreground">Note context unavailable.</p>
          )}
        </div>

        {/* Action buttons */}
        <div className="mt-6 flex items-center gap-3">
          <Button
            onClick={handleAdjudicate}
            disabled={isPending || current.review_status !== "unreviewed"}
            className="gap-1.5"
            aria-busy={reviewMutation.isPending}
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            {reviewMutation.isPending && !showEventDateInput
              ? "Saving\u2026"
              : "No Event (A)"}
          </Button>

          <div className="flex-1" />

          {!showEventDateInput ? (
            <Button
              variant="outline"
              onClick={() => setShowEventDateInput(true)}
              disabled={isPending || current.review_status !== "unreviewed"}
              className="gap-1.5"
            >
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
              Event Date (E)
            </Button>
          ) : (
            <div
              className="flex items-center gap-2"
              role="group"
              aria-label="Event date input"
            >
              <Label
                htmlFor="event-date-input"
                className="text-sm text-foreground/70"
              >
                Event date:
              </Label>
              <Input
                id="event-date-input"
                type="date"
                className="h-8 w-40 text-sm"
                value={eventDateValue}
                onChange={(e) => setEventDateValue(e.target.value)}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleEventDate();
                  if (e.key === "Escape") {
                    setShowEventDateInput(false);
                    setEventDateValue("");
                  }
                }}
              />
              <Button
                size="sm"
                onClick={handleEventDate}
                disabled={!eventDateValue || isPending}
              >
                Confirm
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setShowEventDateInput(false);
                  setEventDateValue("");
                }}
              >
                Cancel
              </Button>
            </div>
          )}

          {/* Live region for mutation feedback */}
          <div className="sr-only" aria-live="assertive" aria-atomic="true">
            {reviewMutation.isSuccess && "Annotation adjudicated"}
            {deleteEventDateMutation.isSuccess && "Event date deleted, skips reverted"}
            {(reviewMutation.isError || deleteEventDateMutation.isError) &&
              "Action failed, please try again"}
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}

// ── Main Page Component ─────────────────────────────────────────

export default function AnnotationsPage() {
  const { projectId } = useParams<{ projectId: string }>();

  const { data: stats, isLoading: statsLoading } = useQuery<AnnotationStats>({
    queryKey: ["annotation-stats", projectId],
    queryFn: () =>
      api.get<AnnotationStats>(`/projects/${projectId}/annotations/stats`),
  });

  const hasAnnotations = stats && stats.total > 0;

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="annotations" projectId={projectId!} />

      {/* Header + project progress */}
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-foreground">Annotations</h2>
        {stats && stats.total > 0 && (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>
              <span className="font-medium tabular-nums text-foreground">{stats.reviewed}</span>/{stats.total} reviewed
            </span>
            <span className="text-border">|</span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{stats.unreviewed}</span> remaining
            </span>
            {stats.events_found > 0 && (
              <>
                <span className="text-border">|</span>
                <span>
                  <span className="font-medium tabular-nums text-foreground">{stats.events_found}</span> event{stats.events_found !== 1 ? "s" : ""}
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Review panel */}
      {statsLoading ? (
        <ReviewSkeleton />
      ) : hasAnnotations ? (
        <PatientReviewPanel projectId={projectId!} />
      ) : (
        <div
          className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-12"
          role="status"
        >
          <BarChart3
            className="mb-3 h-8 w-8 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="font-medium text-foreground">No annotations yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Validate and activate a predictor in{" "}
            <Link
              to={`/projects/${projectId}/evaluation`}
              className="text-accent underline hover:text-foreground"
            >
              Evaluation
            </Link>{" "}
            to generate predictions.
          </p>
        </div>
      )}
    </div>
  );
}
