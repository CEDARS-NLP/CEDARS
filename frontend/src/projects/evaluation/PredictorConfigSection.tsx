import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Plus,
  Trash2,
  Star,
  FlaskConical,
  CheckCircle2,
  Pencil,
  X,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  Predictor,
  TestResult,
  PredictorFormState,
  TokenUsage,
} from "@/projects/types";
import {
  EMPTY_FORM,
  formFromPredictor,
  formToPayload,
} from "@/projects/types";

const SELF_HOSTED = new Set(["ollama", "vllm", "lmstudio", "openai_compatible"]);

function PredictorFormFields({
  form,
  onChange,
  showTypeSelector,
}: {
  form: PredictorFormState;
  onChange: (updates: Partial<PredictorFormState>) => void;
  showTypeSelector?: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label>Name</Label>
          <Input
            placeholder="e.g. GPT-4o MI Detector"
            value={form.name}
            onChange={(e) => onChange({ name: e.target.value })}
          />
        </div>
        {showTypeSelector && (
          <div className="space-y-2">
            <Label>Type</Label>
            <div className="flex gap-2">
              <Button
                variant={form.type === "llm" ? "default" : "outline"}
                size="sm"
                onClick={() => onChange({ type: "llm" })}
              >
                LLM
              </Button>
              <Button
                variant={form.type === "pines" ? "default" : "outline"}
                size="sm"
                onClick={() => onChange({ type: "pines" })}
              >
                PINES
              </Button>
            </div>
          </div>
        )}
      </div>

      {form.type === "llm" ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Provider</Label>
              <select
                value={form.provider}
                onChange={(e) => {
                  const p = e.target.value;
                  let apiBase = form.apiBase;
                  if (p === "ollama") apiBase = "http://localhost:11434";
                  else if (p === "vllm" || p === "lmstudio" || p === "openai_compatible")
                    apiBase = "http://localhost:8000/v1";
                  else apiBase = "";
                  onChange({ provider: p, apiBase });
                }}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="ollama">Ollama (local)</option>
                <option value="vllm">vLLM (OpenAI-compatible)</option>
                <option value="lmstudio">LM Studio (local)</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="bedrock">AWS Bedrock</option>
                <option value="openai_compatible">Other OpenAI-compatible</option>
              </select>
              <p className="text-xs text-muted-foreground">
                {SELF_HOSTED.has(form.provider)
                  ? "Self-hosted \u2014 no API key required"
                  : "Cloud provider \u2014 API key required"}
              </p>
            </div>
            <div className="space-y-2">
              <Label>Model</Label>
              <Input
                value={form.model}
                onChange={(e) => onChange({ model: e.target.value })}
                placeholder={
                  form.provider === "ollama"
                    ? "llama3, mistral..."
                    : form.provider === "vllm"
                      ? "gpt-oss-120b, meta-llama/..."
                      : form.provider === "openai"
                        ? "gpt-4o, gpt-4o-mini..."
                        : form.provider === "anthropic"
                          ? "claude-sonnet-4-20250514..."
                          : "model name"
                }
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>API Base URL</Label>
              <Input
                value={form.apiBase}
                onChange={(e) => onChange({ apiBase: e.target.value })}
                placeholder={
                  form.provider === "ollama"
                    ? "http://localhost:11434"
                    : form.provider === "vllm"
                      ? "http://localhost:8000/v1"
                      : "Leave blank for cloud providers"
                }
              />
            </div>
            <div className="space-y-2">
              <Label>
                API Key
                {SELF_HOSTED.has(form.provider) && (
                  <span className="ml-1.5 text-[10px] text-muted-foreground">optional</span>
                )}
              </Label>
              <Input
                type="password"
                value={form.apiKey}
                onChange={(e) => onChange({ apiKey: e.target.value })}
                placeholder={
                  SELF_HOSTED.has(form.provider)
                    ? "Not needed for self-hosted"
                    : "sk-..."
                }
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Event Definition
            </Label>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                placeholder="Event name (e.g. Myocardial Infarction)"
                value={form.eventName}
                onChange={(e) => onChange({ eventName: e.target.value })}
              />
              <Input
                placeholder="Description"
                value={form.eventDesc}
                onChange={(e) => onChange({ eventDesc: e.target.value })}
              />
              <Input
                placeholder="Include criteria"
                value={form.include}
                onChange={(e) => onChange({ include: e.target.value })}
              />
              <Input
                placeholder="Exclude criteria"
                value={form.exclude}
                onChange={(e) => onChange({ exclude: e.target.value })}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <Label>PINES API URL</Label>
          <Input
            value={form.pinesUrl}
            onChange={(e) => onChange({ pinesUrl: e.target.value })}
            placeholder="http://pines:8000"
          />
        </div>
      )}
    </div>
  );
}

function TokenUsageDisplay({ usage }: { usage: TokenUsage }) {
  return (
    <span className="text-xs text-muted-foreground">
      Tokens: {usage.prompt_tokens.toLocaleString()} prompt + {usage.completion_tokens.toLocaleString()} completion = {usage.total_tokens.toLocaleString()} total
    </span>
  );
}

export default function PredictorConfigSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testPredictorId, setTestPredictorId] = useState<string | null>(null);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const [createForm, setCreateForm] = useState<PredictorFormState>({ ...EMPTY_FORM });
  const [editForm, setEditForm] = useState<PredictorFormState>({ ...EMPTY_FORM });

  const { data: predictors, isLoading } = useQuery<Predictor[]>({
    queryKey: ["predictors", projectId],
    queryFn: () => api.get<Predictor[]>(`/projects/${projectId}/predictors`),
  });

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`/projects/${projectId}/predictors`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["predictors", projectId] });
      setShowForm(false);
      setCreateForm({ ...EMPTY_FORM });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.put(`/projects/${projectId}/predictors/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["predictors", projectId] });
      setEditingId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/projects/${projectId}/predictors/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["predictors", projectId] }),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) =>
      api.post(`/projects/${projectId}/predictors/${id}/activate`, {}),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["predictors", projectId] }),
  });

  const testMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      api.post<TestResult>(`/projects/${projectId}/predictors/${id}/test`, { text }),
    onSuccess: (result) => setTestResult(result as TestResult),
  });

  function startEditing(pred: Predictor) {
    setEditForm(formFromPredictor(pred));
    setEditingId(pred.id);
    setTestPredictorId(null);
    setTestResult(null);
  }

  function handleSaveEdit(id: string) {
    const payload = formToPayload(editForm);
    updateMutation.mutate({ id, body: payload });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-foreground">Predictors</h3>
          <p className="text-sm text-muted-foreground">
            Configure LLM or PINES models for clinical event classification
          </p>
        </div>
        <Button onClick={() => { setShowForm(true); setEditingId(null); }} disabled={showForm}>
          <Plus className="mr-1.5 h-4 w-4" />
          Add Predictor
        </Button>
      </div>

      {/* Create form */}
      {showForm && (
        <Card className="border-accent/30">
          <CardHeader>
            <CardTitle className="text-base">New Predictor</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <PredictorFormFields
              form={createForm}
              onChange={(updates) => setCreateForm((prev) => ({ ...prev, ...updates }))}
              showTypeSelector
            />
            <div className="flex gap-2">
              <Button
                onClick={() => createMutation.mutate(formToPayload(createForm))}
                disabled={!createForm.name || createMutation.isPending}
              >
                {createMutation.isPending ? "Creating..." : "Create Predictor"}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowForm(false);
                  setCreateForm({ ...EMPTY_FORM });
                }}
              >
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Predictor list */}
      {isLoading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {predictors && predictors.length === 0 && !showForm && (
        <div className="flex flex-col items-center rounded-lg border-2 border-dashed border-border py-16">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
            <Brain className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="text-lg font-medium text-foreground">No predictors configured</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add an LLM or PINES predictor to start classifying clinical events.
          </p>
        </div>
      )}

      {predictors && predictors.length > 0 && (
        <div className="space-y-3">
          {predictors.map((pred) => {
            const isEditing = editingId === pred.id;
            const isTesting = testPredictorId === pred.id;

            return (
              <Card
                key={pred.id}
                className={`border-border/60 ${pred.is_active ? "ring-2 ring-accent/40" : ""}`}
              >
                <CardContent className="flex items-center gap-4 py-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 dark:bg-primary/20">
                    <Brain className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-foreground">
                        {pred.name}
                      </p>
                      {pred.is_active && (
                        <span className="flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent dark:bg-accent/20">
                          <CheckCircle2 className="h-3 w-3" />
                          Active
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {pred.predictor_type.toUpperCase()}
                      {pred.config &&
                        (pred.predictor_type === "llm"
                          ? ` \u00b7 ${(pred.config as Record<string, string>).provider || ""}/${(pred.config as Record<string, string>).model || ""}`
                          : ` \u00b7 ${(pred.config as Record<string, string>).pines_api_url || ""}`)}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Edit"
                      onClick={() => {
                        if (isEditing) {
                          setEditingId(null);
                        } else {
                          startEditing(pred);
                        }
                      }}
                    >
                      {isEditing ? (
                        <X className="h-3.5 w-3.5" />
                      ) : (
                        <Pencil className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Test prediction"
                      onClick={() => {
                        if (isTesting) {
                          setTestPredictorId(null);
                        } else {
                          setTestPredictorId(pred.id);
                          setEditingId(null);
                          setTestResult(null);
                          setTestText("");
                        }
                      }}
                    >
                      <FlaskConical className="h-3.5 w-3.5" />
                    </Button>
                    {!pred.is_active && (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Set as active"
                        onClick={() => activateMutation.mutate(pred.id)}
                      >
                        <Star className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Delete"
                      onClick={() => deleteMutation.mutate(pred.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </CardContent>

                {/* Edit panel */}
                {isEditing && (
                  <div className="border-t border-border px-6 py-4 space-y-4">
                    <PredictorFormFields
                      form={editForm}
                      onChange={(updates) => setEditForm((prev) => ({ ...prev, ...updates }))}
                    />
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => handleSaveEdit(pred.id)}
                        disabled={!editForm.name || updateMutation.isPending}
                      >
                        {updateMutation.isPending ? "Saving..." : "Save Changes"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}

                {/* Test panel */}
                {isTesting && (
                  <div className="border-t border-border px-6 py-4">
                    <Label className="mb-2 block text-xs">Test Clinical Text</Label>
                    <textarea
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                      rows={3}
                      placeholder="Paste a clinical note excerpt to test..."
                      value={testText}
                      onChange={(e) => setTestText(e.target.value)}
                    />
                    <div className="mt-2 flex items-center gap-3">
                      <Button
                        size="sm"
                        onClick={() =>
                          testMutation.mutate({ id: pred.id, text: testText })
                        }
                        disabled={!testText || testMutation.isPending}
                      >
                        {testMutation.isPending ? "Running..." : "Run Test"}
                      </Button>
                      {testResult && (
                        <div className="flex items-center gap-3 text-sm">
                          <span
                            className={`font-medium ${
                              testResult.label === 1
                                ? "text-emerald-600 dark:text-emerald-400"
                                : "text-muted-foreground"
                            }`}
                          >
                            {testResult.label === 1 ? "Event Detected" : "No Event"}
                          </span>
                          <span className="text-muted-foreground">
                            Score: {testResult.score.toFixed(3)}
                          </span>
                          {testResult.reasoning && (
                            <span className="truncate text-muted-foreground" title={testResult.reasoning}>
                              {testResult.reasoning}
                            </span>
                          )}
                        </div>
                      )}
                      {testMutation.isError && (
                        <span className="text-sm text-destructive">
                          {testMutation.error instanceof Error
                            ? testMutation.error.message
                            : "Test failed"}
                        </span>
                      )}
                    </div>
                    {testResult?.token_usage && (
                      <div className="mt-2">
                        <TokenUsageDisplay usage={testResult.token_usage} />
                      </div>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
