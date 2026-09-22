/**
 * One vocabulary for session state, shared by the list and the session page.
 *
 * The two pages had drifted apart: the list said "Reviewing" in blue where the
 * session page said "REVIEWING" in yellow. Both sets of colours were also only
 * legible on the dark theme.
 */

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  reviewing: "In review",
  committed: "Committed",
  completed: "Complete",
  discarded: "Discarded",
};

export const STATUS_STYLES: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  reviewing: "bg-primary/15 text-primary",
  committed: "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300",
  completed: "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300",
  discarded: "bg-muted text-muted-foreground",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
