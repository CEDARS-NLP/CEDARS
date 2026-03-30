import { useMemo } from "react";

interface EvidenceSpan {
  text: string;
  start_pos: number;
  end_pos: number;
  match_source: string;
}

interface EvidenceHighlighterProps {
  noteText: string;
  evidence: EvidenceSpan[];
}

/** Highlight evidence spans within a clinical note. */
export default function EvidenceHighlighter({ noteText, evidence }: EvidenceHighlighterProps) {
  const segments = useMemo(() => {
    if (!evidence.length) return [{ text: noteText, isEvidence: false, source: "" }];

    // Sort spans by start_pos, merge overlapping
    const sorted = [...evidence].sort((a, b) => a.start_pos - b.start_pos);
    const merged: { start: number; end: number; source: string }[] = [];
    for (const span of sorted) {
      const last = merged[merged.length - 1];
      if (last && span.start_pos <= last.end) {
        last.end = Math.max(last.end, span.end_pos);
      } else {
        merged.push({ start: span.start_pos, end: span.end_pos, source: span.match_source });
      }
    }

    const result: { text: string; isEvidence: boolean; source: string }[] = [];
    let cursor = 0;
    for (const { start, end, source } of merged) {
      if (start > cursor) {
        result.push({ text: noteText.slice(cursor, start), isEvidence: false, source: "" });
      }
      result.push({ text: noteText.slice(start, end), isEvidence: true, source });
      cursor = end;
    }
    if (cursor < noteText.length) {
      result.push({ text: noteText.slice(cursor), isEvidence: false, source: "" });
    }
    return result;
  }, [noteText, evidence]);

  return (
    <div
      className="text-[15px] leading-relaxed"
      style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
    >
      {segments.map((seg, i) =>
        seg.isEvidence ? (
          <mark
            key={i}
            className="rounded-sm bg-amber-200 px-0.5 font-medium text-amber-950 dark:bg-amber-500/30 dark:text-amber-100"
            title={`Matched by: ${seg.source}`}
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i} className="text-foreground/60">
            {seg.text}
          </span>
        )
      )}
    </div>
  );
}
