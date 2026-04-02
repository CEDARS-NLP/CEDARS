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
  const [llmModel, setLlmModel] = useState("gpt-4o-mini");
  const [llmApiBase, setLlmApiBase] = useState("");
  const [error, setError] = useState("");

  const mutation = useMutation({
    mutationFn: (data: { name: string; description: string; llm_provider: string; llm_model: string; llm_api_base: string | null }) =>
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
    });
  }

  return (
    <div className="flex h-full items-start justify-center px-8 py-12">
      <Card className="w-full max-w-lg border-border/60">
        <CardHeader>
          <CardTitle>New Project</CardTitle>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-5">
            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="name">Project Name</Label>
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
              <p className="text-sm font-medium mb-3">LLM Configuration</p>
              <div className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="llmProvider">Provider</Label>
                  <select
                    id="llmProvider"
                    value={llmProvider}
                    onChange={(e) => setLlmProvider(e.target.value)}
                    className="flex w-full rounded-md border bg-background px-3 py-2 text-sm"
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="vllm">vLLM</option>
                    <option value="ollama">Ollama (local)</option>
                    <option value="bedrock">AWS Bedrock</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llmModel">Model</Label>
                  <Input
                    id="llmModel"
                    type="text"
                    placeholder="gpt-4o-mini"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="llmApiBase">API Base URL (optional)</Label>
                  <Input
                    id="llmApiBase"
                    type="text"
                    placeholder="http://localhost:11434"
                    value={llmApiBase}
                    onChange={(e) => setLlmApiBase(e.target.value)}
                  />
                </div>
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex gap-3">
            <Button
              type="submit"
              className="flex-1"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Creating..." : "Create Project"}
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
