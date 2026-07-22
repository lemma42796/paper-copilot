import type {
  ChatJobRecord,
  ChatResponse,
  ChatSession,
  ChatSessionMessage,
  EvidenceResponse,
  ReportHistoryEntry
} from "./chat-types";

export function chatSessionFromReport(entry: ReportHistoryEntry): ChatSession {
  const run: ChatResponse = {
    request: entry.request,
    report_markdown: entry.report_markdown,
    session_path: entry.session_path,
    report_path: entry.report_path,
    quality_run_path: null,
    eval_report_path: null,
    termination_reason: entry.termination_reason,
    cost_cny: entry.cost_cny ?? 0,
    events_count: entry.events_count ?? 0,
    paper_budget: entry.paper_budget,
    composer_plan: entry.composer_plan ?? null,
    proposal_check: entry.proposal_check ?? null
  };
  return {
    id: entry.session_path,
    conversationId: null,
    title: entry.request,
    status: "completed",
    messages: [
      { id: `${entry.session_path}:user`, role: "user", content: entry.request },
      {
        id: `${entry.session_path}:assistant`,
        role: "assistant",
        content: entry.report_markdown
      }
    ],
    run,
    jobId: null,
    error: null,
    updatedAt: entry.updated_at,
    costCny: entry.cost_cny
  };
}

export function chatSessionsFromJobs(records: ChatJobRecord[]): ChatSession[] {
  const groups = new Map<string, ChatJobRecord[]>();
  for (const record of records) {
    const conversationId = record.spec.conversation_id ?? record.id;
    groups.set(conversationId, [...(groups.get(conversationId) ?? []), record]);
  }
  return [...groups.entries()]
    .map(([conversationId, jobs]) => chatSessionFromJobGroup(conversationId, jobs))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export function chatResponseFromSession(session: ChatSession): ChatResponse | null {
  return session.run;
}

export function isResumeIntent(message: string): boolean {
  const normalized = message
    .trim()
    .toLowerCase()
    .replace(/[，。！？,.!?\s]/g, "");
  return new Set([
    "继续",
    "继续任务",
    "继续刚才的任务",
    "继续刚才中断的任务",
    "继续上次的任务",
    "继续上次中断的任务",
    "恢复任务",
    "恢复刚才的任务",
    "resume",
    "continue"
  ]).has(normalized);
}

export function formatCost(cost: number | null): string {
  return cost === null ? "费用未知" : `¥${cost.toFixed(4)}`;
}

export function formatHistoryTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function formatTermination(reason: string): string {
  switch (reason) {
    case "end_turn":
      return "正常结束";
    case "max_turns":
      return "达到轮数上限";
    case "max_budget_usd":
    case "max_budget_cny":
      return "达到预算上限";
    default:
      return reason;
  }
}

export function formatEvidenceMeta(evidence: EvidenceResponse): string {
  if (evidence.kind === "field") {
    return evidence.field ? `字段 ${evidence.field}` : "字段证据";
  }
  const page =
    evidence.page_start !== null && evidence.page_end !== null
      ? formatPageRange(evidence.page_start, evidence.page_end)
      : "页码未知";
  return `${evidence.section ?? "section unknown"} · ${page} · chunk ${
    evidence.chunk_id ?? "unknown"
  }`;
}

export function isChunkEvidenceRef(ref: string): boolean {
  return /^\[\s*[A-Za-z0-9_-]{3,64}\s*:\s*chunks\[\d+\]\s*\]$/.test(ref);
}

export async function copyText(value: string): Promise<boolean> {
  if (!navigator.clipboard) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function formatPageRange(start: number, end: number): string {
  return start === end ? `p.${start}` : `p.${start}-${end}`;
}

function chatSessionFromJobGroup(
  conversationId: string,
  records: ChatJobRecord[]
): ChatSession {
  const jobs = [...records].sort((left, right) =>
    left.created_at.localeCompare(right.created_at)
  );
  const latest = jobs[jobs.length - 1];
  const messages: ChatSessionMessage[] = [];
  let costCny = 0;
  let hasCost = false;
  for (const job of jobs) {
    messages.push({
      id: `${job.id}:user`,
      role: "user",
      content: job.spec.request
    });
    if (job.result !== null) {
      messages.push({
        id: `${job.id}:assistant`,
        role: "assistant",
        content: job.result.report_markdown
      });
      costCny += job.result.cost_cny;
      hasCost = true;
    }
  }
  return {
    id: conversationId,
    conversationId,
    title: jobs[0].spec.request,
    status: latest.status,
    messages,
    run: latest.result,
    jobId: latest.id,
    error: latest.error,
    updatedAt: latest.updated_at,
    costCny: hasCost ? costCny : null
  };
}
