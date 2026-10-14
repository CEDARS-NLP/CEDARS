import type { SearchQueryItem } from "@/projects/types";

export interface QueryRevision {
  id: string;
  query: string;
  source_queries: SearchQueryItem[];
  exclude_negated: boolean;
  revision: number;
}

export interface EventDefinition {
  event_name: string;
  event_description: string;
  include_criteria: string;
  exclude_criteria: string;
}

export interface PromptRevision extends EventDefinition {
  id: string;
  llm_provider: string | null;
  llm_model: string | null;
  revision: number;
}

export interface EvaluationAttempt {
  id: string;
  sequence: number;
  query_id: string;
  prompt_revision_id: string | null;
  mode: "search" | "llm";
  scope: "sample" | "full";
  status: string;
  metrics: Record<string, unknown> | null;
  created_at: string;
  query_revision: QueryRevision;
  prompt_revision: PromptRevision | null;
  pipeline_run_id?: string | null;
  progress?: Record<string, unknown> | null;
  error_message?: string | null;
}

export interface MatchedNote {
  note_id: string;
  patient_id: string;
  text: string;
  note_date: string | null;
  matches: { token: string; note_start_index: number; note_end_index: number }[];
  sentences: { text: string; [key: string]: unknown }[];
}

export interface AttemptMatches {
  notes: MatchedNote[];
  total_notes: number;
  page: number;
  total_pages: number;
}

export interface EvaluationState {
  query_revision: QueryRevision | null;
  prompt_revision: PromptRevision | null;
  attempts: EvaluationAttempt[];
}

export interface AttemptResult {
  id: string | number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_confidence?: number | null;
  predicted_score?: number | null;
  finding_reasoning: string | null;
  finding_evidence: { note_id: string; text: string; note_date?: string | null }[] | null;
  review_judgment: string | null;
}

export const isAttemptRunning = (attempt: EvaluationAttempt) =>
  ["pending", "queued", "running", "processing"].includes(attempt.status);

export const isSuccessfulResult = (result: AttemptResult) =>
  ["completed", "success", "succeeded"].includes(result.status.toLowerCase());