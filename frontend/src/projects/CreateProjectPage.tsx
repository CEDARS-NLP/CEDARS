import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
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
  const [error, setError] = useState("");

  const mutation = useMutation({
    mutationFn: (data: { name: string; description: string }) =>
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
    mutation.mutate({ name, description });
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl">New Project</CardTitle>
          <CardDescription>
            Create a new clinical event detection project
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="flex flex-col gap-4">
            {error && (
              <p className="text-sm text-destructive">{error}</p>
            )}
            <div className="flex flex-col gap-2">
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
            <div className="flex flex-col gap-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                type="text"
                placeholder="Optional project description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
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
