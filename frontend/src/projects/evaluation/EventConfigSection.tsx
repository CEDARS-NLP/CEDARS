import { useState, useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UnifiedSession } from "@/projects/types";
import { Play, Loader2 } from "lucide-react";

interface EventConfigSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

export default function EventConfigSection({ projectId, session, onRefresh }: EventConfigSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const [eventName, setEventName] = useState(session.event_name || "");
  const [eventDesc, setEventDesc] = useState(session.event_description || "");
  const [includeCriteria, setIncludeCriteria] = useState(session.include_criteria || "");
  const [excludeCriteria, setExcludeCriteria] = useState(session.exclude_criteria || "");

  const llmStatus = session.metrics?.llm_status;
  const llmRunning = llmStatus === "running";
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setEventName(session.event_name || "");
    setEventDesc(session.event_description || "");
    setIncludeCriteria(session.include_criteria || "");
    setExcludeCriteria(session.exclude_criteria || "");
  }, [session]);

  // Poll while LLM is running
  useEffect(() => {
    if (llmRunning) {
      pollRef.current = setInterval(() => {
        qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
        qc.invalidateQueries({ queryKey: ["funnel", projectId, session.id] });
      }, 3000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      // Final refresh when done
      qc.invalidateQueries({ queryKey: ["eval-results", projectId, session.id] });
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [llmRunning, projectId, session.id, qc]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/projects/${projectId}/evaluation/sessions/${session.id}/event-config`, {
        event_name: eventName,
        event_description: eventDesc,
        include_criteria: includeCriteria,
        exclude_criteria: excludeCriteria,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/evaluation/sessions/${session.id}/run-llm`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  const canRun = eventName.trim();

  const llmTotal = session.metrics?.llm_total ?? 0;
  const llmCompleted = (session.metrics?.llm_completed ?? 0) + (session.metrics?.llm_failed ?? 0);
  const progressText = llmRunning && llmTotal > 0
    ? `Classifying patients… ${llmCompleted}/${llmTotal}`
    : "Running LLM…";

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">Event definition</h2>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Event name</Label>
          <Input value={eventName} onChange={(e) => setEventName(e.target.value)} disabled={!isEditable} placeholder="e.g., Myocardial Infarction" />
        </div>
        <div className="space-y-2">
          <Label>Event description</Label>
          <textarea value={eventDesc} onChange={(e) => setEventDesc(e.target.value)} disabled={!isEditable} placeholder="Describe the clinical event..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Include criteria</Label>
          <textarea value={includeCriteria} onChange={(e) => setIncludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to look for..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Exclude criteria</Label>
          <textarea value={excludeCriteria} onChange={(e) => setExcludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to exclude..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
      </div>

      {isEditable && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || llmRunning}
          >
            Save config
          </Button>
          <Button
            onClick={() => {
              saveMutation.mutateAsync().then(() => runMutation.mutate());
            }}
            disabled={!canRun || runMutation.isPending || llmRunning}
          >
            {runMutation.isPending || llmRunning ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> {progressText}</>
            ) : (
              <><Play className="mr-2 h-4 w-4" /> Run LLM on sample</>
            )}
          </Button>
        </div>
      )}

      {llmRunning && llmTotal > 0 && (
        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${Math.round((llmCompleted / llmTotal) * 100)}%` }}
          />
        </div>
      )}

      {runMutation.isError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(runMutation.error as Error).message}
        </div>
      )}

      {llmStatus === "failed" && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          LLM classification failed. Check worker logs for details.
        </div>
      )}
    </div>
  );
}
