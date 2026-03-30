import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { QueryMatchesResult, NoteWithMatches } from "@/projects/types";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

interface NotePreviewListProps {
  projectId: string;
  sessionId: string;
  queryIndex: number;
}

function HighlightedText({ text, matches }: { text: string; matches: NoteWithMatches["matches"] }) {
  if (!matches.length) return <span>{text}</span>;

  const positions = matches
    .flatMap((m) =>
      m.match_positions.map((p) => ({ ...p, is_negated: m.is_negated }))
    )
    .sort((a, b) => a.start - b.start);

  if (!positions.length) return <span>{text}</span>;

  const parts: React.ReactNode[] = [];
  let lastEnd = 0;

  for (const pos of positions) {
    if (pos.start > lastEnd) {
      parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd, pos.start)}</span>);
    }
    const cls = pos.is_negated
      ? "bg-red-500/20 text-red-300 line-through"
      : "bg-blue-500/20 text-blue-300 font-medium";
    parts.push(
      <span key={`h-${pos.start}`} className={cls}>
        {text.slice(pos.start, pos.end)}
      </span>
    );
    lastEnd = pos.end;
  }
  if (lastEnd < text.length) {
    parts.push(<span key={`t-${lastEnd}`}>{text.slice(lastEnd)}</span>);
  }

  return <>{parts}</>;
}

export default function NotePreviewList({ projectId, sessionId, queryIndex }: NotePreviewListProps) {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["query-matches", projectId, sessionId, queryIndex, page],
    queryFn: () =>
      api.get<QueryMatchesResult>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/queries/${queryIndex}/matches?page=${page}&page_size=10`
      ),
  });

  if (isLoading) return <p className="py-4 text-sm text-muted-foreground">Loading matches...</p>;
  if (!data || data.notes.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">No matched notes for this query.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {data.total_notes} notes from {data.total_patients} patients
      </div>

      {data.notes.map((note) => (
        <div key={note.note_id} className="rounded-lg border bg-muted/30 p-3">
          <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
            <span>Patient: {note.patient_id.slice(0, 8)}...</span>
            {note.note_date && <span>Date: {note.note_date}</span>}
            {note.note_type && <span>Type: {note.note_type}</span>}
          </div>
          <div className="text-sm leading-relaxed">
            <HighlightedText text={note.note_text} matches={note.matches} />
          </div>
        </div>
      ))}

      {data.total_pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {data.total_pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= data.total_pages}
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
