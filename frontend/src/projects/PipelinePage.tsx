import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Brain,
  Search,
  BarChart3,
  ArrowRight,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Predictor, SearchQuery, NlpStats } from "@/projects/types";

export default function PipelinePage() {
  const { projectId } = useParams<{ projectId: string }>();

  const { data: predictors } = useQuery<Predictor[]>({
    queryKey: ["predictors", projectId],
    queryFn: () => api.get<Predictor[]>(`/projects/${projectId}/predictors`),
  });

  const { data: queries } = useQuery<SearchQuery[]>({
    queryKey: ["nlp-queries", projectId],
    queryFn: () => api.get<SearchQuery[]>(`/projects/${projectId}/nlp/queries`),
  });

  const { data: stats } = useQuery<NlpStats>({
    queryKey: ["nlp-stats", projectId],
    queryFn: () => api.get<NlpStats>(`/projects/${projectId}/nlp/stats`),
  });

  const activePredictor = predictors?.find((p) => p.is_active);

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="pipeline" projectId={projectId!} />

      <div>
        <h2 className="text-lg font-semibold text-foreground">Pipeline Status</h2>
        <p className="text-sm text-muted-foreground">
          Read-only overview of NLP queries and predictor configuration.{" "}
          <Link
            to={`/projects/${projectId}/evaluation`}
            className="inline-flex items-center gap-1 text-accent hover:underline"
          >
            Edit in Evaluation
            <ArrowRight className="h-3 w-3" />
          </Link>
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Active search queries */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Search className="h-4 w-4" />
              Search Queries
              {queries && (
                <span className="text-sm font-normal text-muted-foreground">
                  ({queries.length})
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {queries && queries.length > 0 ? (
              <div className="space-y-1.5">
                {queries.map((q) => (
                  <div
                    key={q.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                      {q.query}
                    </code>
                    {q.name && (
                      <span className="text-xs text-muted-foreground">({q.name})</span>
                    )}
                    {!q.is_active && (
                      <span className="text-xs text-muted-foreground">(inactive)</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No search queries configured.</p>
            )}
          </CardContent>
        </Card>

        {/* Active predictor */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Brain className="h-4 w-4" />
              Active Predictor
            </CardTitle>
          </CardHeader>
          <CardContent>
            {activePredictor ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{activePredictor.name}</span>
                  <span className="flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent dark:bg-accent/20">
                    <CheckCircle2 className="h-3 w-3" />
                    Active
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {activePredictor.predictor_type.toUpperCase()}
                  {activePredictor.predictor_type === "llm" &&
                    ` \u00b7 ${(activePredictor.config as Record<string, string>).provider || ""}/${(activePredictor.config as Record<string, string>).model || ""}`}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No active predictor.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* NLP stats */}
      {stats && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              NLP Statistics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-5">
              <div>
                <span className="text-muted-foreground">Total notes</span>
                <p className="font-medium">{stats.total_notes}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Processed</span>
                <p className="font-medium">{stats.processed_notes}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Sentences</span>
                <p className="font-medium">{stats.total_sentences}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Targets</span>
                <p className="font-medium text-emerald-600 dark:text-emerald-400">
                  {stats.target_sentences}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">Negated</span>
                <p className="font-medium">{stats.negated_sentences}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
