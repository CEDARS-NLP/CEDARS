import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { formatCost, formatTokens } from "@/lib/cost";
import type { LlmUsageGroup, LlmUsageReport } from "@/projects/types";

const SOURCE_LABELS: Record<string, string> = {
  evaluation_sample: "Evaluation sample runs",
  pipeline_run: "Full runs on all patients",
  bulk_prediction: "Annotation predictions",
  predictor_test: "Predictor tests",
  query_suggestion: "Query suggestions",
  pattern_generation: "Pattern generation",
};

const WINDOWS = [7, 30, 90];

function UsageTable({ title, rows, label }: {
  title: string;
  rows: LlmUsageGroup[];
  label: (key: string) => string;
}) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <table className="w-full text-sm">
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border first:border-t-0">
              <td className="py-1.5 pr-3">{label(r.key)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                {formatTokens(r.prompt_tokens + r.completion_tokens)} tokens
              </td>
              <td className="py-1.5 text-right tabular-nums">
                {r.estimated_cost != null ? formatCost(r.estimated_cost) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Everything this project has spent on language models, from the usage ledger.
 *
 * Admin-only on the server; for other roles the request 403s and the panel
 * simply does not render.
 */
export default function LlmUsagePanel({ projectId }: { projectId: string }) {
  const [days, setDays] = useState(30);
  const { data } = useQuery({
    queryKey: ["llm-usage", projectId, days],
    queryFn: () => api.get<LlmUsageReport>(`/projects/${projectId}/llm-usage?days=${days}`),
    retry: false,
  });

  if (!data) return null;
  const { totals } = data;

  return (
    <section className="rounded-lg border border-border bg-card px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium">LLM usage</h3>
          <p className="text-xs text-muted-foreground">
            Tokens are the units models bill by (about ¾ of a word each). Costs are
            estimates at list price when each call ran.
          </p>
        </div>
        <div role="group" aria-label="Time window" className="flex gap-1 text-xs">
          {WINDOWS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              aria-pressed={days === d}
              className={`rounded-md border px-2 py-1 ${
                days === d
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {d} days
            </button>
          ))}
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted-foreground">Estimated cost</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            {totals.estimated_cost != null ? formatCost(totals.estimated_cost) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Tokens read</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            {formatTokens(totals.prompt_tokens)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Tokens written</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            {formatTokens(totals.completion_tokens)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Model calls</dt>
          <dd className="text-2xl font-semibold tabular-nums">{totals.calls}</dd>
        </div>
      </dl>

      {totals.calls === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          No model calls in the last {days} days.
        </p>
      ) : (
        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <UsageTable
            title="By activity"
            rows={data.by_source}
            label={(k) => SOURCE_LABELS[k] ?? k}
          />
          <UsageTable title="By model" rows={data.by_model} label={(k) => k} />
        </div>
      )}
      {totals.unpriced_calls > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {totals.unpriced_calls} call{totals.unpriced_calls === 1 ? "" : "s"} used a model
          with no per-token price (for example a local model) and are counted in tokens
          but not in cost.
        </p>
      )}
    </section>
  );
}
