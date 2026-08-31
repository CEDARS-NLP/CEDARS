import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useProject } from "./useProject";

type ProjectRole = "admin" | "annotator";

interface ProjectMember {
  username: string;
  role: ProjectRole;
  added_by: string;
}

/** Project details: rename the project or terminate it (admin only). */
export default function ProjectDetailsPage() {
  const project = useProject();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [confirm, setConfirm] = useState("");
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState<ProjectRole>("annotator");
  const [message, setMessage] = useState("");
  const isAdmin = project?.role === "admin";

  const { data: members } = useQuery<ProjectMember[]>({
    queryKey: ["project-members", projectId],
    queryFn: () => api.get<ProjectMember[]>(`/projects/${projectId}/members`),
    enabled: Boolean(projectId && isAdmin),
  });

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

  const addMember = useMutation({
    mutationFn: () => api.post<ProjectMember>(`/projects/${projectId}/members`, {
      username: memberUsername,
      role: memberRole,
    }),
    onSuccess: () => {
      setMemberUsername("");
      setMemberRole("annotator");
      setMessage("Project member added.");
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] });
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Add member failed"),
  });

  const updateMember = useMutation({
    mutationFn: ({ username, role }: { username: string; role: ProjectRole }) =>
      api.patch<ProjectMember>(`/projects/${projectId}/members/${username}`, { role }),
    onSuccess: () => {
      setMessage("Project member updated.");
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Update member failed"),
  });

  const removeMember = useMutation({
    mutationFn: (username: string) =>
      api.delete(`/projects/${projectId}/members/${username}`),
    onSuccess: () => {
      setMessage("Project member removed.");
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] });
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Remove member failed"),
  });

  function handleUpdate(e: FormEvent) {
    e.preventDefault();
    setMessage("");
    update.mutate();
  }

  function handleAddMember(e: FormEvent) {
    e.preventDefault();
    setMessage("");
    addMember.mutate();
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

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <form onSubmit={handleAddMember} className="grid gap-3 sm:grid-cols-[1fr_10rem_auto]">
            <div className="space-y-2">
              <Label htmlFor="member-username">Username</Label>
              <Input
                id="member-username"
                value={memberUsername}
                onChange={(e) => setMemberUsername(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="member-role">Role</Label>
              <select
                id="member-role"
                value={memberRole}
                onChange={(e) => setMemberRole(e.target.value as ProjectRole)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
              >
                <option value="annotator">Annotator</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <Button type="submit" className="self-end" disabled={addMember.isPending}>
              {addMember.isPending ? "Adding..." : "Add"}
            </Button>
          </form>

          <div className="divide-y divide-border rounded-md border border-border">
            {(members ?? []).map((member) => (
              <div key={member.username} className="flex flex-wrap items-center gap-3 px-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {member.username}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {member.role} · added by {member.added_by}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => updateMember.mutate({
                    username: member.username,
                    role: member.role === "admin" ? "annotator" : "admin",
                  })}
                  disabled={updateMember.isPending}
                >
                  Make {member.role === "admin" ? "annotator" : "admin"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => removeMember.mutate(member.username)}
                  disabled={removeMember.isPending}
                >
                  Remove
                </Button>
              </div>
            ))}
            {members?.length === 0 && (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                No members are assigned to this project.
              </p>
            )}
          </div>
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
