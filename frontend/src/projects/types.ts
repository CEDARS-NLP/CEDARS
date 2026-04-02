/** Shared TypeScript interfaces for project pages. */

export interface Predictor {
  id: string;
  project_id: string;
  predictor_type: string;
  name: string;
  config: Record<string, unknown>;
  is_active: boolean;
  created_by: string;
  created_at: string;
}

export interface SearchQuery {
  id: string;
  project_id: string;
  name: string;
  query: string;
  is_active: boolean;
  nlp_apply: boolean;
  hide_duplicates: boolean;
  skip_after_event: boolean;
  created_at: string;
}

export interface NlpStats {
  total_notes: number;
  processed_notes: number;
  total_sentences: number;
  target_sentences: number;
  negated_sentences: number;
}

export interface NlpJob {
  id: string;
  status: string;
  total_notes: number;
  processed_notes: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface PredictionJobStatus {
  job_id: string;
  status: string; // "pending" | "running" | "completed" | "failed" | "cancelled"
  progress: number;
  result_summary: {
    total_sentences?: number;
    predictions_made?: number;
    annotations_created?: number;
    errors?: number;
    patients_processed?: number;
    total_patients?: number;
    token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  } | null;
  is_cancelled?: boolean;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}

export interface BulkEstimate {
  sentence_count: number;
  estimated_prompt_tokens: number;
  estimated_completion_tokens: number;
  estimated_total_tokens: number;
}

// ── Background Job (used by JobBanner) ─────────────────────────

export interface BackgroundJobStatus {
  job_id: string;
  status: string;
  progress: number;
  result_summary: Record<string, unknown> | null;
}

// ── Agentic Pipeline Types ─────────────────────────────────────

export interface PipelineRun {
  id: string;
  project_id: string;
  event_config_id: string;
  run_type: string;
  status: string;
  config_snapshot: Record<string, unknown>;
  sample_size: number | null;
  total_patients: number;
  processed_patients: number;
  failed_patients: number;
  is_cancelled: boolean;
  result_summary: Record<string, unknown> | null;
  created_by: string;
  snapshot_version: number;
  created_at: string;
  updated_at: string;
}

export interface PipelineRunStats {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  no_match: number;
}

export interface PatientTaskSummary {
  id: number;
  pipeline_run_id: string;
  patient_id: string;
  status: string;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ProjectStats {
  patients: {
    total: number;
    by_status: Record<string, number>;
  };
  notes: { total: number };
  sentences: { total: number; target: number; negated: number };
  annotations: {
    total: number;
    reviewed: number;
    unreviewed: number;
    skipped: number;
    events_found: number;
  };
  annotators: {
    user_id: string;
    email: string;
    name: string;
    reviewed_count: number;
    events_found: number;
  }[];
  jobs: {
    latest: {
      id: string;
      job_type: string;
      status: string;
      progress: number;
      started_at: string | null;
      completed_at: string | null;
    } | null;
    active_count: number;
    failed_count: number;
  };
}

// ── Unified Evaluation Session Types ─────────────────────────────

export type UnifiedSessionStatus = "draft" | "reviewing" | "committed" | "completed" | "discarded";

export interface SearchQueryItem {
  query: string;
  type: "include" | "exclude";
}

export interface UnifiedSession {
  id: string;
  project_id: string;
  status: UnifiedSessionStatus;
  search_queries: SearchQueryItem[];
  event_name: string | null;
  event_description: string | null;
  include_criteria: string | null;
  exclude_criteria: string | null;
  sample_size: number;
  metrics: UnifiedMetrics | null;
  committed_config: Record<string, unknown> | null;
  committed_at: string | null;
  cloned_from_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface UnifiedSessionListItem {
  id: string;
  project_id: string;
  status: UnifiedSessionStatus;
  search_queries: SearchQueryItem[];
  event_name: string | null;
  sample_size: number;
  metrics: UnifiedMetrics | null;
  committed_at: string | null;
  created_at: string;
}

export interface UnifiedMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  total_reviewed: number;
  total_pending: number;
  llm_status?: "running" | "completed" | "failed";
  llm_total?: number;
  llm_completed?: number;
  llm_failed?: number;
  llm_no_match?: number;
}

export interface FunnelStats {
  sample_patients: number;
  sample_notes: number;
  matched_patients: number;
  matched_notes: number;
  filter_percent: number;
  llm_positive: number | null;
  llm_negative: number | null;
  llm_inconclusive: number | null;
  estimated_cost: number | null;
}

export interface MatchPosition {
  start: number;
  end: number;
  token?: string;
  text?: string;
  sentence_number?: number;
}

export interface NoteSearchMatch {
  id: number;
  patient_id: string;
  note_id: string;
  matched_tokens: string[];
  match_positions: MatchPosition[];
  is_negated: boolean;
}

export interface NoteWithMatches {
  note_id: string;
  patient_id: string;
  note_text: string;
  note_date: string | null;
  note_type: string | null;
  matches: NoteSearchMatch[];
}

export interface QueryMatchesResult {
  query_index: number;
  query: string;
  query_type: string;
  total_notes: number;
  total_patients: number;
  notes: NoteWithMatches[];
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SuggestedQuery {
  query: string;
  type: "include" | "exclude";
}

export interface PatientResultItem {
  id: number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_reasoning: string | null;
  finding_evidence: { note_id: string; text: string; note_date: string }[] | null;
  event_date: string | null;
  predicted_score: number | null;
  review_judgment: string | null;
  reviewer_date_override: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  notes_searched: number;
  notes_matched: number;
}

export interface PatientResultsPage {
  results: PatientResultItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface UnifiedPipelineStats {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  no_match: number;
  is_cancelled: boolean;
}

export interface CommitResult {
  session: UnifiedSession;
  pipeline_run_id: string;
  total_patients: number;
  estimated_cost: number | null;
}

export interface NextEvalResult {
  id: number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_reasoning: string | null;
  finding_evidence: { note_id: string; text: string; note_date: string }[] | null;
  event_date: string | null;
  predicted_score: number | null;
  review_judgment: string | null;
  reviewer_date_override: string | null;
  notes_searched: number;
  notes_matched: number;
  position: number;
  total_unreviewed: number;
  total_results: number;
}

export interface ResultNoteContext {
  note_id: string;
  text_id: string;
  text: string;
  note_date: string | null;
  note_tags: Record<string, string>;
  matched_tokens: string[];
  match_positions: MatchPosition[];
  is_evidence: boolean;
}

export interface ResultNotesContext {
  patient_id: string;
  patient_id_ext: string | null;
  notes: ResultNoteContext[];
  search_keywords: string[];
}
