export type ProjectRole = "investigator" | "admin" | "annotator";

export interface ProjectDetail {
  id: string;
  name: string;
  description: string;
  owner: string;
  role: ProjectRole;
  created_at: string;
}

export interface ProjectMember {
  username: string;
  role: ProjectRole;
  added_by: string;
}

export interface EvidenceSpan {
  text: string;
  start_pos: number;
  end_pos: number;
  match_source?: string | string[];
}

export interface AnnotationView {
  pos_start: number;
  total_pos: number;
  patient_id: string;
  note_id: string;
  note_date: string | null;
  event_date: string | null;
  note_comment: string;
  tags: string[];
  full_note: string;
  full_note_evidence: EvidenceSpan[];
  sentence: string;
  sentence_evidence: EvidenceSpan[];
}

export interface PatientSummary {
  patient_id: string;
  status: "new" | "nlp_processing" | "nlp_complete" | "reviewing" | "reviewed" | string;
  total_notes: number;
  reviewed_notes: number;
  last_updated_at: string | null;
}

export interface PatientListResponse {
  items: PatientSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface NoteView {
  id: string;
  patient_id: string;
  note_date: string | null;
  text: string;
  source_ref?: string | null;
  created_at?: string | null;
}

export interface AnnotationListItem {
  annotation_id: number;
  patient_id: string;
  note_id: string;
  note_date: string | null;
  status: "U" | "R" | "S" | string;
  sentence: string;
  task_id?: number | null;
  reviewed_by?: string | null;
  created_at?: string | null;
}

export interface AnnotationListResponse {
  items: AnnotationListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface NlpStatus {
  total_patients: number;
  tasks_in_progress: number;
  tasks_completed: number;
  tasks_failed: number;
  pines_pending: number;
  pines_running: number;
  pines_succeeded: number;
  pines_failed: number;
}

export interface NlpRunSummary {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  total_patients: number;
  completed_patients: number;
  failed_patients: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskSummary {
  task_id: number;
  job_id: string;
  patient_id: string | null;
  run_id: string | null;
  name: string;
  complete: boolean;
  progress: number;
  failed: boolean;
}

export interface BackgroundJobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  progress: number;
  total: number;
  done: number;
  failed: number;
  result_summary?: Record<string, unknown> | null;
}

export interface StatsOut {
  number_of_patients: number;
  number_of_annotated_patients: number;
  number_of_reviewed: number;
  lemma_dist: Record<string, number>;
  user_review_stats: Record<string, number>;
}
