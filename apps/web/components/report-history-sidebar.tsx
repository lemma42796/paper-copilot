"use client";

import type { ChatSession } from "../lib/chat-types";
import { formatCost, formatHistoryTime } from "../lib/report-adapter";

export function ReportHistorySidebar({
  canCreate,
  isCollapsed,
  onCreate,
  onSelect,
  sessions,
  selectedReportId
}: {
  canCreate: boolean;
  isCollapsed: boolean;
  onCreate: () => void;
  onSelect: (session: ChatSession) => void;
  sessions: ChatSession[];
  selectedReportId: string | null;
}) {
  return (
    <aside className="sidebar" aria-label="会话侧边栏">
      <div className="sidebar-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          {!isCollapsed ? (
            <div>
              <p className="brand-title">Paper Copilot</p>
              <p className="brand-subtitle">Research workspace</p>
            </div>
          ) : null}
        </div>
      </div>

      <button
        aria-label="新建会话"
        className="new-session-button"
        disabled={!canCreate}
        onClick={onCreate}
        title="新建会话"
        type="button"
      >
        <span aria-hidden="true">＋</span>
        {!isCollapsed ? <strong>新建会话</strong> : null}
      </button>

      {!isCollapsed ? (
        <nav className="history-list" aria-label="会话列表">
          <p className="nav-label">最近</p>
          {sessions.length === 0 ? (
            <p className="empty-history">暂无历史会话。</p>
          ) : (
            sessions.map((session) => (
              <button
                className={`history-item${session.id === selectedReportId ? " selected" : ""}`}
                key={session.id}
                onClick={() => onSelect(session)}
                type="button"
              >
                <span>{session.title}</span>
                <small>
                  {sessionStatusLabel(session)} · {formatHistoryTime(session.updatedAt)}
                </small>
              </button>
            ))
          )}
        </nav>
      ) : null}
    </aside>
  );
}

function sessionStatusLabel(session: ChatSession): string {
  switch (session.status) {
    case "draft":
      return "草稿";
    case "queued":
      return "等待执行";
    case "running":
      return "正在运行";
    case "interrupted":
      return "已中断";
    case "failed":
      return "执行失败";
    case "completed":
      return formatCost(session.costCny);
  }
}
