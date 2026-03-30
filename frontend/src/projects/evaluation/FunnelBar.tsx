// frontend/src/projects/evaluation/FunnelBar.tsx
import type { FunnelStats } from "@/projects/types";

interface FunnelBarProps {
  stats: FunnelStats | null;
  isLoading: boolean;
}

export default function FunnelBar({ stats, isLoading }: FunnelBarProps) {
  if (isLoading || !stats) {
    return (
      <div className="sticky top-0 z-10 border-b bg-card p-4">
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          Loading funnel stats...
        </div>
      </div>
    );
  }

  const hasLlm = stats.llm_positive !== null;

  return (
    <div className="sticky top-0 z-10 border-b bg-card p-4">
      <div className="flex items-center gap-2">
        {/* Sample */}
        <div className="flex-1 rounded-lg border bg-muted/50 p-3 text-center">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            Sample
          </div>
          <div className="text-xl font-bold">{stats.sample_patients} pts</div>
          <div className="text-xs text-muted-foreground">
            {stats.sample_notes} notes
          </div>
        </div>

        <div className="text-muted-foreground">→</div>

        {/* Search Match */}
        <div className="flex-1 rounded-lg border bg-muted/50 p-3 text-center">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            Search Match
          </div>
          <div className="text-xl font-bold">
            {stats.matched_patients} pts
          </div>
          <div className="text-xs text-muted-foreground">
            {stats.filter_percent.toFixed(0)}% filtered
          </div>
        </div>

        <div className="text-muted-foreground">→</div>

        {/* LLM Positive */}
        <div
          className={`flex-1 rounded-lg border p-3 text-center ${
            hasLlm ? "bg-muted/50" : "bg-muted/20 opacity-50"
          }`}
        >
          <div className="text-xs font-medium uppercase text-muted-foreground">
            LLM Positive
          </div>
          <div className="text-xl font-bold">
            {hasLlm ? `${stats.llm_positive} pts` : "—"}
          </div>
          <div className="text-xs text-muted-foreground">
            {hasLlm && stats.matched_patients > 0
              ? `${((stats.llm_positive! / stats.matched_patients) * 100).toFixed(0)}% of match`
              : "Run LLM first"}
          </div>
        </div>
      </div>

      {stats.estimated_cost !== null && (
        <div className="mt-2 text-center text-xs text-muted-foreground">
          {stats.filter_percent.toFixed(0)}% of notes filtered by search —
          est. LLM cost: ~${stats.estimated_cost.toFixed(2)}
        </div>
      )}
    </div>
  );
}
