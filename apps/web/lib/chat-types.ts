export type HealthState = "checking" | "online" | "offline";

export type ApiHealthResponse = {
  status: string;
  websocket_url?: string;
};

export type ComposerPoolName = "ccf_a" | "ccf_b" | "other";

export type ComposerDecision = {
  action?: string;
  paper_id: string;
  pool: ComposerPoolName;
  rationale: string;
  evidence_refs: string[];
  attachment_point: string | null;
  compatibility_notes: string | null;
};

export type ComposerPlan = {
  current_step?: string;
  report_ready?: boolean;
  baseline: ComposerDecision | null;
  accepted_modules: ComposerDecision[];
};

export type ComposerProposalIssue = {
  code: string;
  severity: string;
  message: string;
  evidence: string | null;
};

export type ComposerProposalCheck = {
  method: string;
  passed: boolean;
  issues: ComposerProposalIssue[];
  removed_process_chatter: string[];
  counts: Record<string, number>;
};

export type ChatResponse = {
  request: string;
  report_markdown: string;
  session_path: string;
  report_path: string;
  quality_run_path: string | null;
  eval_report_path: string | null;
  termination_reason: string;
  cost_cny: number;
  events_count: number;
  paper_budget: Record<string, unknown>;
  composer_plan: ComposerPlan | null;
  proposal_check: ComposerProposalCheck | null;
};

export type ReportHistoryResponse = {
  reports: ReportHistoryEntry[];
};

export type DirectorySelectionResponse = {
  path: string | null;
};

export type EvidenceResponse = {
  kind: "chunk" | "field";
  citation_ref: string;
  paper_id: string;
  title: string;
  year: number | null;
  chunk_id: number | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  field: string | null;
  text: string;
};

export type ComposerPaper = {
  pool: ComposerPoolName;
  paper_id: string;
  path: string;
  indexed: boolean;
  title: string;
  year: number | null;
  venue: string | null;
};

export type ComposerPool = {
  count: number;
  indexed_count: number;
  unindexed_count: number;
  papers: ComposerPaper[];
  unindexed_pdfs: ComposerPaper[];
};

export type ComposerLibraryResponse = {
  root: string;
  required_layout: string[];
  optional_layout?: string[];
  flat_root_as_ccf_a: boolean;
  baseline_pool: ComposerPoolName;
  module_pool_order: ComposerPoolName[];
  fallback_rule: string;
  missing_pools: ComposerPoolName[];
  pools: Record<ComposerPoolName, ComposerPool>;
};

export type ReportHistoryEntry = {
  id: string;
  request: string;
  report_markdown: string;
  session_path: string;
  report_path: string;
  updated_at: string;
  termination_reason: string;
  cost_cny: number | null;
  events_count: number | null;
  paper_budget: Record<string, unknown>;
  composer_plan: ComposerPlan | null;
  proposal_check: ComposerProposalCheck | null;
};

export type ChatSessionStatus =
  | "draft"
  | "queued"
  | "running"
  | "completed"
  | "interrupted"
  | "failed";

export type ChatSessionMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type ChatSession = {
  id: string;
  conversationId: string | null;
  title: string;
  status: ChatSessionStatus;
  messages: ChatSessionMessage[];
  run: ChatResponse | null;
  jobId: string | null;
  error: string | null;
  updatedAt: string;
  costCny: number | null;
};

export type ChatJobSpec = {
  request: string;
  conversation_id: string | null;
  pdf_dir: string | null;
  max_turns: number;
  budget_cny: number;
  max_papers: number;
  record_quality: boolean;
  update_report: boolean;
  recovery_mode: "restart_from_request" | "rollout_replay";
};

export type ChatJobAttempt = {
  number: number;
  status: "running" | "completed" | "interrupted" | "failed";
  session_id: string;
  session_path: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  resumed_from_attempt: number | null;
};

export type ChatJobRecord = {
  version: 1;
  id: string;
  status: "queued" | "running" | "completed" | "interrupted" | "failed";
  created_at: string;
  updated_at: string;
  spec: ChatJobSpec;
  attempts: ChatJobAttempt[];
  result: ChatResponse | null;
  error: string | null;
};

export type ChatJobsResponse = {
  jobs: ChatJobRecord[];
};

export type ChatJobEvent = {
  seq: number;
  ts: string;
  type:
    | "created"
    | "started"
    | "progress"
    | "completed"
    | "interrupted"
    | "failed"
    | "resumed";
  status: ChatJobRecord["status"];
  attempt: number;
  message: string;
};

export type ChatJobEventsResponse = {
  events: ChatJobEvent[];
  next_after: number;
};

export type ChatJobStreamPayload = ChatJobEventsResponse & {
  record: ChatJobRecord;
};

export type ChatJobWebsocketNotification = {
  method: "job/events";
  params: ChatJobStreamPayload;
};

export type ChatJobWebsocketResponse = {
  id: number;
  result?: { record: ChatJobRecord };
  error?: { code: string; message: string };
};

export type UsageTip = {
  title: string;
  description: string;
  examples: string[];
};
