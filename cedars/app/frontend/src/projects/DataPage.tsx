import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, FileText, Loader2, CheckCircle2 } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";

interface DataFile {
  key: string;
  name: string;
  size: number;
}

interface IngestResponse {
  filename: string;
  message: string;
  total_rows: number;
  total_chunks: number;
  total_patients: number;
}

/** Upload clinical notes (or reuse a stored upload) and load them into the DB. */
export default function DataPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState("");

  const { data: files } = useQuery<DataFile[]>({
    queryKey: ["data-files", projectId],
    queryFn: () => api.get<DataFile[]>(`/projects/${projectId}/data/files`),
    enabled: !!projectId,
  });

  async function handleUpload() {
    setError("");
    setResult(null);
    const form = new FormData();
    if (selectedKey) {
      form.append("miniofile", selectedKey);
    } else if (file) {
      form.append("file", file);
    } else {
      setError("Choose a file to upload or select an existing upload.");
      return;
    }
    setUploading(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/data/upload`, {
        method: "POST",
        body: form,
        credentials: "include",
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(typeof e.detail === "string" ? e.detail : "Upload failed");
      }
      setResult(await res.json());
      queryClient.invalidateQueries({ queryKey: ["data-files", projectId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Upload data</h1>
        <p className="text-sm text-muted-foreground">
          Load clinical notes into the project. Supported: CSV, XLSX, JSON,
          Parquet, Pickle, XML, CSV.GZ. Expected columns:{" "}
          <span className="font-mono">patient_id</span>,{" "}
          <span className="font-mono">text_id</span>,{" "}
          <span className="font-mono">text</span>,{" "}
          <span className="font-mono">text_date</span>.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && (
        <Card className="border-emerald-500/40">
          <CardContent className="flex items-start gap-3 py-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
            <div className="text-sm">
              <p className="font-medium text-foreground">{result.message}</p>
              <p className="text-muted-foreground">
                {result.total_rows} notes across {result.total_chunks} chunk(s),{" "}
                {result.total_patients} patient(s).
              </p>
              <Button asChild size="sm" className="mt-3">
                <Link to={`/projects/${projectId}/query`}>Continue to Query</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload a new file</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="file">File</Label>
            <input
              id="file"
              type="file"
              accept=".csv,.xlsx,.json,.parquet,.pickle,.pkl,.xml,.gz"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setSelectedKey("");
              }}
              className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:opacity-90"
            />
          </div>
          <Button onClick={handleUpload} disabled={uploading}>
            {uploading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading &amp; loading...
              </>
            ) : (
              <>
                <Upload className="mr-2 h-4 w-4" />
                Upload &amp; load
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {files && files.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Previously uploaded files</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {files.map((f) => (
              <label
                key={f.key}
                className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors ${
                  selectedKey === f.key
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/40"
                }`}
              >
                <input
                  type="radio"
                  name="existing"
                  checked={selectedKey === f.key}
                  onChange={() => {
                    setSelectedKey(f.key);
                    setFile(null);
                  }}
                />
                <FileText className="h-4 w-4 text-muted-foreground" />
                <span className="flex-1 truncate">{f.name}</span>
                <span className="text-xs text-muted-foreground">
                  {(f.size / 1024).toFixed(1)} KB
                </span>
              </label>
            ))}
            <p className="pt-1 text-xs text-muted-foreground">
              Select a stored file and press “Upload &amp; load” to re-ingest it.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
