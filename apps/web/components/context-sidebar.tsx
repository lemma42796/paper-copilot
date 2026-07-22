"use client";

import type {
  ChatResponse,
  ComposerLibraryResponse,
  EvidenceResponse,
  RolloutDiagnostics
} from "../lib/chat-types";
import {
  ComposerLibraryPanel,
  ComposerSummary,
  EvidenceInspector,
  RunMetadata,
  TraceDiagnosticsPanel
} from "./report-panels";

export function ContextSidebar({
  apiUrl,
  diagnostics,
  diagnosticsError,
  evidenceError,
  isCollapsed,
  isLoadingEvidence,
  isLoadingDiagnostics,
  isLoadingLibraryStatus,
  isSelectingLibraryDir,
  jobId,
  jobProgress,
  jobStatus,
  libraryStatus,
  libraryStatusError,
  onApiUrlChange,
  onCopy,
  onRefreshDiagnostics,
  onEvidenceRefClick,
  onLibraryDirChange,
  onRefreshLibraryStatus,
  onSelectLibraryDir,
  pdfDir,
  result,
  selectedEvidence
}: {
  apiUrl: string;
  diagnostics: RolloutDiagnostics | null;
  diagnosticsError: string | null;
  evidenceError: string | null;
  isCollapsed: boolean;
  isLoadingEvidence: boolean;
  isLoadingDiagnostics: boolean;
  isLoadingLibraryStatus: boolean;
  isSelectingLibraryDir: boolean;
  jobId: string | null;
  jobProgress: string | null;
  jobStatus: "queued" | "running" | "completed" | "interrupted" | "failed" | null;
  libraryStatus: ComposerLibraryResponse | null;
  libraryStatusError: string | null;
  onApiUrlChange: (value: string) => void;
  onCopy: (value: string, label: string) => Promise<void>;
  onRefreshDiagnostics: () => Promise<void>;
  onEvidenceRefClick: (ref: string) => void | Promise<void>;
  onLibraryDirChange: (value: string) => void;
  onRefreshLibraryStatus: () => Promise<void>;
  onSelectLibraryDir: () => Promise<void>;
  pdfDir: string;
  result: ChatResponse | null;
  selectedEvidence: EvidenceResponse | null;
}) {
  if (isCollapsed) {
    return null;
  }

  return (
    <aside className="inspector" aria-label="研究上下文">
      <div className="inspector-header">
        <div>
          <h2>研究上下文</h2>
          <p>资料库、运行和证据</p>
        </div>
      </div>

      <section className="settings">
        <h2>资料库</h2>
        <p className="settings-note">指定本地论文文件夹。之后每次任务都会自动带上这个目录。</p>
        <div className="field-row">
          <label htmlFor="pdf-dir">本地论文文件夹</label>
          <div className="library-dir-control">
            <input
              id="pdf-dir"
              onChange={(event) => onLibraryDirChange(event.target.value)}
              placeholder="/Users/a123/paper-copilot-test-pdfs"
              value={pdfDir}
            />
            <button
              className="secondary-button"
              disabled={isSelectingLibraryDir}
              onClick={() => void onSelectLibraryDir()}
              type="button"
            >
              {isSelectingLibraryDir ? "选择中" : "选择目录"}
            </button>
          </div>
        </div>
        <ComposerLibraryPanel
          error={libraryStatusError}
          isLoading={isLoadingLibraryStatus}
          onRefresh={onRefreshLibraryStatus}
          status={libraryStatus}
        />
      </section>

      <section className="settings">
        <h2>本地服务</h2>
        <div className="field-row">
          <label htmlFor="api-url">API</label>
          <input
            id="api-url"
            onChange={(event) => onApiUrlChange(event.target.value)}
            value={apiUrl}
          />
        </div>
      </section>

      <RunMetadata
        jobProgress={jobProgress}
        jobStatus={jobStatus}
        onCopy={onCopy}
        result={result}
      />
      <TraceDiagnosticsPanel
        diagnostics={diagnostics}
        error={diagnosticsError}
        isLoading={isLoadingDiagnostics}
        jobId={jobId}
        onRefresh={onRefreshDiagnostics}
      />
      <ComposerSummary
        onCopy={onCopy}
        onEvidenceRefClick={onEvidenceRefClick}
        result={result}
      />
      <EvidenceInspector
        error={evidenceError}
        evidence={selectedEvidence}
        isLoading={isLoadingEvidence}
        onCopy={onCopy}
      />
    </aside>
  );
}
