import type { ReactNode } from "react";
import { Check, ChevronDown, Lock } from "lucide-react";

export type StepState = "done" | "current" | "todo" | "locked";

interface StepCardProps {
  /** 1-based position. This workflow is a real sequence, so the number earns its place. */
  index: number;
  title: string;
  state: StepState;
  /** Factual one-liner shown when collapsed — what this step currently holds. */
  summary?: ReactNode;
  /** Why the step can't be opened yet. Shown in place of the summary when locked. */
  lockedReason?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/**
 * One stage of the evaluation workflow.
 *
 * Collapsed steps state their result in a single line; only the open step shows
 * controls. This is the whole point of the redesign — the previous page rendered
 * seven peer sections at once, so a first-time user had no idea what to do next.
 */
export default function StepCard({
  index,
  title,
  state,
  summary,
  lockedReason,
  open,
  onToggle,
  children,
}: StepCardProps) {
  const locked = state === "locked";

  return (
    <section
      className={`rounded-lg border transition-colors ${
        state === "current" && !open
          ? "border-primary/40"
          : locked
          ? "border-border/50"
          : "border-border"
      } ${open ? "bg-card" : "bg-card/50"}`}
    >
      <button
        type="button"
        onClick={locked ? undefined : onToggle}
        aria-expanded={open}
        disabled={locked}
        className={`flex w-full items-center gap-3 px-4 py-3 text-left ${
          locked ? "cursor-not-allowed" : "cursor-pointer"
        }`}
      >
        <StepMarker index={index} state={state} />

        <div className="min-w-0 flex-1">
          <div
            className={`text-sm font-semibold ${
              locked ? "text-muted-foreground" : "text-foreground"
            }`}
          >
            {title}
          </div>
          {!open && (
            <div className="truncate text-xs text-muted-foreground">
              {locked ? lockedReason : summary}
            </div>
          )}
        </div>

        {!locked && (
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
              open ? "" : "-rotate-90"
            }`}
          />
        )}
      </button>

      {open && !locked && (
        <div className="border-t border-border px-4 py-4">{children}</div>
      )}
    </section>
  );
}

function StepMarker({ index, state }: { index: number; state: StepState }) {
  const base =
    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums";

  if (state === "done") {
    return (
      <span
        className={`${base} bg-emerald-600 text-white dark:bg-emerald-500`}
        aria-label="Step complete"
      >
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
    );
  }
  if (state === "locked") {
    return (
      <span className={`${base} bg-muted text-muted-foreground`} aria-hidden>
        <Lock className="h-3 w-3" />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span className={`${base} bg-primary text-primary-foreground`}>{index}</span>
    );
  }
  return (
    <span className={`${base} border border-border text-muted-foreground`}>
      {index}
    </span>
  );
}
