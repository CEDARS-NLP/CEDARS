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

/**
 * Renders a single note with matching sentences highlighted inline.
 * Match positions contain the sentence text and character offsets — we use
 * those to highlight the matched sentences within the full note body.
 */
export default function EvalNoteViewer({
  note,
  keywords,
}: {
  note: ResultNoteContext;
  keywords: string[];
}) {
  const firstMatchRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    firstMatchRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [note.note_id]);

  const noteFont = { fontFamily: "Georgia, 'Times New Roman', serif" };

  // Build a set of matched character ranges from match_positions
  const matchRanges: { start: number; end: number; text: string }[] = [];
  if (note.match_positions && note.match_positions.length > 0) {
    for (const pos of note.match_positions) {
      const start = pos.start ?? 0;
      const end = pos.end ?? 0;
      if (start < end) {
        matchRanges.push({ start, end, text: pos.text || "" });
      }
    }
    // Sort by start position
    matchRanges.sort((a, b) => a.start - b.start);
  }

  // Render note header
  const header = (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/50 px-4 py-2">
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
  );

  const fullText = note.text || "";

  // If no match positions, just render text with keyword highlights
  if (matchRanges.length === 0) {
    return (
      <div>
        {header}
        <div
          className="whitespace-pre-wrap px-4 py-3 text-[14px] leading-relaxed text-foreground/60"
          style={noteFont}
        >
          {highlightKeywords(fullText, keywords)}
        </div>
      </div>
    );
  }

  // Build segments: alternate between non-match and match regions
  const segments: React.ReactNode[] = [];
  let cursor = 0;
  let isFirstMatch = true;

  for (const range of matchRanges) {
    // Skip overlapping ranges
    if (range.start < cursor) continue;

    // Non-match region before this match
    if (range.start > cursor) {
      const before = fullText.slice(cursor, range.start);
      segments.push(
        <span key={`pre-${cursor}`} className="text-foreground/50">
          {highlightKeywords(before, keywords)}
        </span>
      );
    }

    // Matched sentence region
    const matched = fullText.slice(range.start, range.end);
    const refProp = isFirstMatch ? { ref: firstMatchRef } : {};
    segments.push(
      <span
        key={`match-${range.start}`}
        {...refProp}
        className="rounded bg-primary/15 px-0.5 text-foreground ring-1 ring-primary/30"
      >
        {highlightKeywords(matched, keywords)}
      </span>
    );
    isFirstMatch = false;
    cursor = range.end;
  }

  // Trailing non-match text
  if (cursor < fullText.length) {
    segments.push(
      <span key={`post-${cursor}`} className="text-foreground/50">
        {highlightKeywords(fullText.slice(cursor), keywords)}
      </span>
    );
  }

  return (
    <div>
      {header}
      <div
        className="whitespace-pre-wrap px-4 py-3 text-[14px] leading-relaxed"
        style={noteFont}
        role="region"
        aria-label="Clinical note with highlighted matches"
      >
        {segments}
      </div>
    </div>
  );
}
