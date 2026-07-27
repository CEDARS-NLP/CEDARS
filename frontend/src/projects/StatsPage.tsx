import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";

interface ProjectStats {
  patients: { total: number; by_status: Record<string, number> };
  notes: { total: number };
  annotations: { total: number; reviewed: number; unreviewed: number };
  lemma_dist: Record<string, number>;
  user_review_stats: Record<string, number>;
  number_of_annotated_patients: number;
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function BarChart({
  data,
  suffix = "",
}: {
  data: [string, number][];
  suffix?: string;
}) {
  const max = Math.max(1, ...data.map(([, v]) => v));
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">No data yet.</p>;
  }
  return (
    <div className="space-y-2">
      {data.map(([label, value]) => (
        <div key={label} className="flex items-center gap-3">
          <div className="w-40 truncate text-right text-sm text-muted-foreground" title={label}>
            {label}
          </div>
          <div className="h-5 flex-1 rounded bg-muted">
            <div
              className="h-5 rounded bg-accent"
              style={{ width: `${(value / max) * 100}%` }}
            />
          </div>
          <div className="w-16 text-sm tabular-nums">
            {value}
            {suffix}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Statistics page — v2 port of stats.py / stats.html. Shows cohort counts,
 * the top-10 token (lemma) distribution, and per-reviewer patient counts.
 */
export default function StatsPage() {
  const { projectId } = useParams<{ projectId: string }>();

  const { data, isLoading, error } = useQuery<ProjectStats>({
    queryKey: ["project-stats-full", projectId],
    queryFn: () => api.get<ProjectStats>(`/projects/${projectId}/stats`),
    enabled: !!projectId,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <p className="text-sm text-destructive">
        {error instanceof Error ? error.message : "Failed to load statistics"}
      </p>
    );
  }

  const lemma = Object.entries(data.lemma_dist).sort((a, b) => b[1] - a[1]);
  const users = Object.entries(data.user_review_stats).sort((a, b) => b[1] - a[1]);
  const reviewed = data.patients.by_status["reviewed"] ?? 0;

  return (
    <div className="max-w-4xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Statistics</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Cohort overview for the current query.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Patients" value={data.patients.total} />
        <StatCard label="Annotated patients" value={data.number_of_annotated_patients} />
        <StatCard label="Reviewed patients" value={reviewed} />
        <StatCard label="Notes" value={data.notes.total} />
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium">Top tokens (lemma distribution)</h2>
        <BarChart data={lemma} suffix="%" />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium">Patients reviewed by user</h2>
        <BarChart data={users} />
      </section>
    </div>
  );
}
