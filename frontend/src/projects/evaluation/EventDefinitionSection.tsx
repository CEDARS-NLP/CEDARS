import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UnifiedSession } from "@/projects/types";
import { ArrowRight, Loader2 } from "lucide-react";

interface EventDefinitionSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
  /** Called after a successful save so the page can advance to the next step. */
  onSaved: () => void;
}

interface Definition {
  event_name: string;
  event_description: string;
  include_criteria: string;
  exclude_criteria: string;
}

const FIELD_CLASS =
  "flex w-full rounded-md border bg-background px-3 py-2 text-sm disabled:opacity-60";

/**
 * Step 1 — what counts as the event.
 *
 * This is deliberately first: the search queries in step 2 are generated from
 * these words, and the LLM in step 3 is prompted with them. Previously it sat
 * below the search queries, which is why the query suggester asked the user to
 * re-type a description they had already written here.
 */
export default function EventDefinitionSection({
  projectId,
  session,
  onRefresh,
  onSaved,
}: EventDefinitionSectionProps) {
  const qc = useQueryClient();
  const isEditable = ["draft", "reviewing"].includes(session.status);

  const stored: Definition = {
    event_name: session.event_name || "",
    event_description: session.event_description || "",
    include_criteria: session.include_criteria || "",
    exclude_criteria: session.exclude_criteria || "",
  };
  const storedKey = JSON.stringify(stored);

  const [form, setForm] = useState<Definition>(stored);
  const [syncedKey, setSyncedKey] = useState(storedKey);

  // Adopt the server's values when they actually change, during render rather
  // than in an effect. The old effect keyed on the whole session object, so any
  // unrelated refetch — a funnel poll, a progress tick — wiped what the user was
  // part-way through typing.
  if (storedKey !== syncedKey) {
    setSyncedKey(storedKey);
    setForm(stored);
  }

  const dirty = JSON.stringify(form) !== storedKey;
  const set = (patch: Partial<Definition>) =>
    setForm((prev) => ({ ...prev, ...patch }));

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(
        `/projects/${projectId}/evaluation/sessions/${session.id}/event-config`,
        form
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
      onSaved();
    },
  });

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        Describe the event in the words you would use with a colleague. Step 2 turns
        this into search queries, and the model in step 3 reads it as its
        instructions.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5 md:col-span-1">
          <Label htmlFor="event-name">Event name</Label>
          <Input
            id="event-name"
            value={form.event_name}
            onChange={(e) => set({ event_name: e.target.value })}
            disabled={!isEditable}
            placeholder="Pulmonary embolism"
          />
        </div>
        <div className="space-y-1.5 md:col-span-1">
          <Label htmlFor="event-desc">What happened to the patient</Label>
          <textarea
            id="event-desc"
            value={form.event_description}
            onChange={(e) => set({ event_description: e.target.value })}
            disabled={!isEditable}
            placeholder="A radiologically confirmed pulmonary embolism during the study period."
            className={FIELD_CLASS}
            rows={2}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="include-criteria">Counts as the event</Label>
          <textarea
            id="include-criteria"
            value={form.include_criteria}
            onChange={(e) => set({ include_criteria: e.target.value })}
            disabled={!isEditable}
            placeholder="Filling defect on CTA, or PE named as an active diagnosis."
            className={FIELD_CLASS}
            rows={2}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="exclude-criteria">Does not count</Label>
          <textarea
            id="exclude-criteria"
            value={form.exclude_criteria}
            onChange={(e) => set({ exclude_criteria: e.target.value })}
            disabled={!isEditable}
            placeholder="Suspected or ruled-out PE, family history, prophylaxis without a diagnosis."
            className={FIELD_CLASS}
            rows={2}
          />
        </div>
      </div>

      {isEditable && (
        <div className="flex items-center gap-3">
          <Button
            onClick={() => (dirty ? saveMutation.mutate() : onSaved())}
            disabled={!form.event_name.trim() || saveMutation.isPending}
          >
            {saveMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving
              </>
            ) : (
              <>
                {dirty ? "Save and continue" : "Continue"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
          {dirty && (
            <span className="text-xs text-muted-foreground">Unsaved changes</span>
          )}
        </div>
      )}

      {saveMutation.isError && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(saveMutation.error as Error).message}
        </p>
      )}
    </div>
  );
}
