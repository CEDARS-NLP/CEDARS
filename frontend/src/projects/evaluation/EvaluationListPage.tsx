// frontend/src/projects/evaluation/EvaluationListPage.tsx
import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { UnifiedSessionListItem } from "@/projects/types";
import { Plus, Copy, Trash2, Search, Sparkles, ArrowRight } from "lucide-react";

import NlpQueriesSection from "./NlpQueriesSection";
import { STATUS_STYLES, statusLabel } from "./sessionStatus";

type Mode = "search" | "llm";

export default function EvaluationListPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("search");

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ["eval-sessions", projectId],
    queryFn: () =>
      api.get<UnifiedSessionListItem[]>(
        `/projects/${projectId}/evaluation/sessions`
      ),
  });

  const { data: annotationStats } = useQuery({
    queryKey: ["annotation-stats", projectId],
    queryFn: () =>
      api.get<{ total: number }>(`/projects/${projectId}/annotations/stats`),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<UnifiedSessionListItem>(
        `/projects/${projectId}/evaluation/sessions`,
        { search_queries: [] }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
      navigate(`/projects/${projectId}/evaluation/${data.id}`);
    },
  });

  const discardMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.delete(`/projects/${projectId}/evaluation/sessions/${sessionId}`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] }),
  });

  const cloneMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.post<UnifiedSessionListItem>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/clone`
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["eval-sessions", projectId] });
      navigate(`/projects/${projectId}/evaluation/${data.id}`);
    },
  });

  const hasActive = sessions.some((s) =>
    ["draft", "reviewing"].includes(s.status)
  );
  const hasCommitted = sessions.some((s) => s.status === "committed");
  const annotationCount = annotationStats?.total ?? 0;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Find notes to review</h1>
        <p className="text-sm text-muted-foreground">
          Search every note with keyword queries, or test an LLM filter on a
          sample first and commit the version you trust.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ModeCard
          icon={<Search className="h-5 w-5" />}
          title="Run a search query"
          description="Match keywords across all notes with spaCy and send every hit straight to annotation. No model needed."
          selected={mode === "search"}
          onSelect={() => setMode("search")}
        />
        <ModeCard
          icon={<Sparkles className="h-5 w-5" />}
          title="Test an LLM filter first"
          description="Define an event, check the model against your own judgment on a small sample, then apply it across every patient."
          selected={mode === "llm"}
          onSelect={() => setMode("llm")}
        />
      </div>

      {mode === "search" ? (
        <div className="space-y-4">
          <NlpQueriesSection projectId={projectId!} />
          {annotationCount > 0 && (
            <Card>
              <CardContent className="flex items-center justify-between py-4">
                <p className="text-sm text-muted-foreground">
                  {annotationCount} matched annotation
                  {annotationCount === 1 ? "" : "s"} ready for review.
                </p>
                <Button asChild>
                  <Link to={`/projects/${projectId}/annotations`}>
                    Review annotations
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Evaluation sessions</h2>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={hasActive || hasCommitted || createMutation.isPending}
            >
              <Plus className="mr-2 h-4 w-4" />
              New session
            </Button>
          </div>

          {hasCommitted && (
            <div className="rounded-md border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
              A committed session is running on the full project. Cancel or finish it
              before starting another.
            </div>
          )}

          {isLoading ? (
            <p className="text-muted-foreground">Loading sessions...</p>
          ) : sessions.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-muted-foreground">
                No sessions yet. Start one to define an event and try it on a sample.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
          {sessions.map((s) => (
            <Card
              key={s.id}
              className="cursor-pointer transition-colors hover:bg-muted/50"
              onClick={() =>
                navigate(`/projects/${projectId}/evaluation/${s.id}`)
              }
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="flex items-center gap-3">
                  <CardTitle className="text-base">
                    {s.event_name || "Untitled session"}
                  </CardTitle>
                  <Badge className={STATUS_STYLES[s.status] ?? ""}>
                    {statusLabel(s.status)}
                  </Badge>
                </div>
                <div
                  className="flex gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {s.status !== "discarded" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => cloneMutation.mutate(s.id)}
                      disabled={hasActive || hasCommitted}
                      title="Clone to new session"
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  )}
                  {["draft", "reviewing"].includes(s.status) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => discardMutation.mutate(s.id)}
                      title="Discard session"
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex items-center gap-6 text-sm text-muted-foreground">
                <span>
                  {s.search_queries.length} quer
                  {s.search_queries.length === 1 ? "y" : "ies"}
                </span>
                <span>Sample: {s.sample_size} patients</span>
                {!!s.metrics?.total_reviewed && (
                  <span>
                    {s.metrics.total_reviewed} judged, F1{" "}
                    {(s.metrics.f1 * 100).toFixed(0)}%
                  </span>
                )}
                <span className="ml-auto">
                  {new Date(s.created_at).toLocaleDateString()}
                </span>
              </CardContent>
            </Card>
          ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ModeCard({
  icon,
  title,
  description,
  selected,
  onSelect,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`rounded-lg border p-4 text-left transition-colors ${
        selected
          ? "border-primary bg-primary/5"
          : "border-border hover:bg-muted/50"
      }`}
    >
      <div className="flex items-center gap-2 font-medium">
        {icon}
        {title}
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
    </button>
  );
}
