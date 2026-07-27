import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CalendarDays,
  Trash2,
  Search,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

interface AnnotationView {
  pos_start: number;
  total_pos: number;
  patient_id: string;
  note_id: string;
  note_date: string | null;
  event_date: string | null;
  note_comment: string;
  highlighted_sentence: string;
  full_note: string;
  tags: string[];
}

interface NextResponse {
  complete: boolean;
  patient_id: string | null;
  patient_status: string | null;
  annotation: AnnotationView | null;
}

interface ActionResponse {
  patient_complete: boolean;
  annotation: AnnotationView | null;
}

/**
 * Adjudication reviewer — v2 port of ops.py `adjudicate_records` /
 * `show_annotation` / `save_adjudications`. The backend AdjudicationHandler
 * drives all navigation and review state.
 */
export default function AdjudicatePage() {
  const { projectId } = useParams<{ projectId: string }>();

  const [patientId, setPatientId] = useState<string | null>(null);
  const [annotation, setAnnotation] = useState<AnnotationView | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const [comment, setComment] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadNext = useCallback(
    async (searchTerm?: string) => {
      setBusy(true);
      setError(null);
      try {
        const qs = searchTerm ? `?search=${encodeURIComponent(searchTerm)}` : "";
        const res = await api.get<NextResponse>(
          `/projects/${projectId}/workflow/review/next${qs}`
        );
        if (res.complete) {
          setComplete(true);
          setPatientId(null);
          setAnnotation(null);
        } else {
          setComplete(false);
          setPatientId(res.patient_id);
          setStatus(res.patient_status);
          setAnnotation(res.annotation);
          setComment(res.annotation?.note_comment ?? "");
          setEventDate(res.annotation?.event_date ?? "");
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load patient");
      } finally {
        setBusy(false);
      }
    },
    [projectId]
  );

  useEffect(() => {
    loadNext();
  }, [loadNext]);

  const act = async (action: string) => {
    if (!patientId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<ActionResponse>(
        `/projects/${projectId}/workflow/review/patient/${patientId}/action`,
        {
          action,
          comment,
          event_date: action === "new_date" ? eventDate : null,
        }
      );
      if (res.patient_complete) {
        setComment("");
        await loadNext();
      } else if (res.annotation) {
        setAnnotation(res.annotation);
        setEventDate(res.annotation.event_date ?? "");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  if (complete) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
        <CheckCircle2 className="h-12 w-12 text-emerald-600" />
        <h1 className="text-xl font-semibold">All patients reviewed</h1>
        <p className="text-sm text-muted-foreground">
          There are no more patients with unreviewed annotations.
        </p>
        <Button variant="outline" onClick={() => loadNext()}>
          Check again
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-5xl">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Adjudicate</h1>
          {annotation && (
            <p className="mt-1 text-sm text-muted-foreground">
              Patient <span className="font-medium text-foreground">{annotation.patient_id}</span>
              {status && <Badge className="ml-2">{status.replace(/_/g, " ")}</Badge>}
            </p>
          )}
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            loadNext(search.trim() || undefined);
          }}
        >
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search patient ID"
            className="w-44"
          />
          <Button type="submit" variant="outline" size="sm" disabled={busy}>
            <Search className="h-4 w-4" />
          </Button>
        </form>
      </div>

      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}

      {annotation && (
        <div className="space-y-4">
          {/* Position + navigation */}
          <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-2">
            <span className="text-sm text-muted-foreground">
              Annotation {annotation.pos_start} of {annotation.total_pos}
            </span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("first_anno")}>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("prev_10")}>
                -10
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("prev_1")}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("next_1")}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("next_10")}>
                +10
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => act("last_anno")}>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Sentence */}
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center gap-4 text-xs text-muted-foreground">
              <span>Note date: {annotation.note_date ?? "—"}</span>
              <span>Event date: {annotation.event_date ?? "—"}</span>
            </div>
            <div
              className="prose prose-sm max-w-none text-foreground [&_mark]:bg-yellow-200 [&_mark]:px-0.5 dark:[&_mark]:bg-yellow-700"
              dangerouslySetInnerHTML={{ __html: annotation.highlighted_sentence }}
            />
            {annotation.tags.some((t) => t) && (
              <div className="mt-3 flex flex-wrap gap-1">
                {annotation.tags
                  .filter((t) => t)
                  .map((t, i) => (
                    <Badge key={i} variant="outline">
                      {t}
                    </Badge>
                  ))}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy} onClick={() => act("adjudicate")}>
              <CheckCircle2 className="mr-2 h-4 w-4" />
              Mark reviewed
            </Button>
            <div className="flex items-center gap-2">
              <Input
                type="date"
                value={eventDate ?? ""}
                onChange={(e) => setEventDate(e.target.value)}
                className="w-40"
              />
              <Button variant="outline" disabled={busy || !eventDate} onClick={() => act("new_date")}>
                <CalendarDays className="mr-2 h-4 w-4" />
                Mark event date
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => act("del_date")}>
                <Trash2 className="mr-2 h-4 w-4" />
                Delete date
              </Button>
            </div>
          </div>

          {/* Comment */}
          <div className="space-y-2">
            <Label htmlFor="comment">Patient comment</Label>
            <textarea
              id="comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              placeholder="Notes about this patient..."
            />
          </div>

          {/* Full note */}
          <details className="rounded-lg border border-border bg-card p-4">
            <summary className="cursor-pointer text-sm font-medium">Full note</summary>
            <div
              className="prose prose-sm mt-3 max-w-none text-foreground [&_mark]:bg-yellow-200 [&_mark]:px-0.5 dark:[&_mark]:bg-yellow-700"
              dangerouslySetInnerHTML={{ __html: annotation.full_note }}
            />
          </details>
        </div>
      )}
    </div>
  );
}
