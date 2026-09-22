import type { FunnelStats } from "@/projects/types";

interface FunnelBarProps {
  stats: FunnelStats | null;
  isLoading: boolean;
  /** Saved queries no longer match the search these numbers came from. */
  stale?: boolean;
}

/**
 * The narrowing from cohort to positive patients, as one bar.
 *
 * Three side-by-side cards joined by arrows made every stage look equally
 * weighted, which hid the point: the search is what keeps the run affordable.
 * Nested fills on a single track show that proportion directly.
 */
export default function FunnelBar({ stats, isLoading, stale }: FunnelBarProps) {
  if (isLoading || !stats) {
    return (
      <div className="border-b border-border bg-card px-6 py-3">
        <p className="text-sm text-muted-foreground">Counting the sample…</p>
      </div>
    );
  }

  const sample = stats.sample_patients;
  const positive = stats.llm_positive;
  const hasLlm = positive !== null;
  const pct = (n: number) => (sample > 0 ? Math.min(100, (n / sample) * 100) : 0);

  return (
    <div className="sticky top-0 z-10 border-b border-border bg-card/95 px-6 py-3 backdrop-blur">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
          <Stage value={sample} label="patients in the sample" />
          <Stage
            value={stats.matched_patients}
            label={
              sample > 0
                ? `matched the search (${pct(stats.matched_patients).toFixed(0)}%)`
                : "matched the search"
            }
          />
          <Stage
            value={hasLlm ? positive! : null}
            label={hasLlm ? "called positive by the model" : "not classified yet"}
          />
        </div>
        {stats.estimated_cost !== null && (
          <span className="text-xs text-muted-foreground tabular-nums">
            Search skipped {stats.filter_percent.toFixed(0)}% of notes · about $
            {stats.estimated_cost.toFixed(2)} for this sample
          </span>
        )}
      </div>

      <div
        className={`relative mt-2 h-2 overflow-hidden rounded-full bg-muted ${
          stale ? "opacity-50" : ""
        }`}
      >
        <div
          className="absolute inset-y-0 left-0 bg-primary/30 transition-[width] duration-500"
          style={{ width: `${pct(stats.matched_patients)}%` }}
        />
        {hasLlm && (
          <div
            className="absolute inset-y-0 left-0 bg-primary transition-[width] duration-500"
            style={{ width: `${pct(positive!)}%` }}
          />
        )}
      </div>

      {stale && (
        <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-400">
          These counts are from the previous search. Run the search again to update
          them.
        </p>
      )}
    </div>
  );
}

function Stage({ value, label }: { value: number | null; label: string }) {
  return (
    <span className={value === null ? "text-muted-foreground" : ""}>
      <span className="text-lg font-semibold tabular-nums text-foreground">
        {value === null ? "—" : value.toLocaleString()}
      </span>{" "}
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
