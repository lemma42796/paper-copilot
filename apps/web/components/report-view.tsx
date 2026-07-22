"use client";

import type { ChatResponse, ChatSessionMessage } from "../lib/chat-types";
import { MarkdownReport } from "./markdown-report";
import { LoadingReport, ReportToolbar } from "./report-panels";

export function ReportView({
  copyNotice,
  isRunning,
  jobError,
  jobStatus,
  messages,
  onCopy,
  onEvidenceRefClick,
  onRefresh,
  progress,
  result
}: {
  copyNotice: string | null;
  isRunning: boolean;
  jobError: string | null;
  jobStatus: "queued" | "running" | "completed" | "interrupted" | "failed" | null;
  messages: ChatSessionMessage[];
  onCopy: (value: string, label: string) => Promise<void>;
  onEvidenceRefClick: (ref: string) => void | Promise<void>;
  onRefresh: () => Promise<void>;
  progress: string | null;
  result: ChatResponse | null;
}) {
  const lastAssistantIndex = messages.findLastIndex(
    (message) => message.role === "assistant"
  );
  return (
    <article className="report-pane">
      {copyNotice ? <p className="copy-toast">{copyNotice}</p> : null}
      {messages.length > 0 ? (
        <div className="conversation">
          {messages.map((message, index) =>
            message.role === "user" ? (
              <UserMessage key={message.id} text={message.content} />
            ) : (
              <div className="assistant-message" key={message.id}>
                <span className="assistant-avatar" aria-hidden="true">P</span>
                <div className="assistant-content">
                  <MarkdownReport
                    markdown={message.content}
                    onEvidenceRefClick={onEvidenceRefClick}
                  />
                  {result !== null && index === lastAssistantIndex ? (
                    <ReportToolbar onCopy={onCopy} onRefresh={onRefresh} result={result} />
                  ) : null}
                </div>
              </div>
            )
          )}
          {isRunning ? (
            <div className="assistant-message">
              <span className="assistant-avatar" aria-hidden="true">P</span>
              <LoadingReport message={progress} />
            </div>
          ) : jobStatus === "interrupted" || jobStatus === "failed" ? (
            <div className="assistant-message">
              <span className="assistant-avatar" aria-hidden="true">P</span>
              <div className="job-interrupted-message">
                <h2>{jobStatus === "interrupted" ? "任务已中断" : "任务执行失败"}</h2>
                <p>{jobError ?? "上一次执行没有完成。"}</p>
                <p>在输入框中输入“继续刚才中断的任务”即可恢复。</p>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty-report">
          <span className="empty-report-mark" aria-hidden="true">P</span>
          <h2>今天想研究什么？</h2>
          <p>询问论文、比较方法，或基于本地资料库设计新的研究方案。</p>
        </div>
      )}
    </article>
  );
}

function UserMessage({ text }: { text: string }) {
  if (text.trim().length === 0) {
    return null;
  }
  return (
    <div className="user-message">
      <p>{text}</p>
    </div>
  );
}
