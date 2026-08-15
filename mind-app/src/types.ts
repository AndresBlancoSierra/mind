export type ProjectStatus =
  | 'created'
  | 'discovering'
  | 'completed'
  | 'cancelled'
  | 'failed';

export interface ProjectStats {
  search_results: number;
  candidates: number;
  downloaded: number;
  valid_pdfs: number;
  duplicates_removed: number;
  text_extracted: number;
  ocr_required: number;
  accepted: number;
  review: number;
  rejected: number;
}

export interface Project {
  id: number;
  slug: string;
  topic: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  stats: ProjectStats;
  run_id: number | null;
  run_status: string;
}

export interface StageStatus {
  name: string;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface LogEntry {
  id: number;
  level: string;
  message: string;
  created_at: string;
}

export interface RunProgress {
  run_id: number;
  status: string;
  current_stage: string;
  stages: StageStatus[];
  stats: ProjectStats;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  logs: LogEntry[];
}

export type SourceStatus =
  | 'discovered'
  | 'downloading'
  | 'downloaded'
  | 'failed'
  | 'validated'
  | 'extracting'
  | 'extracted'
  | 'ocr_required'
  | 'filtering'
  | 'accepted'
  | 'review'
  | 'rejected'
  | 'duplicate'
  | 'rejected_validation';

export interface Source {
  id: number;
  title: string;
  url: string;
  snippet: string;
  source_domain: string;
  search_query: string;
  discovered_at: string;
  status: SourceStatus;
  rejection_reason: string | null;
  file_size: number | null;
  content_type: string;
  page_count: number | null;
  language: string;
  text_chars: number | null;
  extraction_method: string;
  similarity: number | null;
  ai_decision: 'ACCEPT' | 'REJECT' | 'REVIEW' | '';
  ai_confidence: number | null;
  ai_document_type: string;
  ai_topic_match: string;
  ai_reason: string;
  embedding_stage: string;
  note: string;
  metadata: Record<string, unknown>;
  has_processed: boolean;
  content?: string;
}

export interface SourcesResponse {
  total: number;
  items: Source[];
  stats: ProjectStats;
}

export interface RuntimeStatus {
  gpu: string;
  vram?: string;
  driver?: string;
  runtime: string;
  runtime_up: string;
  model: string;
  model_installed: string;
  embedding_model: string;
  embedding_model_installed: string;
  installed_models: string;
  python_runtime: string;
}
