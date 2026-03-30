import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import type { UnifiedSession, FunnelStats } from "@/projects/types";
import FunnelBar from "./FunnelBar";
import SearchQueriesSection from "./SearchQueriesSection";
import LlmConfigSection from "./LlmConfigSection";
import ResultsSection from "./ResultsSection";
import MetricsPanel from "./MetricsPanel";
import CommitSection from "./CommitSection";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-500/20 text-yellow-400",
  reviewing: "bg-blue-500/20 text-blue-400",
  committed: "bg-purple-500/20 text-purple-400",
  completed: "bg-green-500/20 text-green-400",
  discarded: "bg-zinc-500/20 text-zinc-400",
};

export default function EvaluationSessionPage() {
  const { projectId, sessionId } = useParams<{ projectId: string; sessionId: string }>();
  const qc = useQueryClient();

  const { data: session, isLoading: sessionLoading } = useQuery({
    queryKey: ["eval-session", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedSession>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}`
      ),
  });

  const { data: funnel, isLoading: funnelLoading } = useQuery({
    queryKey: ["funnel", projectId, sessionId],
    queryFn: () =>
      api.get<FunnelStats>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/funnel`
      ),
    enabled: !!session,
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["eval-session", projectId, sessionId] });
    qc.invalidateQueries({ queryKey: ["funnel", projectId, sessionId] });
  }

  if (sessionLoading || !session) {
    return <p className="p-6 text-muted-foreground">Loading session...</p>;
  }

  const isReadOnly = ["committed", "completed", "discarded"].includes(session.status);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">
            {session.event_name || "Untitled Session"}
          </h1>
          <Badge className={STATUS_COLORS[session.status] ?? ""}>
            {session.status.toUpperCase()}
          </Badge>
        </div>
        {isReadOnly && (
          <span className="text-sm text-muted-foreground">Read-only</span>
        )}
      </div>

      {/* Pinned Funnel Bar */}
      <FunnelBar stats={funnel ?? null} isLoading={funnelLoading} />

      {/* Sections */}
      <div className="space-y-6 p-6">
        <SearchQueriesSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />

        <LlmConfigSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />

        {session.status !== "draft" && (
          <>
            <ResultsSection
              projectId={projectId!}
              sessionId={session.id}
              sessionStatus={session.status}
              onRefresh={refresh}
            />

            <MetricsPanel
              projectId={projectId!}
              sessionId={session.id}
            />
          </>
        )}

        <CommitSection
          projectId={projectId!}
          session={session}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}
