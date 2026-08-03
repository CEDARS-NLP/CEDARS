import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  SkipBack,
  SkipForward,
  Check,
  Search,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import EvidenceHighlighter from "@/components/EvidenceHighlighter";
import NoteViewer from "@/components/NoteViewer";

interface EvidenceSpan {
  text: string;
  start_pos: number;
  end_pos: number;
  match_source: string;
}

interface AnnotationView {
  pos_start: number;
  total_pos: number;
  patient_id: string;
  note_id: string;
  note_date: string | null;
  event_date: string | null;
  note_comment: string;
  tags: string[];
  full_note: string;
  full_note_evidence: EvidenceSpan[];
  sentence: string;
  sentence_evidence: EvidenceSpan[];
}

interface AdjudicateResponse {
  complete: boolean;
  patient_id: string | null;
  patient_status: string | null;
  patient_complete: boolean | null;
  annotation: AnnotationView | null;
  message: string | null;
}

const NAV = [
  { action: "first_anno", icon: SkipBack, title: "First annotation" },
  { action: "prev_10", icon: ChevronsLeft, title: "Back 10" },
  { action: "prev_1", icon: ChevronLeft, title: "Previous" },
  { action: "next_1", icon: ChevronRight, title: "Next" },
  { action: "next_10", icon: ChevronsRight, title: "Forward 10" },
  { action: "last_anno", icon: SkipForward, title: "Last annotation" },
];

/** Adjudication workspace (ports adjudicate_records.html + save_adjudications). */
export default function AdjudicatePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [resp, setResp] = useState<AdjudicateResponse | null>(null);
  const [comment, setComment] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState("");

  const ann = resp?.annotation ?? null;

  const applyResponse = useCallback((r: AdjudicateResponse) => {
    setResp(r);
    setFlash(r.message ?? "");
    if (r.annotation) {
      setComment(r.annotation.note_comment ?? "");
      setEventDate(r.annotation.event_date ?? r.annotation.note_date ?? "");
    }
  }, []);

  const loadNext = useCallback(async () => {
    setLoading(true);
    try {
      applyResponse(
        await api.get<AdjudicateResponse>(`/projects/${projectId}/adjudicate/next`)
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, applyResponse]);

  useEffect(() => {
    loadNext();
  }, [loadNext]);

  async function doAction(action: string) {
    setLoading(true);
    try {
      applyResponse(
        await api.post<AdjudicateResponse>(`/projects/${projectId}/adjudicate/save`, {
          action,
          comment,
          event_date: eventDate || null,
        })
      );
    } finally {
      setLoading(false);
    }
  }

  async function doSearch() {
    if (!search.trim()) return;
    setLoading(true);
    try {
      applyResponse(
        await api.post<AdjudicateResponse>(`/projects/${projectId}/adjudicate/search`, {
          patient_id: search.trim(),
        })
      );
      setSearch("");
    } finally {
      setLoading(false);
    }
  }

  // Unlock the current patient on leave (unmount / tab close) + idle timeout.
  useEffect(() => {
    const apiPath = `/projects/${projectId}/adjudicate/unlock`;
    const beaconUrl = `/api/v1${apiPath}`;
    const beacon = () => navigator.sendBeacon(beaconUrl);
    window.addEventListener("beforeunload", beacon);

    let idle: number;
    const resetIdle = () => {
      window.clearTimeout(idle);
      idle = window.setTimeout(() => {
        api.post(apiPath).catch(() => {});
        setFlash("Patient unlocked due to inactivity.");
      }, 30 * 60 * 1000);
    };
    const events = ["click", "keydown", "mousemove"];
    events.forEach((e) => document.addEventListener(e, resetIdle));
    resetIdle();

    return () => {
      window.removeEventListener("beforeunload", beacon);
      window.clearTimeout(idle);
      events.forEach((e) => document.removeEventListener(e, resetIdle));
      navigator.sendBeacon(beaconUrl);
    };
  }, [projectId]);

  if (resp?.complete && !ann) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <CheckCircle2 className="mb-4 h-12 w-12 text-emerald-600" />
        <h2 className="text-xl font-semibold text-foreground">
          All annotations reviewed
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          There are no more patients to adjudicate.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search bar */}
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          doSearch();
        }}
      >
        <Input
          placeholder="Enter Patient ID"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Button type="submit" variant="outline" size="sm" disabled={loading}>
          <Search className="mr-2 h-4 w-4" />
          Search
        </Button>
      </form>

      {flash && (
        <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          {flash}
        </div>
      )}

      {!ann ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left: note/patient data + date + comments */}
          <div className="space-y-4 lg:col-span-4">
            <Card>
              <CardContent className="space-y-2 py-4 text-sm">
                <h2 className="mb-1 font-semibold text-foreground">
                  Note &amp; patient data
                </h2>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Position</span>
                  <span>
                    {ann.pos_start} of {ann.total_pos}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Patient ID</span>
                  <span className="font-medium">{ann.patient_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Note date</span>
                  <span>{ann.note_date ?? "None"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Current event date</span>
                  <span className="font-medium">{ann.event_date ?? "None"}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 py-4">
                <div className="space-y-2">
                  <Label htmlFor="event-date">Enter event date</Label>
                  <Input
                    id="event-date"
                    type="date"
                    value={eventDate}
                    onChange={(e) => setEventDate(e.target.value)}
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={loading || !eventDate}
                    onClick={() => doAction("new_date")}
                  >
                    Enter date
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={loading}
                    onClick={() => doAction("del_date")}
                  >
                    Delete date
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 py-4">
                <Label htmlFor="comment">Comments</Label>
                <textarea
                  id="comment"
                  rows={4}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={loading}
                  onClick={() => doAction("comment")}
                >
                  Save comment
                </Button>
              </CardContent>
            </Card>
          </div>

          {/* Right: sentence + navigation + full note + tags */}
          <div className="space-y-4 lg:col-span-8">
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Selected sentence
              </h3>
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <EvidenceHighlighter
                  noteText={ann.sentence}
                  evidence={ann.sentence_evidence}
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={loading} onClick={() => doAction("adjudicate")}>
                <Check className="mr-2 h-4 w-4" />
                Adjudicate sentence
              </Button>
              <div className="flex items-center gap-1">
                {NAV.map((n) => (
                  <Button
                    key={n.action}
                    variant="outline"
                    size="icon"
                    title={n.title}
                    disabled={loading}
                    onClick={() => doAction(n.action)}
                  >
                    <n.icon className="h-4 w-4" />
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Full note {ann.note_id}
              </h3>
              <NoteViewer
                noteText={ann.full_note}
                evidence={ann.full_note_evidence}
                maxHeight="30rem"
              />
            </div>

            {ann.tags.some((t) => t) && (
              <div className="flex flex-wrap gap-2">
                {ann.tags.map((t, i) =>
                  t ? (
                    <span
                      key={i}
                      className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-secondary-foreground"
                    >
                      {t}
                    </span>
                  ) : null
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
