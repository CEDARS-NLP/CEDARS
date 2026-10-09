export interface ReviewMetadata {
  review_source?: "human" | "cedars" | "llm" | null;
  review_reason?: "no_keyword_matches" | "negated_matches_only" |
    "all_keyword_predictions_negative" | "manual_review" | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
}

const sourceLabels = { human: "Human", cedars: "CEDARS", llm: "LLM" };
const reasonLabels = {
  no_keyword_matches: "No keyword matches",
  negated_matches_only: "Negated matches only",
  all_keyword_predictions_negative: "All keyword predictions negative",
  manual_review: "Manual review",
};

export default function ReviewProvenance({ review_source, review_reason, reviewed_by, reviewed_at }: ReviewMetadata) {
  const humanReview = review_source === "human" || (!review_source && !!reviewed_by);
  if (!review_source && !review_reason && !humanReview) return null;

  return (
    <div className="space-y-1 break-words text-xs text-muted-foreground">
      {review_source && <div>Review source: {sourceLabels[review_source]}</div>}
      {review_reason && <div>Review reason: {reasonLabels[review_reason]}</div>}
      {humanReview && reviewed_by && <div>Reviewer ID: {reviewed_by}</div>}
      {humanReview && reviewed_at && (
        <div>Reviewed: {new Date(reviewed_at).toLocaleString(undefined, {
          month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
        }).replace(/AM|PM/g, (period) => period.toLowerCase())}</div>
      )}
    </div>
  );
}