import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import type { UnifiedSession, FunnelStats } from "@/projects/types";
import FunnelBar from "./FunnelBar";
import StepCard, { type StepState } from "./StepCard";
import EventDefinitionSection from "./EventDefinitionSection";
import SearchQueriesSection from "./SearchQueriesSection";
import SampleRunSection from "./SampleRunSection";
import ResultsSection from "./ResultsSection";
import MetricsPanel from "./MetricsPanel";
import CommitSection from "./CommitSection";
import PipelineSection from "./PipelineSection";
import EvalReviewPanel from "./EvalReviewPanel";

import { STATUS_STYLES, statusLabel } from "./sessionStatus";

/** No step index — used to mean "everything collapsed". */
const NO_STEP = 0;

/**
 * One evaluation session, as five steps.
 *
 * The page used to render seven peer sections top to bottom, in an order that
 * contradicted the dependencies between them: search queries above the event
 * definition they are derived from, review hidden behind a toggle below the
 * result list, commit visible before there was anything to commit. Each step now
 * states what it holds, opens one at a time, and says why it is not ready yet.
 */
export default function EvaluationSessionPage() {
  const { projectId, sessionId } = useParams<{ projectId: string; sessionId: string }>();
  const qc = useQueryClient();

  // Cleared by a successful search, set by saving queries: the funnel counts and
  // note previews describe the previous search until it runs again.
  const [searchStale, setSearchStale] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);

  const { data: session, isLoading: sessionLoading } = useQuery({
    queryKey: ["eval-session", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedSession>(`/projects/${projectId}/evaluation/sessions/${sessionId}`),
    // The only thing that changes on its own is a classification run in progress.
    refetchInterval: (query) =>
      (query.state.data as UnifiedSession | undefined)?.metrics?.llm_status ===
      "running"
        ? 3000
        : false,
  });

  const llmRunning = session?.metrics?.llm_status === "running";

  const { data: funnel, isLoading: funnelLoading } = useQuery({
    queryKey: ["funnel", projectId, sessionId],
    queryFn: () =>
      api.get<FunnelStats>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/funnel`
      ),
    enabled: !!session,
    refetchInterval: llmRunning ? 3000 : false,
  });

  // When a classification run ends, the results and metrics are new.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !llmRunning) {
      qc.invalidateQueries({ queryKey: ["eval-results", projectId, sessionId] });
      qc.invalidateQueries({ queryKey: ["eval-metrics", projectId, sessionId] });
      qc.invalidateQueries({ queryKey: ["eval-next-result", projectId, sessionId] });
    }
    wasRunning.current = !!llmRunning;
  }, [llmRunning, projectId, sessionId, qc]);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["eval-session", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["funnel", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
  }

  if (sessionLoading || !session) {
    return <p className="p-6 text-muted-foreground">Loading session…</p>;
  }

  const metrics = session.metrics;
  const isReadOnly = ["committed", "completed", "discarded"].includes(session.status);

  const hasEvent = !!session.event_name?.trim();
  const queryCount = session.search_queries.length;
  const searched = (funnel?.matched_notes ?? 0) > 0;
  const classified =
    metrics?.llm_status === "completed" || (metrics?.llm_completed ?? 0) > 0;
  const reviewed = metrics?.total_reviewed ?? 0;
  const pending = metrics?.total_pending ?? 0;
  const committed = ["committed", "completed"].includes(session.status);

  const current = !hasEvent
    ? 1
    : !searched
    ? 2
    : !classified
    ? 3
    : committed
    ? 5
    : reviewed === 0 || pending > 0
    ? 4
    : 5;

  const open = openStep ?? current;
  const toggle = (index: number) => setOpenStep(open === index ? NO_STEP : index);

  function stateFor(index: number, done: boolean, locked = false): StepState {
    if (locked) return "locked";
    if (done) return "done";
    return index === current ? "current" : "todo";
  }

  const matchSummary = funnel
    ? `${funnel.matched_patients} of ${funnel.sample_patients} sample patients matched`
    : "not run yet";

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">
            {session.event_name || "Untitled session"}
          </h1>
          <Badge className={STATUS_STYLES[session.status] ?? ""}>
            {statusLabel(session.status)}
          </Badge>
        </div>
        {isReadOnly && (
          <span className="text-sm text-muted-foreground">
            Locked — clone the session to change anything
          </span>
        )}
      </div>

      <FunnelBar stats={funnel ?? null} isLoading={funnelLoading} stale={searchStale} />

      <div className="space-y-3 p-6">
        <StepCard
          index={1}
          title="Define the event"
          state={stateFor(1, hasEvent)}
          summary={
            hasEvent
              ? session.event_description || session.event_name!
              : "Not defined yet"
          }
          open={open === 1}
          onToggle={() => toggle(1)}
        >
          <EventDefinitionSection
            projectId={projectId!}
            session={session}
            onRefresh={refresh}
            onSaved={() => setOpenStep(2)}
          />
        </StepCard>

        <StepCard
          index={2}
          title="Find the notes worth reading"
          state={stateFor(2, searched && !searchStale, !hasEvent)}
          lockedReason="Define the event first — queries are built from it."
          summary={
            queryCount === 0
              ? "No queries yet"
              : `${queryCount} ${queryCount === 1 ? "query" : "queries"} · ${matchSummary}`
          }
          open={open === 2}
          onToggle={() => toggle(2)}
        >
          <SearchQueriesSection
            projectId={projectId!}
            session={session}
            onRefresh={refresh}
            searchStale={searchStale}
            onQueriesSaved={() => setSearchStale(true)}
            onSearchRun={() => setSearchStale(false)}
            matchedPatients={funnel?.matched_patients ?? null}
          />
        </StepCard>

        <StepCard
          index={3}
          title="Test the model on a sample"
          state={stateFor(3, classified, !searched)}
          lockedReason="Run the search first so there is something to classify."
          summary={
            llmRunning
              ? `Classifying ${metrics?.llm_completed ?? 0} of ${metrics?.llm_total ?? 0}…`
              : classified
              ? `${metrics?.llm_completed ?? 0} patients classified${
                  (metrics?.llm_failed ?? 0) > 0 ? `, ${metrics!.llm_failed} failed` : ""
                }`
              : "Not run yet"
          }
          open={open === 3}
          onToggle={() => toggle(3)}
        >
          <SampleRunSection
            projectId={projectId!}
            session={session}
            funnel={funnel ?? null}
            searchStale={searchStale}
            onRefresh={refresh}
          />
        </StepCard>

        <StepCard
          index={4}
          title="Check the model against yourself"
          state={stateFor(4, reviewed > 0 && pending === 0, !classified)}
          lockedReason="Run the model on the sample first."
          summary={
            reviewed === 0
              ? "No patients judged yet"
              : `${reviewed} judged · ${((metrics?.accuracy ?? 0) * 100).toFixed(
                  0
                )}% agreement${pending > 0 ? ` · ${pending} left` : ""}`
          }
          open={open === 4}
          onToggle={() => toggle(4)}
        >
          <div className="space-y-5">
            <MetricsPanel projectId={projectId!} sessionId={session.id} />

            {session.status === "reviewing" ? (
              <EvalReviewPanel
                projectId={projectId!}
                sessionId={session.id}
                onRefresh={refresh}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                This session is locked, so judgments can no longer change.
              </p>
            )}

            <details className="group">
              <summary className="cursor-pointer select-none text-sm text-muted-foreground hover:text-foreground">
                Browse every patient in the sample
              </summary>
              <div className="mt-3">
                <ResultsSection
                  projectId={projectId!}
                  sessionId={session.id}
                  sessionStatus={session.status}
                  onRefresh={refresh}
                />
              </div>
            </details>
          </div>
        </StepCard>

        <StepCard
          index={5}
          title="Run it on everyone"
          state={stateFor(5, session.status === "completed", !classified)}
          lockedReason="Test the model on the sample first."
          summary={
            committed
              ? `Committed ${
                  session.committed_at
                    ? new Date(session.committed_at).toLocaleDateString()
                    : ""
                }`.trim()
              : "Not committed"
          }
          open={open === 5}
          onToggle={() => toggle(5)}
        >
          {committed ? (
            <PipelineSection
              projectId={projectId!}
              sessionId={session.id}
              sessionStatus={session.status}
              onRefresh={refresh}
            />
          ) : session.status === "reviewing" ? (
            <CommitSection
              projectId={projectId!}
              session={session}
              onRefresh={refresh}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              This session was discarded. Clone it to start again.
            </p>
          )}
        </StepCard>
      </div>
    </div>
  );
}
