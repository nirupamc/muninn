// Backend API DTOs — shape matches app/schemas/* and app/models/memory.py.

export type MemoryType =
  | "fact"
  | "preference"
  | "project"
  | "goal"
  | "decision"
  | "event"
  | "relationship"
  | "procedure"
  | "other";

export type MemoryStatus = "active" | "superseded" | "invalidated" | "archived";

export interface MemoryRead {
  id: string;
  namespace: string;
  user_id: string | null;
  agent_id: string | null;
  content: string;
  memory_type: MemoryType;
  importance: number;
  confidence: number;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  valid_from: string | null;
  valid_until: string | null;
  source_event_id: string | null;
  metadata: Record<string, unknown>;
}

export interface MemorySearchResult {
  memory: MemoryRead;
  score: number;
}

export interface MemorySearchResponse {
  query: string;
  namespace: string;
  count: number;
  results: MemorySearchResult[];
}

export interface TemporalRecordRead {
  id: string;
  event_id: string;
  admission_id: string | null;
  dedup_decision_id: string | null;
  candidate_content: string;
  candidate_memory_type: string;
  matched_memory_id: string | null;
  created_memory_id: string | null;
  relationship: string;
  relationship_confidence: number | null;
  similarity_score: number | null;
  reason_codes: string[];
  old_status: string | null;
  new_old_status: string | null;
  old_valid_until_before: string | null;
  old_valid_until_after: string | null;
  new_valid_from: string | null;
  provider: string;
  model_name: string;
  created_at: string;
}

export interface MemoryHistoryResponse {
  memory_id: string;
  temporal_decisions: TemporalRecordRead[];
}

export interface EventRead {
  id: string;
  namespace: string;
  user_id: string | null;
  agent_id: string | null;
  session_id: string | null;
  role: "user" | "assistant" | "system" | "tool" | "other";
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ConsolidationSourceRead {
  memory_id: string;
  content: string;
  memory_type: MemoryType;
}

export interface ConsolidationRead {
  consolidation_id: string;
  created_memory_id: string;
  namespace: string;
  user_id: string | null;
  provider: string;
  provider_model: string;
  confidence: number;
  reason: string;
  created_at: string;
  sources: ConsolidationSourceRead[];
}

export interface ContextRequest {
  query: string;
  namespace: string;
  user_id?: string | null;
  agent_id?: string | null;
  token_budget?: number;
  max_candidates?: number;
  max_memories?: number;
  memory_types?: MemoryType[] | null;
  include_superseded?: boolean;
  as_of?: string | null;
}

export interface ContextMemoryUsed {
  memory_id: string;
  memory_type: MemoryType;
  content: string;
  semantic_score: number;
  importance: number;
  confidence: number;
  recency_score: number;
  type_relevance: number;
  reinforcement_score: number;
  final_score: number;
  estimated_tokens: number;
  reason_codes: string[];
}

export interface ContextResponse {
  query: string;
  namespace: string;
  context: string;
  token_budget: number;
  estimated_tokens: number;
  truncated: boolean;
  memories_used: ContextMemoryUsed[];
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface ConsolidatedFromResponse {
  // shape mirrors consolidation source links; kept loose
  derived_memory_id: string;
  sources: { memory_id: string; content: string }[];
}

// M8 — Project & Capture types

export type ProjectStatus = "DISCOVERED" | "CONNECTED" | "MEMORIZED" | "ACTIVE" | "DISABLED";

export interface ProjectRead {
  id: string;
  name: string;
  namespace: string;
  root_path: string;
  canonical_path: string;
  git_root: string | null;
  remote_url: string | null;
  default_branch: string | null;
  status: ProjectStatus;
  capture_enabled: boolean;
  discovered_at: string;
  last_activity_at: string | null;
  metadata: Record<string, unknown>;
  ignored: boolean;
  discovery_source: string | null;
  discovery_evidence: string[];
  last_discovered_at: string | null;
  memory_count: number;
}

export interface ProjectListResponse {
  projects: ProjectRead[];
  total: number;
}

export interface DriveReportRead {
  root_path: string;
  drive_type: string;
  status: "scanned" | "skipped" | "unavailable";
  reason: string | null;
}

export interface SkippedCandidateRead {
  path: string;
  reason: string;
}

export interface ProjectScanResponse {
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  drives: DriveReportRead[];
  roots_scanned: string[];
  directories_considered: number;
  directories_skipped: number;
  skipped_by_reason: Record<string, number>;
  permission_errors: number;
  max_depth_reached: number;
  projects_found: number;
  projects_new_count: number;
  projects_existing_count: number;
  discovered: ProjectRead[];
  existing: ProjectRead[];
  skipped_candidates: SkippedCandidateRead[];
}

export interface DiscoveryStatusResponse {
  scan_in_progress: boolean;
  last_scan: Partial<ProjectScanResponse> & { started_at?: string; finished_at?: string | null } | null;
}

export interface ProjectActivityResponse {
  project_id: string;
  namespace: string;
  last_activity_at: string | null;
  status: string;
  capture_enabled: boolean;
  recent_captures: CaptureEventRead[];
}

export type CaptureSource =
  | "git"
  | "filesystem"
  | "codex"
  | "kilo"
  | "opencode"
  | "generic"
  | "manual";

export type CaptureEventType =
  | "project_discovered"
  | "git_commit"
  | "git_branch_change"
  | "file_batch_changed"
  | "agent_session_started"
  | "agent_session_finished"
  | "agent_summary"
  | "agent_decision"
  | "agent_tool_result"
  | "manual_note";

export type CaptureProcessingStatus = "pending" | "processing" | "completed" | "failed";

export type AdmissionDecision = "STORE" | "IGNORE";

export interface CaptureEventRead {
  id: string;
  project_id: string;
  namespace: string;
  source: CaptureSource;
  event_type: CaptureEventType;
  agent_id: string | null;
  session_id: string | null;
  working_directory: string | null;
  content: string;
  metadata: Record<string, unknown>;
  fingerprint: string;
  occurred_at: string;
  captured_at: string;
  processing_status: CaptureProcessingStatus;
  memory_event_id: string | null;
  memory_id: string | null;
  admission_decision: AdmissionDecision | null;
  error: string | null;
}

export interface CaptureStatusResponse {
  projects_with_capture: number;
  total_capture_events: number;
  pending_events: number;
  adapter_health: Record<string, AdapterHealthRead[]>;
}

export interface AdapterHealthRead {
  name: string;
  available: boolean;
  last_check: string;
  error: string | null;
  metadata: Record<string, unknown> | null;
}
