import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, FileJson, FileSpreadsheet } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";

interface ExportStats {
  total: number;
  reviewed: number;
  events: number;
  total_eval_tokens: number;
}

type Format = "csv" | "json";
type Filter = "all" | "reviewed" | "events";

export default function ExportPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [format, setFormat] = useState<Format>("csv");
  const [filter, setFilter] = useState<Filter>("all");
  const [downloading, setDownloading] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(
    null
  );

  const { data: stats, isLoading } = useQuery<ExportStats>({
    queryKey: ["export-stats", projectId],
    queryFn: () => api.get<ExportStats>(`/projects/${projectId}/export/stats`),
  });

  const exportCount =
    filter === "reviewed"
      ? stats?.reviewed ?? 0
      : filter === "events"
        ? stats?.events ?? 0
        : stats?.total ?? 0;

  async function handleDownload() {
    setDownloading(true);
    setFeedback(null);
    try {
      const statusParam = filter !== "all" ? `?status=${filter}` : "";
      if (format === "csv") {
        const res = await fetch(
          `/api/v1/projects/${projectId}/export/annotations/csv${statusParam}`,
          { credentials: "include" }
        );
        if (!res.ok) throw new Error("Export failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `annotations-${projectId!.slice(0, 8)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        const data = await api.get<unknown[]>(
          `/projects/${projectId}/export/annotations${statusParam}`
        );
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `annotations-${projectId!.slice(0, 8)}.json`;
        a.click();
        URL.revokeObjectURL(url);
      }
      setFeedback({
        type: "success",
        message: `Downloaded ${exportCount} annotations as ${format.toUpperCase()}`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        message: err instanceof Error ? err.message : "Export failed",
      });
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-6">
      <WorkflowBreadcrumb currentStep="export" projectId={projectId!} />

      <div>
        <h2 className="text-lg font-semibold text-foreground">Export</h2>
        <p className="text-sm text-muted-foreground">
          Download annotated data as CSV or JSON
        </p>
      </div>

      {/* Stats summary */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : stats ? (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4" role="status" aria-label="Export statistics">
          <Card className="border-border/60">
            <CardContent className="pt-5">
              <p className="text-sm text-muted-foreground">Total Annotations</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                {stats.total}
              </p>
            </CardContent>
          </Card>
          <Card className="border-border/60">
            <CardContent className="pt-5">
              <p className="text-sm text-muted-foreground">Reviewed</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                {stats.reviewed}
              </p>
            </CardContent>
          </Card>
          <Card className="border-border/60">
            <CardContent className="pt-5">
              <p className="text-sm text-muted-foreground">Events Found</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                {stats.events}
              </p>
            </CardContent>
          </Card>
          {stats.total_eval_tokens > 0 && (
            <Card className="border-border/60">
              <CardContent className="pt-5">
                <p className="text-sm text-muted-foreground">Eval Tokens Used</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                  {stats.total_eval_tokens.toLocaleString()}
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      ) : null}

      {/* Export options */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Export Options</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Format */}
          <div>
            <Label className="mb-2 block text-sm">Format</Label>
            <div className="flex gap-3" role="radiogroup" aria-label="Export format">
              <button
                role="radio"
                aria-checked={format === "csv"}
                onClick={() => setFormat("csv")}
                className={`flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm transition-colors ${
                  format === "csv"
                    ? "border-accent bg-accent/10 text-foreground"
                    : "border-border text-muted-foreground hover:border-accent/40"
                }`}
              >
                <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
                CSV
              </button>
              <button
                role="radio"
                aria-checked={format === "json"}
                onClick={() => setFormat("json")}
                className={`flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm transition-colors ${
                  format === "json"
                    ? "border-accent bg-accent/10 text-foreground"
                    : "border-border text-muted-foreground hover:border-accent/40"
                }`}
              >
                <FileJson className="h-4 w-4" aria-hidden="true" />
                JSON
              </button>
            </div>
          </div>

          {/* Filter */}
          <div>
            <Label className="mb-2 block text-sm">Include</Label>
            <div className="flex gap-3" role="radiogroup" aria-label="Annotation filter">
              {(
                [
                  { value: "all", label: "All annotations" },
                  { value: "reviewed", label: "Reviewed only" },
                  { value: "events", label: "Events only" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.value}
                  role="radio"
                  aria-checked={filter === opt.value}
                  onClick={() => setFilter(opt.value)}
                  className={`rounded-md border px-4 py-2 text-sm transition-colors ${
                    filter === opt.value
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-accent/40"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Download */}
          <div className="flex items-center gap-4 pt-2">
            <Button
              onClick={handleDownload}
              disabled={downloading || exportCount === 0}
              aria-busy={downloading}
            >
              <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
              {downloading
                ? "Downloading..."
                : `Download ${exportCount} annotations`}
            </Button>
          </div>

          {/* Feedback */}
          <div aria-live="polite" aria-atomic="true">
            {feedback?.type === "success" && (
              <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
                {feedback.message}
              </p>
            )}
            {feedback?.type === "error" && (
              <p className="text-sm font-medium text-destructive" role="alert">
                {feedback.message}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
