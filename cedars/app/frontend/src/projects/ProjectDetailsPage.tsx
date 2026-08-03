import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useProject } from "./useProject";

/** Project details: rename the project or terminate it (admin only). */
export default function ProjectDetailsPage() {
  const project = useProject();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const isAdmin = project?.role === "admin";

  const update = useMutation({
    mutationFn: () =>
      api.put(`/projects/${projectId}`, { name, description }),
    onSuccess: () => {
      setMessage("Project updated.");
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Update failed"),
  });

  const terminate = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/projects");
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Termination failed"),
  });

  function handleUpdate(e: FormEvent) {
    e.preventDefault();
    setMessage("");
    update.mutate();
  }

  if (!isAdmin) {
    return (
      <p className="text-sm text-muted-foreground">
        You do not have admin access to this project.
      </p>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Project details</h1>
        <p className="text-sm text-muted-foreground">
          Manage this project's name and lifecycle.
        </p>
      </div>

      {message && (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          {message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Project name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Saving..." : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">Terminate project</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            This permanently deletes all data for this project. Type{" "}
            <span className="font-mono font-semibold">DELETE EVERYTHING</span> to
            confirm.
          </p>
          <Input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="DELETE EVERYTHING"
          />
          <Button
            variant="destructive"
            disabled={confirm !== "DELETE EVERYTHING" || terminate.isPending}
            onClick={() => terminate.mutate()}
          >
            {terminate.isPending ? "Terminating..." : "Terminate project"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
