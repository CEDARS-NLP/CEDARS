import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";

interface Stats {
  number_of_patients: number;
  number_of_annotated_patients: number;
  number_of_reviewed: number;
  lemma_dist: Record<string, number>;
  user_review_stats: Record<string, number>;
}

interface NlpStatus {
  total_patients: number;
  tasks_in_progress: number;
  tasks_completed: number;
  tasks_failed: number;
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="py-5">
        <p className="text-3xl font-semibold text-foreground">{value}</p>
        <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  );
}

function BarChart({
  data,
  title,
  suffix = "",
}: {
  data: Record<string, number>;
  title: string;
  suffix?: string;
}) {
  const entries = Object.entries(data);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No data yet.</p>
        ) : (
          entries.map(([k, v]) => (
            <div key={k} className="flex items-center gap-3 text-sm">
              <span className="w-36 truncate font-mono text-xs" title={k}>
                {k}
              </span>
              <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
                <div
                  className="h-full rounded bg-primary"
                  style={{ width: `${(v / max) * 100}%` }}
                />
              </div>
              <span className="w-12 text-right text-xs text-muted-foreground">
                {v}
                {suffix}
              </span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** Cohort statistics (ports stats.html). */
export default function StatsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data, isLoading } = useQuery<Stats>({
    queryKey: ["stats", projectId],
    queryFn: () => api.get<Stats>(`/projects/${projectId}/stats`),
    enabled: !!projectId,
    refetchInterval: 10000,
  });
  const { data: nlpStatus } = useQuery<NlpStatus>({
    queryKey: ["nlp-status", projectId],
    queryFn: () => api.get<NlpStatus>(`/projects/${projectId}/nlp/status`),
    enabled: !!projectId,
    refetchInterval: 4000,
  });

  const total = nlpStatus?.total_patients ?? 0;
  const completed = nlpStatus?.tasks_completed ?? 0;
  const inProgress = nlpStatus?.tasks_in_progress ?? 0;
  const failed = nlpStatus?.tasks_failed ?? 0;
  const processingPct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Statistics</h1>
        <p className="text-sm text-muted-foreground">
          Overview of the cohort and review progress.
        </p>
      </div>

      {isLoading || !data ? (
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Patients" value={data.number_of_patients} />
            <StatCard
              label="Unreviewed patients"
              value={data.number_of_patients - data.number_of_reviewed}
            />
            <StatCard label="Reviewed patients" value={data.number_of_reviewed} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <BarChart
              data={data.lemma_dist}
              title="Top keyword distribution"
              suffix="%"
            />
            <BarChart data={data.user_review_stats} title="Reviews per user" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Processing status</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Progress value={processingPct} />
              <div className="grid grid-cols-2 gap-4 text-center sm:grid-cols-4">
                <div>
                  <p className="text-2xl font-semibold text-foreground">{total}</p>
                  <p className="text-xs text-muted-foreground">Patients</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold text-foreground">{inProgress}</p>
                  <p className="text-xs text-muted-foreground">In progress</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold text-foreground">{completed}</p>
                  <p className="text-xs text-muted-foreground">Completed</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold text-foreground">{failed}</p>
                  <p className="text-xs text-muted-foreground">Failed</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
