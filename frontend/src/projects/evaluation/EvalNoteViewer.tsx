import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import type { ResultNoteContext } from "@/projects/types";

function highlightKeywords(
  text: string,
  keywords: string[]
): React.ReactNode {
  if (!keywords || keywords.length === 0) return text;
  const escaped = keywords.map((k) =>
    k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(pattern);
  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return parts.map((part, i) =>
    lowerKeywords.some((k) => part.toLowerCase().startsWith(k)) ? (
      <mark
        key={i}
        className="rounded-sm bg-amber-200/70 px-0.5 text-amber-950 dark:bg-amber-500/30 dark:text-amber-100"
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function EvalNoteViewer({
  notes,
  keywords,
  activeNoteId,
}: {
  notes: ResultNoteContext[];
  keywords: string[];
  activeNoteId?: string | null;
}) {
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [activeNoteId]);

  const noteFont = { fontFamily: "Georgia, 'Times New Roman', serif" };

  if (notes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No matched notes available for this patient.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {notes.map((note) => {
        const isActive = note.note_id === activeNoteId;
        return (
          <div
            key={note.note_id}
            ref={isActive ? activeRef : undefined}
            className={`rounded-lg border ${
              note.is_evidence
                ? "border-primary/40 bg-primary/5"
                : "border-border"
            } ${isActive ? "ring-2 ring-primary/50" : ""}`}
          >
            <div className="flex items-center gap-2 border-b border-border/50 px-4 py-2">
              <span className="text-xs font-medium text-foreground">
                {note.text_id}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatDate(note.note_date)}
              </span>
              {note.is_evidence && (
                <Badge className="bg-primary/20 text-primary text-[10px] px-1.5 py-0">
                  LLM Evidence
                </Badge>
              )}
              {note.note_tags &&
                Object.entries(note.note_tags)
                  .filter(([k]) => k.startsWith("text_tag"))
                  .map(([key, val]) => (
                    <Badge
                      key={key}
                      variant="outline"
                      className="border-blue-500/30 bg-blue-500/10 px-1.5 py-0 text-[10px] font-normal text-blue-600 dark:text-blue-400"
                    >
                      {String(val)}
                    </Badge>
                  ))}
            </div>
            <div
              className="max-h-64 overflow-y-auto px-4 py-3 text-[14px] leading-relaxed text-foreground/70"
              style={noteFont}
            >
              {highlightKeywords(note.text, keywords)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
