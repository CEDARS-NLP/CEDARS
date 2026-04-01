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
  reviewMode: boolean;
  onToggleReviewMode: () => void;
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
                    &ldquo;{e.text}&rdquo;
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

export default function ResultsSection({ projectId, sessionId, sessionStatus, onRefresh, reviewMode, onToggleReviewMode }: ResultsSectionProps) {
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

  const canJudge = sessionStatus === "reviewing";

  function handleJudged() {
    qc.invalidateQueries({ queryKey: ["eval-results", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["eval-metrics", projectId, sessionId] });
    onRefresh();
  }

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Patient Results</h2>
        <div className="flex items-center gap-3">
          {sessionStatus === "reviewing" && (
            <Button
              variant={reviewMode ? "default" : "outline"}
              size="sm"
              onClick={onToggleReviewMode}
            >
              {reviewMode ? "Show List" : "Start Review"}
            </Button>
          )}
          {!reviewMode && (
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
          )}
        </div>
      </div>

      {!reviewMode && (isLoading ? (
        <p className="text-sm text-muted-foreground">Loading results...</p>
      ) : !data || data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No results match the current filter.
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
      ))}
    </div>
  );
}
