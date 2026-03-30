import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { UnifiedMetrics } from "@/projects/types";

interface MetricsPanelProps {
  projectId: string;
  sessionId: string;
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex-1 rounded-lg bg-muted/50 p-3 text-center">
      <div className="text-xs font-medium uppercase text-muted-foreground">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

export default function MetricsPanel({ projectId, sessionId }: MetricsPanelProps) {
  const { data: metrics } = useQuery({
    queryKey: ["eval-metrics", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedMetrics>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/metrics`
      ),
    refetchInterval: 5000,
  });

  if (!metrics || metrics.total_reviewed === 0) {
    return (
      <div className="rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Metrics</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Review patient results to see live metrics.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <h2 className="text-lg font-semibold">Live Metrics</h2>
      <div className="flex gap-3">
        <MetricCard label="Accuracy" value={`${(metrics.accuracy * 100).toFixed(1)}%`} color="text-green-400" />
        <MetricCard label="Precision" value={`${(metrics.precision * 100).toFixed(1)}%`} color="text-blue-400" />
        <MetricCard label="Recall" value={`${(metrics.recall * 100).toFixed(1)}%`} color="text-blue-400" />
        <MetricCard label="F1 Score" value={`${(metrics.f1 * 100).toFixed(1)}%`} color="text-yellow-400" />
      </div>
      <div className="text-center text-xs text-muted-foreground">
        Based on {metrics.total_reviewed} reviewed patients ({metrics.total_pending} remaining)
      </div>
    </div>
  );
}
