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

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface TestResult {
  score: number;
  label: number;
  model: string;
  reasoning: string;
  token_usage: TokenUsage | null;
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

export interface Metrics {
  accuracy?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  tp?: number;
  fp?: number;
  tn?: number;
  fn?: number;
  total_judged?: number;
  total_pending?: number;
  token_usage?: TokenUsage;
}

export interface EvalSession {
  id: string;
  project_id: string;
  predictor_config_id: string;
  name: string;
  status: string;
  sample_config: { size?: number; keyword_match_ratio?: number; keywords?: string[] };
  metrics: Metrics;
  total_notes: number;
  judged_notes: number;
  created_at: string;
  completed_at: string | null;
}

export interface Judgment {
  id: string;
  session_id: string;
  note_id: string;
  predicted_label: number | null;
  predicted_score: number | null;
  reasoning: string;
  judgment: string;
  judged_by: string | null;
  judged_at: string | null;
}

export interface JudgmentWithNote extends Judgment {
  note_text: string;
  note_text_id: string;
  patient_id: string;
}

export interface ValidatedPredictor {
  id: string;
  name: string;
  predictor_config_id: string;
  session_id: string;
  config_snapshot: Record<string, unknown>;
  metrics_snapshot: Metrics;
  threshold: number;
  is_active: boolean;
  created_at: string;
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

export interface PredictorFormState {
  name: string;
  type: "llm" | "pines";
  provider: string;
  model: string;
  apiBase: string;
  apiKey: string;
  pinesUrl: string;
  eventName: string;
  eventDesc: string;
  include: string;
  exclude: string;
}

export const EMPTY_FORM: PredictorFormState = {
  name: "",
  type: "llm",
  provider: "ollama",
  model: "llama3",
  apiBase: "http://localhost:11434",
  apiKey: "",
  pinesUrl: "http://localhost:8000",
  eventName: "",
  eventDesc: "",
  include: "",
  exclude: "",
};

// ── Background Job (used by JobBanner) ─────────────────────────

export interface BackgroundJobStatus {
  job_id: string;
  status: string;
  progress: number;
  result_summary: Record<string, unknown> | null;
}

// ── Agentic Pipeline Types ─────────────────────────────────────

export interface EventConfig {
  id: string;
  project_id: string;
  name: string;
  description: string;
  include_criteria: string;
  exclude_criteria: string;
  search_patterns: {
    keywords?: string[];
    regex_patterns?: string[];
    exclusion_patterns?: string[];
  };
  llm_provider: string;
  llm_model: string;
  llm_api_base: string | null;
  confidence_threshold: number | null;
  is_committed: boolean;
  created_at: string;
  updated_at: string;
}

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

export interface RunMetrics {
  total_reviewed: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  precision: number | null;
  recall: number | null;
  f1_score: number | null;
  suggested_threshold: number | null;
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

export function formFromPredictor(pred: Predictor): PredictorFormState {
  const c = pred.config as Record<string, unknown>;
  const evt = (c.event_definition || {}) as Record<string, string>;
  return {
    name: pred.name,
    type: pred.predictor_type as "llm" | "pines",
    provider: (c.provider as string) || "ollama",
    model: (c.model as string) || "",
    apiBase: (c.api_base as string) || "",
    apiKey: (c.api_key as string) || "",
    pinesUrl: (c.pines_api_url as string) || "http://localhost:8000",
    eventName: evt.name || "",
    eventDesc: evt.description || "",
    include: evt.include_criteria || "",
    exclude: evt.exclude_criteria || "",
  };
}

export function formToPayload(form: PredictorFormState) {
  const config: Record<string, unknown> =
    form.type === "llm"
      ? {
          provider: form.provider,
          model: form.model,
          api_base: form.apiBase || undefined,
          api_key: form.apiKey || undefined,
          event_definition: {
            name: form.eventName,
            description: form.eventDesc,
            include_criteria: form.include,
            exclude_criteria: form.exclude,
          },
        }
      : { pines_api_url: form.pinesUrl };

  return { name: form.name, predictor_type: form.type, config };
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
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_base: string | null;
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
  token: string;
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
