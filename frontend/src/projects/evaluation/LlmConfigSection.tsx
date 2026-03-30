import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UnifiedSession } from "@/projects/types";
import { Play, Loader2 } from "lucide-react";

interface LlmConfigSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "bedrock", label: "AWS Bedrock" },
];

export default function LlmConfigSection({ projectId, session, onRefresh }: LlmConfigSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const [eventName, setEventName] = useState(session.event_name || "");
  const [eventDesc, setEventDesc] = useState(session.event_description || "");
  const [includeCriteria, setIncludeCriteria] = useState(session.include_criteria || "");
  const [excludeCriteria, setExcludeCriteria] = useState(session.exclude_criteria || "");
  const [provider, setProvider] = useState(session.llm_provider || "openai");
  const [model, setModel] = useState(session.llm_model || "gpt-4o-mini");
  const [apiBase, setApiBase] = useState(session.llm_api_base || "");

  useEffect(() => {
    setEventName(session.event_name || "");
    setEventDesc(session.event_description || "");
    setIncludeCriteria(session.include_criteria || "");
    setExcludeCriteria(session.exclude_criteria || "");
    setProvider(session.llm_provider || "openai");
    setModel(session.llm_model || "gpt-4o-mini");
    setApiBase(session.llm_api_base || "");
  }, [session]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/projects/${projectId}/evaluation/sessions/${session.id}/llm-config`, {
        event_name: eventName,
        event_description: eventDesc,
        include_criteria: includeCriteria,
        exclude_criteria: excludeCriteria,
        llm_provider: provider,
        llm_model: model,
        llm_api_base: apiBase || null,
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
      qc.invalidateQueries({ queryKey: ["funnel", projectId, session.id] });
      qc.invalidateQueries({ queryKey: ["eval-results", projectId, session.id] });
      onRefresh();
    },
  });

  const canRun = eventName.trim() && provider && model;

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">LLM Classification</h2>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Event Name</Label>
          <Input value={eventName} onChange={(e) => setEventName(e.target.value)} disabled={!isEditable} placeholder="e.g., Myocardial Infarction" />
        </div>
        <div className="space-y-2">
          <Label>Event Description</Label>
          <textarea value={eventDesc} onChange={(e) => setEventDesc(e.target.value)} disabled={!isEditable} placeholder="Describe the clinical event..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Include Criteria</Label>
          <textarea value={includeCriteria} onChange={(e) => setIncludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to look for..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
        <div className="space-y-2">
          <Label>Exclude Criteria</Label>
          <textarea value={excludeCriteria} onChange={(e) => setExcludeCriteria(e.target.value)} disabled={!isEditable} placeholder="What to exclude..." className="flex w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2">
          <Label>LLM Provider</Label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={!isEditable} className="flex w-full rounded-md border bg-background px-3 py-2 text-sm">
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label>Model</Label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} disabled={!isEditable} placeholder="gpt-4o-mini" />
        </div>
        <div className="space-y-2">
          <Label>API Base (optional)</Label>
          <Input value={apiBase} onChange={(e) => setApiBase(e.target.value)} disabled={!isEditable} placeholder="http://localhost:11434" />
        </div>
      </div>

      {isEditable && (
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            Save Config
          </Button>
          <Button
            onClick={() => {
              saveMutation.mutateAsync().then(() => runMutation.mutate());
            }}
            disabled={!canRun || runMutation.isPending}
          >
            {runMutation.isPending ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Running LLM...</>
            ) : (
              <><Play className="mr-2 h-4 w-4" /> Run LLM on Sample</>
            )}
          </Button>
        </div>
      )}

      {runMutation.isError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(runMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
