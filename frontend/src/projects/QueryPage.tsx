import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Search, ArrowRight } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface SaveQueryResponse {
  changed: boolean;
  dispatched_patients: number;
  mode: string;
  job_id: string | null;
}

interface ActiveQuery {
  query: string;
  hide_duplicates: boolean;
  skip_after_event: boolean;
  use_negation: boolean;
  nlp_apply: boolean;
}

/**
 * Search query page — v2 port of ops.py `upload_query`.
 * Enter a CEDARS keyword query, then dispatch NLP processing.
 */
export default function QueryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [hideDuplicates, setHideDuplicates] = useState(true);
  const [skipAfterEvent, setSkipAfterEvent] = useState(true);
  const [useNegation, setUseNegation] = useState(false);
  const [nlpApply, setNlpApply] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Pre-populate from the active query, if any.
  const { data: active } = useQuery<ActiveQuery | null>({
    queryKey: ["workflow-query", projectId],
    queryFn: () => api.get<ActiveQuery | null>(`/projects/${projectId}/workflow/query`).catch(() => null),
    enabled: !!projectId,
  });

  useEffect(() => {
    if (active) {
      setQuery(active.query ?? "");
      setHideDuplicates(active.hide_duplicates ?? true);
      setSkipAfterEvent(active.skip_after_event ?? true);
      setUseNegation(active.use_negation ?? false);
      setNlpApply(active.nlp_apply ?? false);
    }
  }, [active]);

  const mutation = useMutation({
    mutationFn: () =>
      api.put<SaveQueryResponse>(`/projects/${projectId}/workflow/query`, {
        query,
        hide_duplicates: hideDuplicates,
        skip_after_event: skipAfterEvent,
        use_negation: useNegation,
        nlp_apply: nlpApply,
      }),
    onSuccess: (res) => {
      setMessage(
        `Query saved. ${res.dispatched_patients} patient(s) dispatched for NLP (${res.mode}).`
      );
      navigate(`/projects/${projectId}/process`);
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Failed to save query"),
  });

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Search query</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Define the keyword query used to find candidate sentences. Saving a new
          query clears existing annotations and re-runs NLP.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="space-y-6 rounded-lg border border-border bg-card p-6"
      >
        <div className="space-y-2">
          <Label htmlFor="query">Query</Label>
          <Input
            id="query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="(DVT OR embolus) AND !suspected"
            required
          />
          <p className="text-xs text-muted-foreground">
            Use <code>OR</code>, <code>AND</code>, <code>!</code> for negation, and
            <code>*</code>/<code>?</code> wildcards.
          </p>
        </div>

        <div className="grid gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={hideDuplicates}
              onChange={(e) => setHideDuplicates(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Hide duplicate sentences
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={skipAfterEvent}
              onChange={(e) => setSkipAfterEvent(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Skip annotations after an event date is marked
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={useNegation}
              onChange={(e) => setUseNegation(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Surface negated matches
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={nlpApply}
              onChange={(e) => setNlpApply(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Apply the active predictor (PINES/LLM) after NLP
          </label>
        </div>

        {message && <p className="text-sm text-muted-foreground">{message}</p>}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={mutation.isPending || !query.trim()}>
            <Search className="mr-2 h-4 w-4" />
            {mutation.isPending ? "Saving..." : "Save query & run NLP"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate(`/projects/${projectId}/process`)}
          >
            Go to processing
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </form>
    </div>
  );
}
