import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  CUSTOM_MODEL,
  PROVIDERS,
  bedrockModelWarning,
  defaultModelFor,
  modelPresets,
  presetFor,
} from "@/lib/llmModels";

interface CreateProjectResponse {
  id: string;
  name: string;
  description: string;
}

export default function CreateProjectPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [llmProvider, setLlmProvider] = useState("openai");
  const [llmModel, setLlmModel] = useState(defaultModelFor("openai"));
  // True when the model ID is typed by hand instead of picked from the presets.
  const [customModel, setCustomModel] = useState(false);
  const [llmApiBase, setLlmApiBase] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [error, setError] = useState("");

  const presets = modelPresets(llmProvider);
  const selectedPreset = presetFor(llmProvider, llmModel);
  const modelWarning = bedrockModelWarning(llmProvider, llmModel);
  // Bedrock authenticates with the deployment's AWS credentials — no endpoint,
  // no API key.
  const usesConnectionFields = llmProvider !== "bedrock";

  function handleProviderChange(next: string) {
    setLlmProvider(next);
    setLlmModel(defaultModelFor(next));
    setCustomModel(modelPresets(next).length === 0);
    if (next === "bedrock") {
      setLlmApiBase("");
      setLlmApiKey("");
    }
  }

  function handleModelChange(next: string) {
    if (next === CUSTOM_MODEL) {
      setCustomModel(true);
      setLlmModel("");
    } else {
      setCustomModel(false);
      setLlmModel(next);
    }
  }

  const mutation = useMutation({
    mutationFn: (data: { name: string; description: string; llm_provider: string; llm_model: string; llm_api_base: string | null; llm_api_key: string | null }) =>
      api.post<CreateProjectResponse>("/projects", data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/projects");
    },
    onError: (err: Error) => {
      setError(err.message || "Failed to create project");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    mutation.mutate({
      name,
      description,
      llm_provider: llmProvider,
      llm_model: llmModel,
      llm_api_base: llmApiBase || null,
      llm_api_key: llmApiKey || null,
    });
  }

  return (
    <div className="flex h-full items-start justify-center px-8 py-12">
      <Card className="w-full max-w-lg border-border/60">
        <CardHeader>
          <CardTitle>New project</CardTitle>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-5">
            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="name">Project name</Label>
              <Input
                id="name"
                type="text"
                placeholder="e.g. Myocardial Infarction Study"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                type="text"
                placeholder="Optional project description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="border-t pt-4 mt-2">
              <p className="text-sm font-medium mb-3">LLM configuration</p>
              <div className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="llmProvider">Provider</Label>
                  <select
                    id="llmProvider"
                    value={llmProvider}
                    onChange={(e) => handleProviderChange(e.target.value)}
                    className="flex w-full rounded-md border bg-background px-3 py-2 text-sm"
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llmModel">Model</Label>
                  {presets.length > 0 && (
                    <select
                      id="llmModel"
                      value={customModel ? CUSTOM_MODEL : llmModel}
                      onChange={(e) => handleModelChange(e.target.value)}
                      className="flex w-full rounded-md border bg-background px-3 py-2 text-sm"
                    >
                      {presets.map((p) => (
                        <option key={p.id} value={p.id}>{p.label}</option>
                      ))}
                      <option value={CUSTOM_MODEL}>Custom model ID…</option>
                    </select>
                  )}
                  {(customModel || presets.length === 0) && (
                    <Input
                      id={presets.length > 0 ? "llmModelCustom" : "llmModel"}
                      type="text"
                      className="font-mono"
                      placeholder={
                        llmProvider === "bedrock"
                          ? "us.anthropic.claude-haiku-4-5-20251001-v1:0"
                          : llmProvider === "ollama" || llmProvider === "vllm"
                          ? "llama3"
                          : "gpt-4o-mini"
                      }
                      value={llmModel}
                      onChange={(e) => setLlmModel(e.target.value)}
                    />
                  )}
                  {selectedPreset && (
                    <p className="text-xs text-muted-foreground">
                      <span className="font-mono">{selectedPreset.id}</span> — {selectedPreset.hint}
                    </p>
                  )}
                  {modelWarning && (
                    <p className="text-xs text-amber-600 dark:text-amber-400">{modelWarning}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llmApiBase">API base URL (optional)</Label>
                  <Input
                    id="llmApiBase"
                    type="text"
                    placeholder="http://localhost:11434"
                    value={llmApiBase}
                    onChange={(e) => setLlmApiBase(e.target.value)}
                    disabled={!usesConnectionFields}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llmApiKey">API key (optional)</Label>
                  <Input
                    id="llmApiKey"
                    type="password"
                    autoComplete="off"
                    placeholder="sk-… (leave blank for local/self-hosted)"
                    value={llmApiKey}
                    onChange={(e) => setLlmApiKey(e.target.value)}
                    disabled={!usesConnectionFields}
                  />
                </div>
                {!usesConnectionFields && (
                  <p className="text-xs text-muted-foreground">
                    Bedrock needs no endpoint or API key — requests are signed with the
                    deployment's AWS credentials.
                  </p>
                )}
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex gap-3">
            <Button
              type="submit"
              className="flex-1"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Creating..." : "Create project"}
            </Button>
            <Button type="button" variant="outline" className="flex-1" asChild>
              <Link to="/projects">Cancel</Link>
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
