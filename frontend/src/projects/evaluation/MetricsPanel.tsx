import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { UnifiedMetrics } from "@/projects/types";

interface MetricsPanelProps {
  projectId: string;
  sessionId: string;
}

/**
 * Agreement between the model and the reviewer, so far.
 *
 * No polling: every judgment invalidates this query, which is the only thing
 * that can change the numbers. The old 5-second interval was the single
 * chattiest request on the page.
 */
export default function MetricsPanel({ projectId, sessionId }: MetricsPanelProps) {
  const { data: metrics } = useQuery({
    queryKey: ["eval-metrics", projectId, sessionId],
    queryFn: () =>
      api.get<UnifiedMetrics>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/metrics`
      ),
  });

  if (!metrics || metrics.total_reviewed === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Judge a few patients and the model&rsquo;s accuracy against you appears
        here.
      </p>
    );
  }

  const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

  // Precision and F1 divide by the number of patients the model flagged. When
  // it flagged nobody they are undefined, and the backend's 0.0 placeholder read
  // as "the model is wrong every time" rather than "there is nothing to judge
  // it on yet".
  const flaggedAny = metrics.tp + metrics.fp > 0;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Accuracy" value={pct(metrics.accuracy)} />
        <Metric
          label="Precision"
          value={flaggedAny ? pct(metrics.precision) : "—"}
        />
        <Metric label="Recall" value={pct(metrics.recall)} />
        <Metric label="F1" value={flaggedAny ? pct(metrics.f1) : "—"} />
      </div>

      <p className="text-sm text-muted-foreground">
        Across {metrics.total_reviewed} judged{" "}
        {metrics.total_reviewed === 1 ? "patient" : "patients"}: {metrics.tp}{" "}
        correctly flagged, {metrics.fp} flagged in error, {metrics.fn} missed,{" "}
        {metrics.tn} correctly passed over.
        {metrics.total_pending > 0 && ` ${metrics.total_pending} left to judge.`}
      </p>

      {!flaggedAny && (
        <p className="max-w-prose text-sm text-amber-700 dark:text-amber-400">
          The model called no patient positive, so precision and F1 cannot be
          measured yet. If it should have flagged some of these, sharpen what
          counts as the event in step 1 and run the sample again.
        </p>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-muted/40 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}
