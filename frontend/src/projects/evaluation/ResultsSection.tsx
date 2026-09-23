import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type { PatientResultsPage, PatientResultItem } from "@/projects/types";
import { Check, X, ChevronDown, ChevronRight } from "lucide-react";

interface ResultsSectionProps {
  projectId: string;
  sessionId: string;
  sessionStatus: string;
  onRefresh: () => void;
}

/** Readable in both themes — the old values were tuned for dark only. */
const LABEL_COLORS: Record<string, string> = {
  positive: "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300",
  negative: "bg-destructive/15 text-destructive",
  inconclusive: "bg-amber-500/20 text-amber-700 dark:text-amber-300",
  no_match: "bg-muted text-muted-foreground",
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
  const [expanded, setExpanded] = useState(false);
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
    <div className="rounded-md border border-border bg-card">
      <button
        type="button"
        className="flex w-full items-center gap-3 p-3 text-left"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="font-mono text-sm">{result.patient_id}</span>
        {result.finding_label && (
          <Badge className={LABEL_COLORS[result.finding_label] ?? ""}>
            {result.finding_label.replace("_", " ")}
          </Badge>
        )}
        {result.predicted_score !== null && (
          <span className="text-xs text-muted-foreground tabular-nums">
            {(result.predicted_score * 100).toFixed(0)}% likely
          </span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {isReviewed
            ? `You judged this ${result.review_judgment}`
            : canJudge
            ? "Not judged"
            : ""}
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border p-3">
          {result.finding_reasoning && (
            <div className="rounded-md bg-muted/50 p-3 text-sm leading-relaxed">
              {result.finding_reasoning}
            </div>
          )}

          {result.finding_evidence && result.finding_evidence.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs text-muted-foreground">
                Evidence from {result.finding_evidence.length}{" "}
                {result.finding_evidence.length === 1 ? "note" : "notes"}
              </div>
              {result.finding_evidence.map((e, i) => (
                <blockquote
                  key={i}
                  className="border-l-2 border-primary/60 bg-muted/30 p-2 text-sm"
                >
                  <span className="text-xs text-muted-foreground">{e.note_date}</span>
                  <br />
                  {e.text}
                </blockquote>
              ))}
            </div>
          )}

          {canJudge && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                Event date
                <Input
                  type="date"
                  value={dateOverride}
                  onChange={(e) => setDateOverride(e.target.value)}
                  className="w-40"
                />
              </label>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => judgeMutation.mutate("correct")}
                  disabled={judgeMutation.isPending}
                >
                  <Check className="mr-1 h-4 w-4" /> Model was right
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => judgeMutation.mutate("wrong")}
                  disabled={judgeMutation.isPending}
                >
                  <X className="mr-1 h-4 w-4" /> Model was wrong
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => judgeMutation.mutate("skipped")}
                  disabled={judgeMutation.isPending}
                >
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

/**
 * The full result list — a browser, not the review queue.
 *
 * Judging one patient at a time happens in EvalReviewPanel; this view exists for
 * looking something up, spot-checking a label, or changing one decision.
 */
export default function ResultsSection({
  projectId,
  sessionId,
  sessionStatus,
  onRefresh,
}: ResultsSectionProps) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("all");
  const [page, setPage] = useState(1);

  const labelFilter = activeTab === "all" || activeTab === "unreviewed" ? undefined : activeTab;
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

  const canJudge = sessionStatus === "reviewing";

  function handleJudged() {
    qc.invalidateQueries({ queryKey: ["eval-results", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["eval-metrics", projectId, sessionId] });
    onRefresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">
          {data ? `${data.total} patients` : "Loading…"}
        </span>
        <div className="flex gap-1 rounded-md bg-muted p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => {
                setActiveTab(tab);
                setPage(1);
              }}
              className={`rounded-sm px-3 py-1 text-xs capitalize transition-colors ${
                activeTab === tab
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading results…</p>
      ) : !data || data.results.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          {activeTab === "all"
            ? "No results yet."
            : `No ${activeTab} patients in this sample.`}
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
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-muted-foreground tabular-nums">
                Page {page} of {data.total_pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= data.total_pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
