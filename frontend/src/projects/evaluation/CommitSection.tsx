import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { UnifiedSession, CommitResult } from "@/projects/types";
import { Lock, Loader2 } from "lucide-react";

interface CommitSectionProps {
  projectId: string;
  session: UnifiedSession;
  onRefresh: () => void;
}

export default function CommitSection({ projectId, session, onRefresh }: CommitSectionProps) {
  const qc = useQueryClient();

  const commitMutation = useMutation({
    mutationFn: () =>
      api.post<CommitResult>(
        `/projects/${projectId}/evaluation/sessions/${session.id}/commit`,
        {}
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-session", projectId, session.id] });
      onRefresh();
    },
  });

  if (session.status !== "reviewing") return null;

  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Ready to commit?</h2>
          <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
            This will lock the search queries and LLM prompt, then run the
            pipeline on <strong>all patients</strong> in the project.
          </p>
        </div>
        <Button
          size="lg"
          onClick={() => commitMutation.mutate()}
          disabled={commitMutation.isPending}
          className="bg-green-600 text-white hover:bg-green-700"
        >
          {commitMutation.isPending ? (
            <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Committing...</>
          ) : (
            <><Lock className="mr-2 h-4 w-4" /> Commit and run full pipeline</>
          )}
        </Button>
      </div>

      {commitMutation.isError && (
        <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {(commitMutation.error as Error).message}
        </div>
      )}

      {commitMutation.isSuccess && commitMutation.data && (
        <div className="mt-3 rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
          Pipeline started. Processing {commitMutation.data.total_patients} patients.
        </div>
      )}
    </div>
  );
}
