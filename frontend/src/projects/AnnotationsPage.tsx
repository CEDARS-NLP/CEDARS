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
  HelpCircle,
  X,
  User,
  FileText,
  Brain,
  ArrowRight,
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
  earlier_count: number;
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
  note_tags: Record<string, string>;
  search_keywords: string[];
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

interface MatchedNote {
  note_id: string;
  text_id: string;
  text: string;
  note_date: string | null;
  note_tags: Record<string, string>;
  matched_sentences: string[];
  match_positions: { start: number; end: number; text?: string; sentence_number?: number }[];
  search_keywords: string[];
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
  return (score * 100).toFixed(0) + "%";
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ── Sequence Markers ─────────────────────────────────────────────

function SequenceMarkers({
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
      className="flex items-center gap-1 px-1"
      role="navigation"
      aria-label="Annotation sequence"
    >
      {annotations.map((ann, i) => {
        const isCurrent = i === currentIndex;
        const status = ann.review_status;
        const bg =
          status === "reviewed"
            ? "bg-emerald-500"
            : status === "skipped"
              ? "bg-zinc-400 dark:bg-zinc-600"
              : "bg-amber-400 dark:bg-amber-500";

        return (
          <Tooltip key={ann.id}>
            <TooltipTrigger asChild>
              <button
                onClick={() => onNavigate(i)}
                className={`h-2.5 rounded-full transition-all ${bg} ${
                  isCurrent
                    ? "w-6 ring-2 ring-primary ring-offset-1 ring-offset-background"
                    : "w-2.5 hover:w-4 hover:ring-1 hover:ring-border"
                }`}
                aria-label={`Annotation ${i + 1}: ${status}`}
                aria-current={isCurrent ? "true" : undefined}
              />
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              #{i + 1} &middot; {status}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

// ── Keyword highlighter for note text ────────────────────────────

function highlightKeywords(
  text: string,
  keywords: string[]
): React.ReactNode {
  if (!keywords || keywords.length === 0) return text;

  // Build a regex that matches any keyword (with optional wildcard suffix)
  const escaped = keywords.map((k) =>
    k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(pattern);

  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return parts.map((part, i) =>
    lowerKeywords.some((k) => part.toLowerCase().startsWith(k)) ? (
      <mark
        key={i}
        className="rounded-sm bg-amber-200/70 px-0.5 text-amber-950 dark:bg-amber-500/30 dark:text-amber-100"
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

// ── Note Context Viewer ─────────────────────────────────────────

function NoteViewer({
  context,
  targetSentenceId,
  sentenceText,
  keywords,
}: {
  context: NoteContext;
  targetSentenceId: string;
  sentenceText: string;
  keywords: string[];
}) {
  const targetRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    targetRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [targetSentenceId]);

  const noteFont = { fontFamily: "Georgia, 'Times New Roman', serif" };

  if (context.sentences.length === 0) {
    // Pipeline annotations without NLP sentences — show raw note text
    // Try to find and highlight the sentence text within the note
    const noteText = context.text || "";
    const sentIdx = sentenceText
      ? noteText.toLowerCase().indexOf(sentenceText.slice(0, 60).toLowerCase())
      : -1;

    if (sentIdx === -1) {
      // Can't locate sentence — just highlight keywords
      return (
        <div
          className="whitespace-pre-wrap text-[14px] leading-relaxed text-foreground/60"
          style={noteFont}
        >
          {highlightKeywords(noteText, keywords)}
        </div>
      );
    }

    // Split into before / sentence region / after and highlight the sentence
    // Find the end by searching for the sentence text (use first 200 chars for matching)
    const matchLen = Math.min(sentenceText.length, 200);
    const before = noteText.slice(0, sentIdx);
    const matched = noteText.slice(sentIdx, sentIdx + matchLen);
    const after = noteText.slice(sentIdx + matchLen);

    return (
      <div
        className="whitespace-pre-wrap text-[14px] leading-relaxed"
        style={noteFont}
        role="region"
        aria-label="Clinical note context"
      >
        <span className="text-foreground/50">
          {highlightKeywords(before, keywords)}
        </span>
        <span
          ref={targetRef}
          className="rounded bg-primary/15 px-0.5 text-foreground ring-1 ring-primary/30"
        >
          {highlightKeywords(matched, keywords)}
        </span>
        <span className="text-foreground/50">
          {highlightKeywords(after, keywords)}
        </span>
      </div>
    );
  }

  return (
    <div
      className="text-[14px] leading-relaxed"
      style={noteFont}
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
                ? "rounded bg-primary/15 px-0.5 font-medium text-foreground ring-1 ring-primary/30"
                : isOtherTarget
                  ? "text-foreground/60 underline decoration-primary/30 decoration-1 underline-offset-2"
                  : "text-foreground/50"
            }
            aria-current={isTarget ? "true" : undefined}
          >
            {highlightKeywords(sent.text, keywords)}{" "}
          </span>
        );
      })}
    </div>
  );
}

// ── Keyboard Shortcuts Overlay ───────────────────────────────────

function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-80 rounded-lg border border-border bg-card p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-foreground">
            Keyboard Shortcuts
          </h4>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
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

// ── Loading Skeleton ────────────────────────────────────────────

function ReviewSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading annotations">
      <Skeleton className="h-10 w-full" />
      <div className="grid grid-cols-3 gap-6">
        <Skeleton className="h-64" />
        <Skeleton className="col-span-2 h-64" />
      </div>
    </div>
  );
}

// ── Pipeline Note Viewer (full note with matched regions highlighted) ────

function PipelineNoteViewer({
  noteText,
  matchPositions,
  keywords,
}: {
  noteText: string;
  matchPositions: { start: number; end: number; text?: string }[];
  keywords: string[];
}) {
  const firstMatchRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    firstMatchRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [noteText]);

  const noteFont = { fontFamily: "Georgia, 'Times New Roman', serif" };

  // Build sorted, non-overlapping match ranges
  const ranges = matchPositions
    .filter((p) => p.start < p.end)
    .sort((a, b) => a.start - b.start);

  if (ranges.length === 0) {
    return (
      <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-foreground/60" style={noteFont}>
        {highlightKeywords(noteText, keywords)}
      </div>
    );
  }

  const segments: React.ReactNode[] = [];
  let cursor = 0;
  let isFirst = true;

  for (const range of ranges) {
    if (range.start < cursor) continue;
    if (range.start > cursor) {
      segments.push(
        <span key={`pre-${cursor}`} className="text-foreground/50">
          {highlightKeywords(noteText.slice(cursor, range.start), keywords)}
        </span>
      );
    }
    const refProp = isFirst ? { ref: firstMatchRef } : {};
    segments.push(
      <span
        key={`match-${range.start}`}
        {...refProp}
        className="rounded bg-primary/15 px-0.5 text-foreground ring-1 ring-primary/30"
      >
        {highlightKeywords(noteText.slice(range.start, range.end), keywords)}
      </span>
    );
    isFirst = false;
    cursor = range.end;
  }

  if (cursor < noteText.length) {
    segments.push(
      <span key={`post-${cursor}`} className="text-foreground/50">
        {highlightKeywords(noteText.slice(cursor), keywords)}
      </span>
    );
  }

  return (
    <div className="whitespace-pre-wrap text-[14px] leading-relaxed" style={noteFont}>
      {segments}
    </div>
  );
}

// ── Patient Review Panel (two-column layout) ─────────────────────

function PatientReviewPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showEventDateInput, setShowEventDateInput] = useState(false);
  const [eventDateValue, setEventDateValue] = useState("");
  const [completionMessage, setCompletionMessage] = useState<string | null>(
    null
  );
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [earlierNotesBanner, setEarlierNotesBanner] = useState<string | null>(
    null
  );
  const [noteIndex, setNoteIndex] = useState(0);

  // 1. Get next patient
  const {
    data: patientInfo,
    isLoading: patientLoading,
    refetch: refetchPatient,
  } = useQuery<PatientInfo>({
    queryKey: ["patient-next", projectId],
    queryFn: () =>
      api.get<PatientInfo>(
        `/projects/${projectId}/annotations/patient/next`
      ),
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
  const { data: patientStats, refetch: refetchStats } =
    useQuery<PatientReviewStats>({
      queryKey: ["patient-stats", projectId, patientId],
      queryFn: () =>
        api.get<PatientReviewStats>(
          `/projects/${projectId}/annotations/patient/${patientId}/stats`
        ),
      enabled: !!patientId,
    });

  const current = annotations?.[currentIndex] ?? null;

  // 4. Get note context for current annotation
  const isPipelineAnnotation = !!current && !current.sentence_id;

  // 4a. Get note context for NLP sentence-level annotations
  const { data: context, isLoading: contextLoading } = useQuery<NoteContext>({
    queryKey: ["annotation-context", current?.id],
    queryFn: () =>
      api.get<NoteContext>(
        `/projects/${current!.project_id}/annotations/${current!.id}/context`
      ),
    enabled: !!current && !isPipelineAnnotation,
  });

  // 4b. Get all matched notes for pipeline annotations
  const { data: matchedNotes, isLoading: matchedNotesLoading } = useQuery<MatchedNote[]>({
    queryKey: ["patient-matched-notes", projectId, patientId, current?.id],
    queryFn: () =>
      api.get<MatchedNote[]>(
        `/projects/${projectId}/annotations/patient/${patientId}/matched-notes?annotation_id=${current!.id}`
      ),
    enabled: !!current && isPipelineAnnotation && !!patientId,
  });

  // Reset note index when patient changes
  useEffect(() => {
    setNoteIndex(0);
  }, [patientId]);

  // Navigate to first unreviewed when annotations load
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

  // Prefetch next annotation context
  useEffect(() => {
    if (!annotations || annotations.length <= 1) return;
    const nextAnno = annotations.find(
      (a, i) => i > currentIndex && a.review_status === "unreviewed"
    );
    if (nextAnno) {
      queryClient.prefetchQuery({
        queryKey: ["annotation-context", nextAnno.id],
        queryFn: () =>
          api.get<NoteContext>(
            `/projects/${nextAnno.project_id}/annotations/${nextAnno.id}/context`
          ),
      });
    }
  }, [annotations, currentIndex, queryClient]);

  // After action: refresh and advance
  const handlePostAction = useCallback(async () => {
    const { data: freshAnnotations } = await refetchAnnotations();
    await refetchStats();
    queryClient.invalidateQueries({
      queryKey: ["annotation-stats", projectId],
    });

    if (!freshAnnotations) return;

    const hasUnreviewed = freshAnnotations.some(
      (a) => a.review_status === "unreviewed"
    );
    if (!hasUnreviewed) {
      const reviewed = freshAnnotations.filter(
        (a) => a.review_status === "reviewed"
      ).length;
      const skipped = freshAnnotations.filter(
        (a) => a.review_status === "skipped"
      ).length;
      const events = freshAnnotations.filter((a) => a.event_date).length;
      setCompletionMessage(
        `Patient ${patientInfo?.patient_id_ext} complete \u2014 ${reviewed} reviewed, ${skipped} skipped, ${events} event${events !== 1 ? "s" : ""}`
      );
      queryClient.prefetchQuery({
        queryKey: ["patient-next", projectId],
        queryFn: () =>
          api.get<PatientInfo>(
            `/projects/${projectId}/annotations/patient/next`
          ),
      });
      setTimeout(() => {
        setCompletionMessage(null);
        setEarlierNotesBanner(null);
        setCurrentIndex(0);
        queryClient.removeQueries({
          queryKey: ["patient-annotations", projectId, patientId],
        });
        queryClient.removeQueries({
          queryKey: ["patient-stats", projectId, patientId],
        });
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

  // Mutations
  const reviewMutation = useMutation({
    mutationFn: ({ id, event_date }: { id: string; event_date?: string }) =>
      api.post<ReviewResult>(
        `/projects/${projectId}/annotations/${id}/review`,
        { event_date: event_date || null }
      ),
    onSuccess: (data) => {
      const hadEventDate = showEventDateInput && eventDateValue;
      setShowEventDateInput(false);
      setEventDateValue("");

      if (hadEventDate && data.earlier_count > 0) {
        setEarlierNotesBanner(
          `${data.earlier_count} earlier note${data.earlier_count > 1 ? "s" : ""} found before the event date \u2014 verify the earliest occurrence.`
        );
      } else if (hadEventDate && data.earlier_count === 0) {
        setEarlierNotesBanner(null);
      }

      handlePostAction();
    },
  });

  const deleteEventDateMutation = useMutation({
    mutationFn: (annotationId: string) =>
      api.post<DeleteEventDateResult>(
        `/projects/${projectId}/annotations/${annotationId}/delete-event-date`,
        {}
      ),
    onSuccess: async () => {
      await refetchAnnotations();
      await refetchStats();
      queryClient.invalidateQueries({
        queryKey: ["annotation-stats", projectId],
      });
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
    if (
      !patientStats?.event_annotation_id ||
      deleteEventDateMutation.isPending
    )
      return;
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

  // Default event date to note date
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

  // Loading
  if (patientLoading || annotationsLoading) {
    return <ReviewSkeleton />;
  }

  // Completion overlay
  if (completionMessage) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-16 dark:border-emerald-700 dark:bg-emerald-950/20"
        role="status"
      >
        <CheckCircle2
          className="mb-3 h-10 w-10 text-emerald-500"
          aria-hidden="true"
        />
        <p className="text-lg font-medium text-foreground">
          {completionMessage}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Loading next patient...
        </p>
      </div>
    );
  }

  // All patients complete
  if (patientInfo?.all_complete) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-16"
        role="status"
      >
        <CheckCircle2
          className="mb-3 h-10 w-10 text-emerald-500"
          aria-hidden="true"
        />
        <p className="text-lg font-medium text-foreground">
          All patients reviewed
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Every patient has been fully annotated.
        </p>
      </div>
    );
  }

  // No patient
  if (!patientId || !annotations || annotations.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-16"
        role="status"
      >
        <BarChart3
          className="mb-3 h-10 w-10 text-muted-foreground"
          aria-hidden="true"
        />
        <p className="text-lg font-medium text-foreground">
          No patients available
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          All patients may be locked by other reviewers, or no annotations exist
          yet.
        </p>
      </div>
    );
  }

  if (!current) return null;

  const isPending =
    reviewMutation.isPending || deleteEventDateMutation.isPending;
  const reviewedCount = patientStats
    ? patientStats.reviewed + patientStats.skipped
    : 0;
  const patientTotal = patientStats?.total ?? total;
  const progressPct =
    patientTotal > 0 ? Math.round((reviewedCount / patientTotal) * 100) : 0;

  return (
    <TooltipProvider delayDuration={200}>
      <div
        className="space-y-4"
        role="region"
        aria-label="Patient annotation review"
      >
        {showShortcuts && (
          <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />
        )}

        {/* ── Top Bar: Navigation + Sequence ─────────────────────── */}
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 px-4 py-2.5">
          {/* Navigation arrows */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={handlePrev}
            disabled={currentIndex === 0}
            aria-label="Previous annotation"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          <span className="min-w-[4rem] text-center text-sm font-medium tabular-nums text-foreground">
            {currentIndex + 1} of {total}
          </span>

          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={handleNext}
            disabled={currentIndex >= total - 1}
            aria-label="Next annotation"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>

          {/* Divider */}
          <div className="mx-1 h-5 w-px bg-border" />

          {/* Sequence markers */}
          <div className="min-w-0 flex-1 overflow-x-auto">
            <SequenceMarkers
              annotations={annotations}
              currentIndex={currentIndex}
              onNavigate={setCurrentIndex}
            />
          </div>

          {/* Divider */}
          <div className="mx-1 h-5 w-px bg-border" />

          {/* Status badge */}
          <Badge
            variant="outline"
            className={
              current.review_status === "reviewed"
                ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : current.review_status === "skipped"
                  ? "border-zinc-500/50 bg-zinc-500/10 text-zinc-500"
                  : "border-amber-500/50 bg-amber-500/10 text-amber-600 dark:text-amber-400"
            }
          >
            {current.review_status}
          </Badge>

          {/* Shortcuts help */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => setShowShortcuts((v) => !v)}
                aria-label="Keyboard shortcuts"
              >
                <HelpCircle className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Keyboard shortcuts (?)</TooltipContent>
          </Tooltip>
        </div>

        {/* Earlier notes banner */}
        {earlierNotesBanner && (
          <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
            <CalendarDays className="h-5 w-5 shrink-0 text-amber-500" />
            <span className="text-sm font-medium text-amber-700 dark:text-amber-300">
              {earlierNotesBanner}
            </span>
          </div>
        )}

        {/* ── Two-Column Layout ───────────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
          {/* ── LEFT PANEL: Patient Details ───────────────────── */}
          <div className="space-y-4">
            {/* Patient card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <User className="h-4 w-4" />
                Patient
              </div>

              <div className="space-y-3">
                <div>
                  <div className="font-mono text-lg font-semibold text-foreground">
                    {patientInfo?.patient_id_ext ?? patientId.slice(0, 8)}
                  </div>
                </div>

                {/* Progress bar */}
                <div>
                  <div className="mb-1.5 flex items-center justify-between text-xs text-muted-foreground">
                    <span>Review progress</span>
                    <span className="tabular-nums">
                      {reviewedCount}/{patientTotal}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all duration-300"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>

                {/* Stats row */}
                {patientStats && (
                  <div className="grid grid-cols-3 gap-2 pt-1">
                    <div className="rounded-md bg-muted/50 px-2 py-1.5 text-center">
                      <div className="text-xs text-muted-foreground">
                        Pending
                      </div>
                      <div className="text-sm font-semibold tabular-nums text-amber-600 dark:text-amber-400">
                        {patientStats.unreviewed}
                      </div>
                    </div>
                    <div className="rounded-md bg-muted/50 px-2 py-1.5 text-center">
                      <div className="text-xs text-muted-foreground">Done</div>
                      <div className="text-sm font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                        {patientStats.reviewed}
                      </div>
                    </div>
                    <div className="rounded-md bg-muted/50 px-2 py-1.5 text-center">
                      <div className="text-xs text-muted-foreground">
                        Skipped
                      </div>
                      <div className="text-sm font-semibold tabular-nums text-zinc-500">
                        {patientStats.skipped}
                      </div>
                    </div>
                  </div>
                )}

                {/* Event date (if set) */}
                {patientStats?.current_event_date && (
                  <div className="flex items-center justify-between rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <CalendarDays className="h-4 w-4 text-rose-500" />
                      <span className="text-sm font-medium text-rose-600 dark:text-rose-400">
                        Event:{" "}
                        {formatDate(patientStats.current_event_date)}
                      </span>
                    </div>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          className="text-rose-400 hover:text-rose-600"
                          onClick={handleDeleteEventDate}
                          disabled={deleteEventDateMutation.isPending}
                          aria-label="Delete event date"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>Delete event date (D)</TooltipContent>
                    </Tooltip>
                  </div>
                )}
              </div>
            </div>

            {/* AI Prediction card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Brain className="h-4 w-4" />
                AI Prediction
              </div>

              <div className="space-y-3">
                {/* Label + confidence */}
                <div className="flex items-center gap-2">
                  {current.predicted_label !== null && (
                    <Badge
                      className={
                        current.predicted_label === 1
                          ? "bg-emerald-600 text-white hover:bg-emerald-700"
                          : "bg-zinc-500 text-white hover:bg-zinc-600"
                      }
                    >
                      {current.predicted_label === 1
                        ? "Event Detected"
                        : "No Event"}
                    </Badge>
                  )}
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {formatScore(current.predicted_score)} confidence
                  </span>
                </div>

                {current.is_negated && (
                  <Badge
                    variant="outline"
                    className="gap-1 border-amber-400 text-amber-600 dark:text-amber-400"
                  >
                    <AlertTriangle className="h-3 w-3" />
                    Negated mention
                  </Badge>
                )}

                {/* Reasoning */}
                {current.reasoning && (
                  <div className="rounded-md bg-muted/50 p-3">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      Reasoning
                    </div>
                    <p className="text-sm leading-relaxed text-foreground/80">
                      {current.reasoning}
                    </p>
                  </div>
                )}

                {/* Model tag */}
                {current.predictor_model && (
                  <div className="text-xs text-muted-foreground">
                    Model:{" "}
                    <span className="font-mono">
                      {current.predictor_model}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* ── Actions ─────────────────────────────────────── */}
            <div className="space-y-2">
              <Button
                onClick={handleAdjudicate}
                disabled={
                  isPending || current.review_status !== "unreviewed"
                }
                className="w-full gap-2"
                size="lg"
                aria-busy={reviewMutation.isPending}
              >
                <CheckCircle2 className="h-4 w-4" />
                {reviewMutation.isPending && !showEventDateInput
                  ? "Saving\u2026"
                  : "No Event"}
                <kbd className="ml-auto rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-xs">
                  A
                </kbd>
              </Button>

              {!showEventDateInput ? (
                <Button
                  variant="outline"
                  onClick={() => setShowEventDateInput(true)}
                  disabled={
                    isPending || current.review_status !== "unreviewed"
                  }
                  className="w-full gap-2"
                  size="lg"
                >
                  <CalendarDays className="h-4 w-4" />
                  Set Event Date
                  <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 text-xs">
                    E
                  </kbd>
                </Button>
              ) : (
                <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
                  <Label
                    htmlFor="event-date-input"
                    className="text-sm text-foreground/70"
                  >
                    Event date
                  </Label>
                  <Input
                    id="event-date-input"
                    type="date"
                    className="text-sm"
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
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="flex-1"
                      onClick={handleEventDate}
                      disabled={!eventDateValue || isPending}
                    >
                      Confirm
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="flex-1"
                      onClick={() => {
                        setShowEventDateInput(false);
                        setEventDateValue("");
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ── RIGHT PANEL: Sentence + Full Note ─────────────── */}
          <div className="space-y-4">
            {isPipelineAnnotation ? (
              /* Pipeline annotation: show all matched notes, one at a time */
              matchedNotesLoading ? (
                <div className="space-y-2 rounded-lg border border-border bg-card p-4">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                  <Skeleton className="h-4 w-4/6" />
                </div>
              ) : matchedNotes && matchedNotes.length > 0 ? (
                <>
                  {/* Matched sentence excerpt */}
                  <div className="rounded-lg border border-border bg-card">
                    <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
                      <ArrowRight className="h-4 w-4 text-primary" />
                      <span className="text-sm font-medium text-foreground">
                        Matched Sentence
                      </span>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={() => setNoteIndex((i) => Math.max(0, i - 1))}
                          disabled={noteIndex === 0}
                        >
                          <ChevronLeft className="h-3.5 w-3.5" />
                        </Button>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          Note {noteIndex + 1} / {matchedNotes.length}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={() => setNoteIndex((i) => Math.min(matchedNotes.length - 1, i + 1))}
                          disabled={noteIndex >= matchedNotes.length - 1}
                        >
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                      <span className="text-muted-foreground">&middot;</span>
                      <span className="text-xs text-muted-foreground">
                        {matchedNotes[noteIndex].text_id}
                        {matchedNotes[noteIndex].note_date && ` \u2014 ${formatDate(matchedNotes[noteIndex].note_date)}`}
                      </span>
                      {matchedNotes[noteIndex].note_tags &&
                        Object.entries(matchedNotes[noteIndex].note_tags)
                          .filter(([k]) => k.startsWith("text_tag"))
                          .map(([key, val]) => (
                            <Badge
                              key={key}
                              variant="outline"
                              className="border-blue-500/30 bg-blue-500/10 px-1.5 py-0 text-[10px] font-normal text-blue-600 dark:text-blue-400"
                            >
                              {String(val)}
                            </Badge>
                          ))}
                    </div>
                    <div className="max-h-48 overflow-y-auto px-5 py-4">
                      {matchedNotes[noteIndex].matched_sentences.length > 0 ? (
                        <div className="space-y-2">
                          {matchedNotes[noteIndex].matched_sentences.map((sent, i) => (
                            <p
                              key={i}
                              className="text-[16px] leading-[1.8] text-foreground"
                              style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
                            >
                              {highlightKeywords(sent, matchedNotes[noteIndex].search_keywords)}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm italic text-muted-foreground">
                          No sentence-level matches for this note.
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Full note */}
                  <div className="rounded-lg border border-border bg-card">
                    <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium text-foreground">
                        Full Note
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {matchedNotes[noteIndex].text_id}
                        {matchedNotes[noteIndex].note_date && ` \u2014 ${formatDate(matchedNotes[noteIndex].note_date)}`}
                      </span>
                    </div>
                    <div className="h-[420px] overflow-y-auto px-5 py-4">
                      <PipelineNoteViewer
                        noteText={matchedNotes[noteIndex].text}
                        matchPositions={matchedNotes[noteIndex].match_positions}
                        keywords={matchedNotes[noteIndex].search_keywords}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="rounded-lg border border-border bg-card p-4">
                  <p className="text-sm text-muted-foreground">
                    No matched notes found for this patient.
                  </p>
                </div>
              )
            ) : (
              /* NLP sentence-level annotation: original layout */
              <>
                {/* Sentence under review */}
                <div className="rounded-lg border border-border bg-card">
                  <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
                    <ArrowRight className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium text-foreground">
                      Sentence Under Review
                    </span>
                    {current.note_date && (
                      <>
                        <span className="text-muted-foreground">&middot;</span>
                        <span className="text-xs text-muted-foreground">
                          Note {current.note_text_id} &mdash;{" "}
                          {formatDate(current.note_date)}
                        </span>
                      </>
                    )}
                    {context?.note_tags && Object.keys(context.note_tags).length > 0 && (
                      <>
                        <span className="text-muted-foreground">&middot;</span>
                        {Object.entries(context.note_tags)
                          .filter(([k]) => k.startsWith("text_tag"))
                          .sort(([a], [b]) => a.localeCompare(b))
                          .map(([key, val]) => (
                            <Badge
                              key={key}
                              variant="outline"
                              className="border-blue-500/30 bg-blue-500/10 px-1.5 py-0 text-[10px] font-normal text-blue-600 dark:text-blue-400"
                            >
                              {String(val)}
                            </Badge>
                          ))}
                      </>
                    )}
                  </div>
                  <div className="max-h-48 overflow-y-auto px-5 py-4">
                    <p
                      className="text-[16px] leading-[1.8] text-foreground"
                      style={{
                        fontFamily: "Georgia, 'Times New Roman', serif",
                      }}
                    >
                      {current.matched_tokens
                        ? highlightMatches(current.sentence_text, current.matched_tokens)
                        : highlightKeywords(
                            current.sentence_text,
                            context?.search_keywords ?? []
                          )}
                    </p>
                  </div>
                </div>

                {/* Full note context */}
                <div className="rounded-lg border border-border bg-card">
                  <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium text-foreground">
                      Full Note
                    </span>
                    {context && (
                      <span className="text-xs text-muted-foreground">
                        {context.text_id}
                        {context.note_date && ` \u2014 ${formatDate(context.note_date)}`}
                      </span>
                    )}
                  </div>
                  <div className="h-[420px] overflow-y-auto px-5 py-4">
                    {contextLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-5/6" />
                        <Skeleton className="h-4 w-4/6" />
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-3/6" />
                      </div>
                    ) : context ? (
                      <NoteViewer
                        context={context}
                        targetSentenceId={current.sentence_id}
                        sentenceText={current.sentence_text}
                        keywords={context.search_keywords ?? []}
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Note context unavailable.
                      </p>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Live region for screen readers */}
        <div className="sr-only" aria-live="assertive" aria-atomic="true">
          {reviewMutation.isSuccess && "Annotation adjudicated"}
          {deleteEventDateMutation.isSuccess &&
            "Event date deleted, skips reverted"}
          {(reviewMutation.isError || deleteEventDateMutation.isError) &&
            "Action failed, please try again"}
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
    <div className="space-y-5">
      <WorkflowBreadcrumb currentStep="annotations" projectId={projectId!} />

      {/* Header + stats */}
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-foreground">
          Annotation Review
        </h2>
        {stats && stats.total > 0 && (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>
              <span className="font-semibold tabular-nums text-foreground">
                {stats.reviewed}
              </span>
              /{stats.total} reviewed
            </span>
            <span className="text-border">|</span>
            <span>
              <span className="font-semibold tabular-nums text-foreground">
                {stats.unreviewed}
              </span>{" "}
              remaining
            </span>
            {stats.events_found > 0 && (
              <>
                <span className="text-border">|</span>
                <span>
                  <span className="font-semibold tabular-nums text-foreground">
                    {stats.events_found}
                  </span>{" "}
                  event{stats.events_found !== 1 ? "s" : ""}
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
          className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border py-16"
          role="status"
        >
          <BarChart3
            className="mb-3 h-10 w-10 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="text-lg font-medium text-foreground">
            No annotations yet
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Validate and activate a predictor in{" "}
            <Link
              to={`/projects/${projectId}/evaluation`}
              className="text-primary underline hover:text-foreground"
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
