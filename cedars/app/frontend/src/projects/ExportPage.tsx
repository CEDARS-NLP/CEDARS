import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Trash2, FileDown } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface DownloadFile {
  name: string;
  size: number;
  last_modified: string;
}

/** Generate, list, download and delete annotation exports (ports download.html). */
export default function ExportPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const { data: files, isError: filesFailed, error: filesError } = useQuery<DownloadFile[]>({
    queryKey: ["downloads", projectId],
    queryFn: () => api.get<DownloadFile[]>(`/projects/${projectId}/download/files`),
    enabled: !!projectId,
    refetchInterval: 5000,
  });

  async function createDownload(full: boolean) {
    setBusy(true);
    setMessage(full ? "Generating full export..." : "Generating export...");
    try {
      const { job_id } = await api.post<{ job_id: string }>(
        `/projects/${projectId}/download/${full ? "full" : "compact"}`
      );
      for (let i = 0; i < 150; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const s = await api.get<{ status: string }>(
          `/projects/${projectId}/download/check/${job_id}`
        );
        if (s.status === "finished") {
          setMessage("Export ready.");
          break;
        }
        if (s.status === "failed" || s.status === "not_found") {
          setMessage("Export failed.");
          break;
        }
      }
      queryClient.invalidateQueries({ queryKey: ["downloads", projectId] });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadFile(name: string) {
    try {
      const blob = await api.getBlob(`/projects/${projectId}/download/file/${encodeURIComponent(name)}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cedars_${name}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function removeFile(name: string) {
    try {
      await api.delete(`/projects/${projectId}/download/file/${encodeURIComponent(name)}`);
      queryClient.invalidateQueries({ queryKey: ["downloads", projectId] });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Export annotations</h1>
        <p className="text-sm text-muted-foreground">
          Generate a CSV of the annotated cohort. The compact export is one row
          per patient; the full export also includes key sentences.
        </p>
      </div>

      {message && (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          {message}
        </div>
      )}

      <div className="flex gap-3">
        <Button onClick={() => createDownload(false)} disabled={busy}>
          {busy ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <FileDown className="mr-2 h-4 w-4" />
          )}
          Generate compact export
        </Button>
        <Button
          onClick={() => createDownload(true)}
          disabled={busy}
          variant="outline"
        >
          <FileDown className="mr-2 h-4 w-4" />
          Generate full export
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Available exports</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {filesFailed ? (
            <p className="text-sm text-destructive">
              Failed to load exports: {filesError instanceof Error ? filesError.message : "unknown error"}
            </p>
          ) : !files || files.length === 0 ? (
            <p className="text-sm text-muted-foreground">No exports generated yet.</p>
          ) : (
            files.map((f) => (
              <div
                key={f.name}
                className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm"
              >
                <span className="flex-1 truncate font-mono text-xs">{f.name}</span>
                <span className="text-xs text-muted-foreground">
                  {f.last_modified}
                </span>
                <Button size="sm" variant="ghost" onClick={() => downloadFile(f.name)}>
                  <Download className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => removeFile(f.name)}
                  aria-label="Delete export"
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
