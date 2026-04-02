import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  User,
  Check,
  X,
  SkipForward,
  CalendarDays,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { NextEvalResult, ResultNotesContext } from "@/projects/types";
import EvalNoteViewer from "./EvalNoteViewer";

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

const LABEL_COLORS: Record<string, string> = {
  positive: "bg-emerald-600 text-white hover:bg-emerald-700",
  negative: "bg-zinc-500 text-white hover:bg-zinc-600",
  inconclusive: "bg-amber-500 text-white hover:bg-amber-600",
};

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
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-1.5 text-sm">
          {[
            ["C", "Correct (agree with LLM)"],
            ["W", "Wrong (disagree with LLM)"],
            ["S", "Skip"],
            ["E", "Toggle event date override"],
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

export default function EvalReviewPanel({
  projectId,
  sessionId,
  onRefresh,
}: {
  projectId: string;
  sessionId: string;
  onRefresh: () => void;
}) {
  const queryClient = useQueryClient();
  const [afterId, setAfterId] = useState<number | null>(null);
  const [showDateOverride, setShowDateOverride] = useState(false);
  const [dateValue, setDateValue] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [completionMessage, setCompletionMessage] = useState<string | null>(null);
  const [noteIndex, setNoteIndex] = useState(0);

  const {
    data: current,
    isLoading,
    refetch,
  } = useQuery<NextEvalResult>({
    queryKey: ["eval-next-result", projectId, sessionId, afterId],
    queryFn: () => {
      const params = afterId != null ? `?after_id=${afterId}` : "";
      return api.get<NextEvalResult>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/next${params}`
      );
    },
    retry: false,
  });

  const { data: noteContext, isLoading: notesLoading } = useQuery<ResultNotesContext>({
    queryKey: ["eval-result-notes", projectId, sessionId, current?.id],
    queryFn: () =>
      api.get<ResultNotesContext>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/${current!.id}/notes`
      ),
    enabled: !!current,
  });

  // Sort notes: evidence notes first (positive signal), then chronologically
  const sortedNotes = useMemo(() => {
    if (!noteContext?.notes) return [];
    const notes = [...noteContext.notes];
    // If there are evidence notes, put them first; otherwise keep chrono order
    const evidenceNotes = notes.filter((n) => n.is_evidence);
    const otherNotes = notes.filter((n) => !n.is_evidence);
    if (evidenceNotes.length > 0) {
      return [...evidenceNotes, ...otherNotes];
    }
    return notes; // already chronologically ordered from backend
  }, [noteContext?.notes]);

  // Reset note index when patient changes
  useEffect(() => {
    setNoteIndex(0);
  }, [current?.id]);

  useEffect(() => {
    if (showDateOverride && !dateValue && current?.event_date) {
      setDateValue(current.event_date.slice(0, 10));
    }
  }, [showDateOverride, current?.event_date]); // eslint-disable-line react-hooks/exhaustive-deps

  const judgeMutation = useMutation({
    mutationFn: ({
      judgment,
      event_date_override,
    }: {
      judgment: string;
      event_date_override?: string | null;
    }) =>
      api.post(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/${current!.id}/judge`,
        { judgment, event_date_override: event_date_override ?? null }
      ),
    onSuccess: () => {
      setShowDateOverride(false);
      setDateValue("");

      queryClient.invalidateQueries({
        queryKey: ["eval-metrics", projectId, sessionId],
      });
      queryClient.invalidateQueries({
        queryKey: ["eval-results", projectId, sessionId],
      });
      onRefresh();

      if (current && current.total_unreviewed <= 1) {
        setCompletionMessage(
          `All ${current.total_results} patients reviewed!`
        );
        setTimeout(() => setCompletionMessage(null), 3000);
      } else {
        setAfterId(current!.id);
        refetch();
      }
    },
  });

  const handleJudge = useCallback(
    (judgment: string) => {
      if (!current || judgeMutation.isPending) return;
      const event_date_override =
        showDateOverride && dateValue ? dateValue : null;
      judgeMutation.mutate({ judgment, event_date_override });
    },
    [current, judgeMutation, showDateOverride, dateValue]
  );

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      switch (e.key.toLowerCase()) {
        case "c":
          e.preventDefault();
          handleJudge("correct");
          break;
        case "w":
          e.preventDefault();
          handleJudge("wrong");
          break;
        case "s":
          e.preventDefault();
          handleJudge("skipped");
          break;
        case "e":
          e.preventDefault();
          setShowDateOverride((v) => !v);
          break;
        case "?":
          e.preventDefault();
          setShowShortcuts((v) => !v);
          break;
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleJudge]);

  if (completionMessage) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-16 dark:border-emerald-700 dark:bg-emerald-950/20">
        <Check className="mb-3 h-10 w-10 text-emerald-500" />
        <p className="text-lg font-medium text-foreground">{completionMessage}</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <div className="grid grid-cols-3 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="col-span-2 h-64" />
        </div>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-16 dark:border-emerald-700 dark:bg-emerald-950/20">
        <Check className="mb-3 h-10 w-10 text-emerald-500" />
        <p className="text-lg font-medium text-foreground">
          All patients reviewed
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Check the metrics panel to see evaluation results.
        </p>
      </div>
    );
  }

  const isPending = judgeMutation.isPending;
  const progressPct =
    current.total_results > 0
      ? Math.round(
          ((current.total_results - current.total_unreviewed) /
            current.total_results) *
            100
        )
      : 0;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-4">
        {showShortcuts && (
          <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />
        )}

        {/* Top bar */}
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 px-4 py-2.5">
          <span className="text-sm font-medium tabular-nums text-foreground">
            {current.total_results - current.total_unreviewed + 1} of{" "}
            {current.total_results}
          </span>
          <div className="mx-2 h-5 w-px bg-border" />
          <div className="flex-1">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {current.total_unreviewed} remaining
          </span>
          <div className="mx-1 h-5 w-px bg-border" />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setShowShortcuts((v) => !v)}
              >
                <HelpCircle className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Keyboard shortcuts (?)</TooltipContent>
          </Tooltip>
        </div>

        {/* Two-column layout */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
          {/* LEFT PANEL */}
          <div className="space-y-4">
            {/* Patient card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <User className="h-4 w-4" />
                Patient
              </div>
              <div className="font-mono text-lg font-semibold text-foreground">
                {noteContext?.patient_id_ext ?? current.patient_id.slice(0, 8)}
              </div>
              <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                <span>{current.notes_searched} notes searched</span>
                <span>&middot;</span>
                <span>{current.notes_matched} matched</span>
              </div>
            </div>

            {/* AI Prediction card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Brain className="h-4 w-4" />
                LLM Classification
              </div>

              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  {current.finding_label && (
                    <Badge
                      className={
                        LABEL_COLORS[current.finding_label] ?? "bg-zinc-500 text-white"
                      }
                    >
                      {current.finding_label === "positive"
                        ? "Event Detected"
                        : current.finding_label === "negative"
                          ? "No Event"
                          : "Inconclusive"}
                    </Badge>
                  )}
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {formatScore(current.predicted_score)} confidence
                  </span>
                </div>

                {current.event_date && (
                  <div className="flex items-center gap-2 text-sm">
                    <CalendarDays className="h-4 w-4 text-rose-500" />
                    <span className="text-foreground/80">
                      Event: {formatDate(current.event_date)}
                    </span>
                  </div>
                )}

                {current.finding_reasoning && (
                  <div className="rounded-md bg-muted/50 p-3">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      Reasoning
                    </div>
                    <p className="text-sm leading-relaxed text-foreground/80">
                      {current.finding_reasoning}
                    </p>
                  </div>
                )}

                {current.finding_evidence && current.finding_evidence.length > 0 && (
                  <div className="text-xs text-muted-foreground">
                    {current.finding_evidence.length} evidence note
                    {current.finding_evidence.length !== 1 ? "s" : ""} cited
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <Button
                onClick={() => handleJudge("correct")}
                disabled={isPending}
                className="w-full gap-2 bg-emerald-600 hover:bg-emerald-700"
                size="lg"
              >
                <Check className="h-4 w-4" />
                Correct
                <kbd className="ml-auto rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-xs">
                  C
                </kbd>
              </Button>

              <Button
                onClick={() => handleJudge("wrong")}
                disabled={isPending}
                variant="destructive"
                className="w-full gap-2"
                size="lg"
              >
                <X className="h-4 w-4" />
                Wrong
                <kbd className="ml-auto rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-xs">
                  W
                </kbd>
              </Button>

              <Button
                onClick={() => handleJudge("skipped")}
                disabled={isPending}
                variant="outline"
                className="w-full gap-2"
                size="lg"
              >
                <SkipForward className="h-4 w-4" />
                Skip
                <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 text-xs">
                  S
                </kbd>
              </Button>

              {!showDateOverride ? (
                <Button
                  variant="outline"
                  onClick={() => setShowDateOverride(true)}
                  disabled={isPending}
                  className="w-full gap-2"
                  size="lg"
                >
                  <CalendarDays className="h-4 w-4" />
                  Override Event Date
                  <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 text-xs">
                    E
                  </kbd>
                </Button>
              ) : (
                <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
                  <Label htmlFor="eval-date-override" className="text-sm text-foreground/70">
                    Corrected event date
                  </Label>
                  <Input
                    id="eval-date-override"
                    type="date"
                    className="text-sm"
                    value={dateValue}
                    onChange={(e) => setDateValue(e.target.value)}
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        setShowDateOverride(false);
                        setDateValue("");
                      }
                    }}
                  />
                  <p className="text-xs text-muted-foreground">
                    Set the correct date, then press Correct or Wrong above.
                  </p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-full"
                    onClick={() => {
                      setShowDateOverride(false);
                      setDateValue("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* RIGHT PANEL — Note viewer (one note at a time) */}
          <div className="rounded-lg border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
              <span className="text-sm font-medium text-foreground">
                Matched Notes
              </span>
              {sortedNotes.length > 0 && (
                <>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => setNoteIndex((i) => Math.max(0, i - 1))}
                      disabled={noteIndex === 0}
                      aria-label="Previous note"
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </Button>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {noteIndex + 1} / {sortedNotes.length}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() =>
                        setNoteIndex((i) =>
                          Math.min(sortedNotes.length - 1, i + 1)
                        )
                      }
                      disabled={noteIndex >= sortedNotes.length - 1}
                      aria-label="Next note"
                    >
                      <ChevronRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {sortedNotes[noteIndex]?.is_evidence && (
                    <Badge className="bg-primary/20 text-primary text-[10px] px-1.5 py-0">
                      Evidence
                    </Badge>
                  )}
                </>
              )}
            </div>
            <div className="h-[560px] overflow-y-auto">
              {notesLoading ? (
                <div className="space-y-2 p-4">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                  <Skeleton className="h-4 w-4/6" />
                </div>
              ) : sortedNotes.length > 0 ? (
                <EvalNoteViewer
                  note={sortedNotes[noteIndex]}
                  keywords={noteContext?.search_keywords ?? []}
                />
              ) : (
                <p className="p-4 text-sm text-muted-foreground">
                  Note context unavailable.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
