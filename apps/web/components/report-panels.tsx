"use client";

import type {
  ChatResponse,
  ComposerDecision,
  ComposerLibraryResponse,
  ComposerPool,
  ComposerPoolName,
  EvidenceResponse
} from "../lib/chat-types";
import {
  copyText,
  formatCost,
  formatEvidenceMeta,
  formatTermination,
  isChunkEvidenceRef
} from "../lib/report-adapter";
import { renderInlineText } from "./markdown-report";

export function LoadingReport({ message }: { message: string | null }) {
  return (
    <div className="loading-report">
      <div className="loading-spinner" aria-hidden="true" />
      <div>
        <h2>正在研究</h2>
        <p>{message ?? "正在读取本地资料并组织回答。"}</p>
      </div>
    </div>
  );
}

export function ReportToolbar({
  onCopy,
  onRefresh,
  result
}: {
  onCopy: (value: string, label: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  result: ChatResponse;
}) {
  return (
    <div className="report-toolbar">
      <div className="report-toolbar-text">
        <p className="report-subtitle">本次运行 · {formatCost(result.cost_cny)}</p>
      </div>
      <div className="report-toolbar-actions">
        <button className="secondary-button" onClick={() => void onRefresh()} type="button">
          刷新历史
        </button>
        <button
          className="secondary-button"
          onClick={() => void onCopy(result.report_path, "报告路径")}
          type="button"
        >
          复制报告路径
        </button>
        <button
          className="secondary-button"
          onClick={() => void onCopy(result.session_path, "会话路径")}
          type="button"
        >
          复制会话路径
        </button>
      </div>
    </div>
  );
}

export function RunMetadata({
  jobProgress,
  jobStatus,
  onCopy,
  result
}: {
  jobProgress: string | null;
  jobStatus: "queued" | "running" | "completed" | "interrupted" | "failed" | null;
  onCopy: (value: string, label: string) => Promise<void>;
  result: ChatResponse | null;
}) {
  if (result === null) {
    return (
      <section className="metadata">
        <h2>运行</h2>
        <dl>
          <div>
            <dt>状态</dt>
            <dd>{formatJobStatus(jobStatus)}</dd>
          </div>
          {jobProgress ? (
            <div>
              <dt>最新进度</dt>
              <dd title={jobProgress}>{jobProgress}</dd>
            </div>
          ) : null}
        </dl>
      </section>
    );
  }

  return (
    <section className="metadata">
      <h2>运行</h2>
      <dl>
        <MetaItem label="停止原因" value={formatTermination(result.termination_reason)} />
        <MetaItem label="费用" value={`¥${result.cost_cny.toFixed(4)}`} />
        <MetaItem label="事件数" value={String(result.events_count)} />
        <MetaItem copyable label="会话" onCopy={onCopy} value={result.session_path} />
        <MetaItem copyable label="报告" onCopy={onCopy} value={result.report_path} />
        <MetaItem
          copyable
          label="质量记录"
          onCopy={onCopy}
          value={result.quality_run_path ?? "未记录"}
        />
        <MetaItem
          copyable
          label="评估报告"
          onCopy={onCopy}
          value={result.eval_report_path ?? "未更新"}
        />
      </dl>
    </section>
  );
}

function formatJobStatus(
  status: "queued" | "running" | "completed" | "interrupted" | "failed" | null
): string {
  switch (status) {
    case "queued":
      return "等待执行";
    case "running":
      return "正在运行";
    case "completed":
      return "已完成";
    case "interrupted":
      return "已中断";
    case "failed":
      return "执行失败";
    case null:
      return "空闲";
  }
}

export function ComposerSummary({
  onCopy,
  onEvidenceRefClick,
  result
}: {
  onCopy: (value: string, label: string) => Promise<void>;
  onEvidenceRefClick: (ref: string) => void | Promise<void>;
  result: ChatResponse | null;
}) {
  const plan = result?.composer_plan ?? null;
  const check = result?.proposal_check ?? null;
  const riskItems =
    result === null ? [] : extractMarkdownSectionItems(result.report_markdown, ["风险与缺口"]);
  const visibleRiskItems = riskItems.slice(0, 5);
  const hiddenRiskCount = riskItems.length - visibleRiskItems.length;
  if (plan === null && check === null) {
    return null;
  }

  const modules = plan?.accepted_modules ?? [];
  const distinctModuleCount = new Set(modules.map((module) => module.paper_id)).size;
  const acceptedModuleCount = check?.counts.accepted_module_count ?? modules.length;
  const requiredModuleCount = 3;
  const distinctOk =
    acceptedModuleCount === requiredModuleCount && distinctModuleCount === acceptedModuleCount;

  return (
    <section className="composer-summary">
      <div className="composer-summary-header">
        <h2>Composer</h2>
        <span className={check?.passed ? "status-pill passed" : "status-pill"}>
          {check === null ? "未检查" : check.passed ? "通过" : "需处理"}
        </span>
      </div>

      <div className="composer-check-grid">
        <ComposerCheckMetric label="模块" value={`${acceptedModuleCount}/${requiredModuleCount}`} />
        <ComposerCheckMetric label="来源" value={distinctOk ? "不同 paper" : "需核查"} />
        <ComposerCheckMetric
          label="未支撑细节"
          value={String(check?.counts.unsupported_specific_count ?? 0)}
        />
      </div>

      {plan?.baseline ? (
        <ComposerDecisionSummary
          decision={plan.baseline}
          label="Baseline"
          onCopy={onCopy}
          onEvidenceRefClick={onEvidenceRefClick}
        />
      ) : (
        <p className="settings-note">尚未记录 baseline。</p>
      )}

      {modules.length > 0 ? (
        <div className="composer-module-list">
          {modules.map((module, index) => (
            <ComposerDecisionSummary
              decision={module}
              key={`${module.paper_id}-${index}`}
              label={`Module ${index + 1}`}
              onCopy={onCopy}
              onEvidenceRefClick={onEvidenceRefClick}
            />
          ))}
        </div>
      ) : null}

      {check && check.issues.length > 0 ? (
        <div className="composer-issues">
          <p>质量检查问题</p>
          <ul>
            {check.issues.map((issue) => (
              <li key={`${issue.code}-${issue.evidence ?? issue.message}`}>
                <strong>{issue.code}</strong>
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="settings-note">质量检查无 issues。</p>
      )}

      {visibleRiskItems.length > 0 ? (
        <div className="composer-risks">
          <p>风险与缺口</p>
          <ul>
            {visibleRiskItems.map((item, index) => (
              <li key={`${item}-${index}`}>{renderInlineText(item, onEvidenceRefClick)}</li>
            ))}
          </ul>
          {hiddenRiskCount > 0 ? (
            <p className="settings-note">另有 {hiddenRiskCount} 条见报告正文。</p>
          ) : null}
        </div>
      ) : (
        <p className="settings-note">报告正文未提取到风险与缺口小节。</p>
      )}
    </section>
  );
}

export function EvidenceInspector({
  error,
  evidence,
  isLoading,
  onCopy
}: {
  error: string | null;
  evidence: EvidenceResponse | null;
  isLoading: boolean;
  onCopy: (value: string, label: string) => Promise<void>;
}) {
  return (
    <section className="evidence-panel">
      <h2>证据</h2>
      {isLoading ? <p className="settings-note">正在打开证据。</p> : null}
      {error ? <p className="evidence-error">{error}</p> : null}
      {evidence ? (
        <div className="evidence-card">
          <div className="evidence-card-header">
            <p>{evidence.title || evidence.paper_id}</p>
            <button
              className="copy-button"
              onClick={() => void onCopy(evidence.citation_ref, "证据引用")}
              type="button"
            >
              复制
            </button>
          </div>
          <p className="evidence-meta">
            {evidence.year ? `${evidence.year} · ` : ""}
            {formatEvidenceMeta(evidence)}
          </p>
          <pre>{evidence.text}</pre>
        </div>
      ) : !isLoading && !error ? (
        <p className="settings-note">点击报告中的证据引用查看字段详情或 chunk 原文。</p>
      ) : null}
    </section>
  );
}

export function ComposerLibraryPanel({
  error,
  isLoading,
  onRefresh,
  status
}: {
  error: string | null;
  isLoading: boolean;
  onRefresh: () => Promise<void>;
  status: ComposerLibraryResponse | null;
}) {
  return (
    <section className="library-status" aria-label="资料库状态">
      <div className="library-status-header">
        <h3>资料库状态</h3>
        <button className="copy-button" onClick={() => void onRefresh()} type="button">
          刷新
        </button>
      </div>
      {isLoading ? <p className="settings-note">正在检查资料库。</p> : null}
      {error ? <p className="library-status-error">{error}</p> : null}
      {status ? (
        <>
          <p className="settings-note">
            {status.flat_root_as_ccf_a
              ? "当前目录直接作为 CCF A 资料池。"
              : "当前目录使用 ccf_a / ccf_b / other 分层。"}
          </p>
          <div className="pool-summary-grid">
            {(["ccf_a", "ccf_b", "other"] as ComposerPoolName[]).map((poolName) => (
              <PoolSummary
                isBaseline={poolName === status.baseline_pool}
                key={poolName}
                name={poolName}
                pool={status.pools[poolName]}
              />
            ))}
          </div>
          <p className="pool-rule">
            模块优先级: {status.module_pool_order.map(formatComposerPoolName).join(" -> ")}
          </p>
        </>
      ) : !isLoading && !error ? (
        <p className="settings-note">连接本地 API 后显示 CCF A / CCF B / Other 状态。</p>
      ) : null}
    </section>
  );
}

function ComposerCheckMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="composer-check-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ComposerDecisionSummary({
  decision,
  label,
  onCopy,
  onEvidenceRefClick
}: {
  decision: ComposerDecision;
  label: string;
  onCopy: (value: string, label: string) => Promise<void>;
  onEvidenceRefClick: (ref: string) => void | Promise<void>;
}) {
  return (
    <div className="composer-decision">
      <div className="composer-decision-top">
        <span>{label}</span>
        <button
          className="copy-button"
          onClick={() => void onCopy(decision.paper_id, "paper_id")}
          type="button"
        >
          {decision.paper_id}
        </button>
      </div>
      <p className="composer-decision-meta">{formatComposerPoolName(decision.pool)}</p>
      <p>{decision.rationale}</p>
      {decision.attachment_point ? (
        <p className="composer-decision-detail">接入点: {decision.attachment_point}</p>
      ) : null}
      {decision.compatibility_notes ? (
        <p className="composer-decision-detail">兼容性: {decision.compatibility_notes}</p>
      ) : null}
      <EvidenceRefButtons refs={decision.evidence_refs} onEvidenceRefClick={onEvidenceRefClick} />
    </div>
  );
}

function EvidenceRefButtons({
  onEvidenceRefClick,
  refs
}: {
  onEvidenceRefClick: (ref: string) => void | Promise<void>;
  refs: string[];
}) {
  if (refs.length === 0) {
    return null;
  }
  return (
    <div className="composer-ref-list">
      {refs.map((ref) => (
        <button
          className="evidence-ref composer-ref"
          key={ref}
          onClick={() => void onEvidenceRefClick(ref)}
          title={isChunkEvidenceRef(ref) ? "打开证据原文" : "打开字段证据"}
          type="button"
        >
          {ref}
        </button>
      ))}
    </div>
  );
}

function PoolSummary({
  isBaseline,
  name,
  pool
}: {
  isBaseline: boolean;
  name: ComposerPoolName;
  pool: ComposerPool;
}) {
  return (
    <div className="pool-summary">
      <div className="pool-summary-top">
        <span>{formatComposerPoolName(name)}</span>
        {isBaseline ? <small>baseline</small> : null}
      </div>
      <strong>{pool.count}</strong>
      <p>
        indexed {pool.indexed_count}
        {pool.unindexed_count > 0 ? ` / unread ${pool.unindexed_count}` : ""}
      </p>
    </div>
  );
}

function MetaItem({
  copyable = false,
  label,
  onCopy,
  value
}: {
  copyable?: boolean;
  label: string;
  onCopy?: (value: string, label: string) => Promise<void>;
  value: string;
}) {
  const canCopy = copyable && value !== "未记录" && value !== "未更新";

  return (
    <div className="metadata-item">
      <dt>{label}</dt>
      <div className="metadata-value-row">
        <dd title={value}>{value}</dd>
        {canCopy ? (
          <button
            className="copy-button"
            onClick={() => void (onCopy ? onCopy(value, label) : copyText(value))}
            title={`复制${label}路径`}
            type="button"
          >
            复制
          </button>
        ) : null}
      </div>
    </div>
  );
}

function formatComposerPoolName(pool: ComposerPoolName): string {
  switch (pool) {
    case "ccf_a":
      return "CCF A";
    case "ccf_b":
      return "CCF B";
    case "other":
      return "Other";
  }
}

function extractMarkdownSectionItems(markdown: string, headings: string[]): string[] {
  const targets = new Set(headings.map(normalizeMarkdownHeadingText));
  const lines = markdown.split(/\r?\n/);
  const items: string[] = [];
  let paragraph: string[] = [];
  let inSection = false;
  let sectionLevel = 0;

  function flushParagraph() {
    if (paragraph.length === 0) {
      return;
    }
    items.push(normalizeSummaryText(paragraph.join(" ")));
    paragraph = [];
  }

  for (const line of lines) {
    const trimmed = line.trim();
    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (heading !== null) {
      if (inSection) {
        flushParagraph();
        if (heading[1].length <= sectionLevel) {
          break;
        }
      }
      if (targets.has(normalizeMarkdownHeadingText(heading[2]))) {
        inSection = true;
        sectionLevel = heading[1].length;
      }
      continue;
    }

    if (!inSection) {
      continue;
    }

    if (trimmed.length === 0) {
      flushParagraph();
      continue;
    }

    const listItem = /^[-*]\s+(.+)$/.exec(trimmed) ?? /^\d+[.)]\s+(.+)$/.exec(trimmed);
    if (listItem !== null) {
      flushParagraph();
      items.push(normalizeSummaryText(listItem[1]));
      continue;
    }

    if (trimmed.startsWith("|")) {
      flushParagraph();
      const cells = trimmed
        .split("|")
        .map((cell) => cell.trim())
        .filter((cell) => cell.length > 0);
      if (cells.length > 0 && !cells.every((cell) => /^:?-{3,}:?$/.test(cell))) {
        items.push(normalizeSummaryText(cells.join(" / ")));
      }
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  return items.filter((item) => item.length > 0);
}

function normalizeMarkdownHeadingText(text: string): string {
  return text
    .replace(/^\d+[.)、]\s*/, "")
    .replace(/[*_`]/g, "")
    .trim()
    .toLowerCase();
}

function normalizeSummaryText(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}
