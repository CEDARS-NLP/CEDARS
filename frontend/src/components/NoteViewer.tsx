import { useRef, useEffect } from "react";
import EvidenceHighlighter from "./EvidenceHighlighter";

interface EvidenceSpan {
  text: string;
  start_pos: number;
  end_pos: number;
  match_source: string;
}

interface NoteViewerProps {
  /** Full note text */
  noteText: string;
  /** Evidence spans to highlight */
  evidence?: EvidenceSpan[];
  /** Maximum height before scrolling */
  maxHeight?: string;
}

/** Scrollable note viewer with optional evidence highlighting. */
export default function NoteViewer({
  noteText,
  evidence,
  maxHeight = "20rem",
}: NoteViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll to the first highlighted evidence on mount
  useEffect(() => {
    if (!evidence?.length) return;
    const mark = containerRef.current?.querySelector("mark");
    mark?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [evidence]);

  return (
    <div
      ref={containerRef}
      className="overflow-y-auto rounded-md border border-border bg-muted/30 p-4"
      style={{ maxHeight }}
      role="region"
      aria-label="Clinical note"
    >
      {evidence && evidence.length > 0 ? (
        <EvidenceHighlighter noteText={noteText} evidence={evidence} />
      ) : (
        <p
          className="text-[15px] leading-relaxed text-foreground/60"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
        >
          {noteText}
        </p>
      )}
    </div>
  );
}
