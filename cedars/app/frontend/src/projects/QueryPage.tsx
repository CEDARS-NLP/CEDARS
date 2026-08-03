import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";

interface QueryData {
  query: string;
  nlp_apply: boolean;
  hide_duplicates: boolean;
  skip_after_event: boolean;
  exclude_negated: boolean;
}

interface SaveResponse {
  new_query: boolean;
  dispatched: number;
  message: string;
}

/** Define the CEDARS search query and dispatch NLP processing. */
export default function QueryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [nlpApply, setNlpApply] = useState(false);
  const [hideDuplicates, setHideDuplicates] = useState(true);
  const [skipAfterEvent, setSkipAfterEvent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { data } = useQuery<QueryData>({
    queryKey: ["query", projectId],
    queryFn: () => api.get<QueryData>(`/projects/${projectId}/query`),
    enabled: !!projectId,
  });

  useEffect(() => {
    if (data) {
      setQuery(data.query ?? "");
      setNlpApply(data.nlp_apply);
      setHideDuplicates(data.hide_duplicates);
      setSkipAfterEvent(data.skip_after_event);
    }
  }, [data]);

  async function handleSave() {
    setError("");
    setSaving(true);
    try {
      await api.put<SaveResponse>(`/projects/${projectId}/query`, {
        query,
        nlp_apply: nlpApply,
        hide_duplicates: hideDuplicates,
        skip_after_event: skipAfterEvent,
      });
      navigate(`/projects/${projectId}/process`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save query");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Search query</h1>
        <p className="text-sm text-muted-foreground">
          Define keywords to detect. Saving the query resets existing annotations
          and re-runs NLP processing.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Query</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="query">Keywords</Label>
            <textarea
              id="query"
              rows={4}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. (cancer AND metastatic) OR embolism"
              className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Syntax: <span className="font-mono">OR</span>,{" "}
              <span className="font-mono">AND</span>, wildcards{" "}
              <span className="font-mono">*</span> /{" "}
              <span className="font-mono">?</span>, and parentheses for grouping.
            </p>
          </div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={hideDuplicates}
                onChange={(e) => setHideDuplicates(e.target.checked)}
              />
              Hide duplicate sentences
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={skipAfterEvent}
                onChange={(e) => setSkipAfterEvent(e.target.checked)}
              />
              Skip annotations after a recorded event date
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={nlpApply}
                onChange={(e) => setNlpApply(e.target.checked)}
              />
              Apply PINES model (NLP classification)
            </label>
          </div>

          <Button onClick={handleSave} disabled={saving || !query.trim()}>
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving &amp; dispatching...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Save &amp; run NLP
              </>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
