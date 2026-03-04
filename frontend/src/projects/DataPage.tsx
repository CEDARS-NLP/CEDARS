import { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  Trash2,
  Play,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  AlertTriangle,
  ChevronDown,
} from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";

interface DataSource {
  id: string;
  project_id: string;
  name: string;
  connector_type: string;
  config: Record<string, unknown>;
  status: string;
  row_count: number | null;
  error_message: string | null;
  last_sync: string | null;
  created_at: string;
}

const REQUIRED_FIELDS = [
  { key: "patient_id", label: "Patient ID", description: "Unique patient identifier (e.g. MRN)" },
  { key: "text_id", label: "Text ID", description: "Unique note/document identifier" },
  { key: "text", label: "Text", description: "Clinical note content" },
  { key: "note_date", label: "Note Date", description: "Date of the note (ISO format)" },
] as const;

const OPTIONAL_FIELDS = [
  { key: "source_ref", label: "Source Ref", description: "Source reference / accession number" },
] as const;

/** Parse first line of CSV to get column headers */
function parseCSVHeaders(text: string): string[] {
  const firstLine = text.split(/\r?\n/)[0] || "";
  return firstLine.split(",").map((h) => h.trim().replace(/^["']|["']$/g, ""));
}

/** Parse JSON to get column headers from first record */
function parseJSONHeaders(text: string): string[] {
  try {
    const data = JSON.parse(text);
    const records = Array.isArray(data) ? data : data?.records;
    if (Array.isArray(records) && records.length > 0) {
      return Object.keys(records[0]);
    }
  } catch {
    // handled by caller
  }
  return [];
}

/** Normalize a column name for matching: lowercase, trim, collapse spaces/underscores */
function normalizeCol(name: string): string {
  return name.trim().toLowerCase().replace(/[\s_]+/g, "_");
}

/** Try to auto-match a required field to a detected column */
function autoMatch(fieldKey: string, columns: string[]): string {
  const normKey = normalizeCol(fieldKey);

  // Exact normalized match
  const exact = columns.find((c) => normalizeCol(c) === normKey);
  if (exact) return exact;

  // Common aliases
  const aliases: Record<string, string[]> = {
    patient_id: ["patient_id", "patientid", "mrn", "patient", "pid", "subject_id", "subjectid"],
    text_id: ["text_id", "textid", "note_id", "noteid", "doc_id", "docid", "document_id"],
    text: ["text", "note_text", "notetext", "note", "clinical_text", "content", "body"],
    note_date: ["note_date", "notedate", "date", "text_date", "encounter_date"],
    source_ref: ["source_ref", "sourceref", "accession", "accession_number", "reference"],
  };

  const fieldAliases = aliases[fieldKey] || [];
  for (const alias of fieldAliases) {
    const match = columns.find((c) => normalizeCol(c) === alias);
    if (match) return match;
  }

  return "";
}

// ── Status helpers ──────────────────────────────────────────────

function statusIcon(status: string) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-destructive" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-accent" />;
    default:
      return <Clock className="h-4 w-4 text-muted-foreground" />;
  }
}

function statusLabel(status: string) {
  switch (status) {
    case "completed":
      return "Ingested";
    case "failed":
      return "Failed";
    case "running":
      return "Ingesting...";
    default:
      return "Pending";
  }
}

// ── Column Mapping Select ───────────────────────────────────────

function ColumnSelect({
  value,
  columns,
  onChange,
  required,
}: {
  value: string;
  columns: string[];
  onChange: (v: string) => void;
  required?: boolean;
}) {
  const isMissing = required && !value;
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full appearance-none rounded-md border px-3 py-1.5 pr-8 text-sm bg-background transition-colors focus:outline-none focus:ring-2 focus:ring-ring ${
          isMissing
            ? "border-destructive/50 text-destructive"
            : value
              ? "border-input text-foreground"
              : "border-input text-muted-foreground"
        }`}
      >
        <option value="">— Select column —</option>
        {columns.map((col) => (
          <option key={col} value={col}>
            {col}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────

export default function DataPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();

  // Upload state
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState("");

  // Column mapping state (shown after file is selected)
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [detectedColumns, setDetectedColumns] = useState<string[]>([]);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [parseError, setParseError] = useState("");
  const [previewRows, setPreviewRows] = useState<Record<string, string>[]>([]);

  const {
    data: sources,
    isLoading,
  } = useQuery<DataSource[]>({
    queryKey: ["data-sources", projectId],
    queryFn: () => api.get<DataSource[]>(`/projects/${projectId}/data/sources`),
  });

  const uploadMutation = useMutation({
    mutationFn: async ({ file, mapping }: { file: File; mapping: Record<string, string> }) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("column_mapping", JSON.stringify(mapping));
      const resp = await fetch(`/api/v1/projects/${projectId}/data/upload`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Upload failed");
      }
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-sources", projectId] });
      setUploadError("");
      resetFileState();
    },
    onError: (err: Error) => setUploadError(err.message),
  });

  const ingestMutation = useMutation({
    mutationFn: (dsId: string) =>
      api.post(`/projects/${projectId}/data/sources/${dsId}/ingest`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-sources", projectId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (dsId: string) =>
      api.delete(`/projects/${projectId}/data/sources/${dsId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-sources", projectId] });
    },
  });

  function resetFileState() {
    setPendingFile(null);
    setDetectedColumns([]);
    setColumnMapping({});
    setParseError("");
    setPreviewRows([]);
  }

  /** Read file headers and set up column mapping UI */
  async function handleFileSelected(file: File) {
    setUploadError("");
    setParseError("");

    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext !== "csv" && ext !== "json") {
      setUploadError("Only CSV and JSON files are supported.");
      return;
    }

    try {
      const text = await file.text();
      const columns = ext === "csv" ? parseCSVHeaders(text) : parseJSONHeaders(text);

      if (columns.length === 0) {
        setParseError("Could not detect any columns in this file. Check the file format.");
        setPendingFile(file);
        return;
      }

      // Auto-match columns
      const mapping: Record<string, string> = {};
      for (const field of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]) {
        mapping[field.key] = autoMatch(field.key, columns);
      }

      // Parse a few preview rows
      let preview: Record<string, string>[] = [];
      if (ext === "csv") {
        const lines = text.split(/\r?\n/).filter(Boolean);
        const headers = parseCSVHeaders(text);
        preview = lines.slice(1, 4).map((line) => {
          const values = line.split(",").map((v) => v.trim().replace(/^["']|["']$/g, ""));
          const row: Record<string, string> = {};
          headers.forEach((h, i) => { row[h] = values[i] || ""; });
          return row;
        });
      } else {
        try {
          const data = JSON.parse(text);
          const records = Array.isArray(data) ? data : data?.records || [];
          preview = records.slice(0, 3).map((r: Record<string, unknown>) => {
            const row: Record<string, string> = {};
            for (const [k, v] of Object.entries(r)) row[k] = String(v ?? "");
            return row;
          });
        } catch { /* ignore */ }
      }

      setPendingFile(file);
      setDetectedColumns(columns);
      setColumnMapping(mapping);
      setPreviewRows(preview);
    } catch {
      setParseError("Failed to read the file. Check that it is a valid CSV or JSON.");
      setPendingFile(file);
    }
  }

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelected(file);
    },
    []
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelected(file);
      e.target.value = "";
    },
    []
  );

  function handleConfirmUpload() {
    if (!pendingFile) return;
    // Filter out unmapped optional fields
    const finalMapping: Record<string, string> = {};
    for (const [key, value] of Object.entries(columnMapping)) {
      if (value) finalMapping[key] = value;
    }
    uploadMutation.mutate({ file: pendingFile, mapping: finalMapping });
  }

  const missingRequired = REQUIRED_FIELDS.filter((f) => !columnMapping[f.key]);
  const allRequiredMapped = missingRequired.length === 0;

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="data" projectId={projectId!} />
      {/* Upload zone (shown when no file is pending) */}
      {!pendingFile && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12 transition-colors ${
            isDragging
              ? "border-accent bg-accent/5"
              : "border-border hover:border-accent/40"
          }`}
        >
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
            <Upload className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="mb-1 text-sm font-medium text-foreground">
            Drop a file here
          </p>
          <p className="mb-4 text-xs text-muted-foreground">
            CSV or JSON — must include <span className="font-medium text-foreground">patient_id</span>,{" "}
            <span className="font-medium text-foreground">text_id</span>,{" "}
            <span className="font-medium text-foreground">text</span>, and{" "}
            <span className="font-medium text-foreground">note_date</span> columns
          </p>
          <label>
            <Button variant="outline" size="sm" asChild>
              <span>Browse files</span>
            </Button>
            <input
              type="file"
              accept=".csv,.json"
              className="hidden"
              onChange={handleFileInput}
            />
          </label>
          {uploadError && (
            <p className="mt-3 text-sm text-destructive">{uploadError}</p>
          )}
        </div>
      )}

      {/* Column mapping step (shown after file selected) */}
      {pendingFile && (
        <Card>
          <CardContent className="space-y-5 pt-6">
            {/* File info */}
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 dark:bg-primary/20">
                <FileText className="h-5 w-5 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{pendingFile.name}</p>
                <p className="text-xs text-muted-foreground">
                  {detectedColumns.length > 0
                    ? `${detectedColumns.length} columns detected`
                    : "No columns detected"}
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={resetFileState}>
                Cancel
              </Button>
            </div>

            {parseError && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5">
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <p className="text-sm text-destructive">{parseError}</p>
              </div>
            )}

            {detectedColumns.length > 0 && (
              <>
                {/* Column mapping */}
                <div>
                  <Label className="mb-3 block text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Map your columns
                  </Label>
                  <p className="mb-4 text-xs text-muted-foreground">
                    Match each required field to a column in your file. We auto-matched what we could.
                  </p>

                  <div className="space-y-3">
                    {REQUIRED_FIELDS.map((field) => (
                      <div key={field.key} className="grid grid-cols-[1fr,auto,1fr] items-center gap-3">
                        <div>
                          <span className="text-sm font-medium text-foreground">{field.label}</span>
                          <span className="ml-1.5 text-[10px] font-medium uppercase text-destructive">required</span>
                          <p className="text-xs text-muted-foreground">{field.description}</p>
                        </div>
                        <span className="text-xs text-muted-foreground">&larr;</span>
                        <ColumnSelect
                          value={columnMapping[field.key] || ""}
                          columns={detectedColumns}
                          onChange={(v) => setColumnMapping((prev) => ({ ...prev, [field.key]: v }))}
                          required
                        />
                      </div>
                    ))}

                    <div className="my-1 border-t border-border" />

                    {OPTIONAL_FIELDS.map((field) => (
                      <div key={field.key} className="grid grid-cols-[1fr,auto,1fr] items-center gap-3">
                        <div>
                          <span className="text-sm font-medium text-foreground">{field.label}</span>
                          <span className="ml-1.5 text-[10px] text-muted-foreground">optional</span>
                          <p className="text-xs text-muted-foreground">{field.description}</p>
                        </div>
                        <span className="text-xs text-muted-foreground">&larr;</span>
                        <ColumnSelect
                          value={columnMapping[field.key] || ""}
                          columns={detectedColumns}
                          onChange={(v) => setColumnMapping((prev) => ({ ...prev, [field.key]: v }))}
                        />
                      </div>
                    ))}
                  </div>
                </div>

                {/* Preview */}
                {previewRows.length > 0 && (
                  <div>
                    <Label className="mb-2 block text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Preview (first {previewRows.length} rows)
                    </Label>
                    <div className="overflow-x-auto rounded-md border border-border">
                      <table className="min-w-full text-xs">
                        <thead>
                          <tr className="border-b border-border bg-muted/50">
                            {detectedColumns.map((col) => {
                              const mappedTo = Object.entries(columnMapping).find(([, v]) => v === col);
                              return (
                                <th key={col} className="px-3 py-2 text-left font-medium text-foreground">
                                  <span>{col}</span>
                                  {mappedTo && (
                                    <span className="ml-1 text-[10px] font-normal text-accent">
                                      &rarr; {mappedTo[0]}
                                    </span>
                                  )}
                                </th>
                              );
                            })}
                          </tr>
                        </thead>
                        <tbody>
                          {previewRows.map((row, i) => (
                            <tr key={i} className="border-b border-border/50 last:border-0">
                              {detectedColumns.map((col) => (
                                <td key={col} className="max-w-[200px] truncate px-3 py-1.5 text-muted-foreground">
                                  {row[col] || ""}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Validation status + upload button */}
                <div className="flex items-center gap-3">
                  <Button
                    onClick={handleConfirmUpload}
                    disabled={!allRequiredMapped || uploadMutation.isPending}
                  >
                    {uploadMutation.isPending ? (
                      <>
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <Upload className="mr-1.5 h-4 w-4" />
                        Upload &amp; Create Data Source
                      </>
                    )}
                  </Button>
                  {!allRequiredMapped && (
                    <div className="flex items-center gap-1.5 text-sm text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="h-4 w-4" />
                      <span>
                        Missing: {missingRequired.map((f) => f.label).join(", ")}
                      </span>
                    </div>
                  )}
                  {allRequiredMapped && (
                    <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="h-4 w-4" />
                      All required columns mapped
                    </span>
                  )}
                </div>

                {uploadError && (
                  <p className="text-sm text-destructive">{uploadError}</p>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Data sources list */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-muted-foreground">
          Data Sources
        </h3>

        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading...</p>
        )}

        {sources && sources.length === 0 && !pendingFile && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No data sources yet. Upload a file to get started.
          </p>
        )}

        {sources && sources.length > 0 && (
          <div className="space-y-3">
            {sources.map((ds) => (
              <Card key={ds.id} className="border-border/60">
                <CardContent className="flex items-center gap-4 py-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 dark:bg-primary/20">
                    <FileText className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {ds.name}
                    </p>
                    <div className="mt-0.5 flex items-center gap-2">
                      {statusIcon(ds.status)}
                      <span className="text-xs text-muted-foreground">
                        {statusLabel(ds.status)}
                        {ds.row_count != null && ` \u00b7 ${ds.row_count} rows`}
                      </span>
                      {ds.error_message && (
                        <span className="truncate text-xs text-destructive" title={ds.error_message}>
                          {ds.error_message}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {ds.status === "pending" && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => ingestMutation.mutate(ds.id)}
                        disabled={ingestMutation.isPending}
                      >
                        <Play className="mr-1 h-3.5 w-3.5" />
                        Ingest
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => deleteMutation.mutate(ds.id)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
