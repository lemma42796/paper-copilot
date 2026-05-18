"use client";

import { FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";

type HealthState = "checking" | "online" | "offline";

type ChatRoute = {
  kind?: string;
  output_profile?: string;
  reason?: string;
};

type ChatResponse = {
  request: string;
  route: ChatRoute;
  report_markdown: string;
  session_path: string;
  report_path: string;
  quality_run_path: string | null;
  eval_report_path: string | null;
  termination_reason: string;
  cost_cny: number;
  events_count: number;
  paper_budget: Record<string, unknown>;
};

type ReportHistoryResponse = {
  reports: ReportHistoryEntry[];
};

type DirectorySelectionResponse = {
  path: string | null;
};

type ReportHistoryEntry = {
  id: string;
  request: string;
  route: ChatRoute;
  report_markdown: string;
  session_path: string;
  report_path: string;
  updated_at: string;
  termination_reason: string;
  cost_cny: number | null;
  events_count: number | null;
  paper_budget: Record<string, unknown>;
};

type RunHistoryItem = {
  id: string;
  request: string;
  route: string;
  cost: number | null;
  reportPath: string;
  sessionPath: string;
  reportMarkdown: string;
  updatedAt: string;
  terminationReason: string;
  eventsCount: number | null;
  paperBudget: Record<string, unknown>;
};

type UsageTip = {
  title: string;
  description: string;
  examples: string[];
};

const DEFAULT_API_URL = "http://127.0.0.1:8765";
const DEFAULT_PROMPT =
  "基于医学图像分割，先找一个可复现 baseline，再找 2-3 个可接入模块，给出实验方案和证据引用。";
const LIBRARY_DIR_STORAGE_KEY = "paper-copilot.libraryDir";
const USAGE_TIPS: UsageTip[] = [
  {
    title: "知识库问答",
    description: "解释单篇论文、对比多篇论文，或围绕本地论文库追问研究问题。",
    examples: [
      "解释 ViT 论文的核心方法、实验设置和主要局限，并给出证据引用。",
      "对比 Transformer 和 ViT 的注意力机制演化，列出关键差异和证据引用。",
      "围绕行人重识别的训练技巧，总结常见方法、适用场景和局限。"
    ]
  },
  {
    title: "新论文模型框架",
    description: "根据研究方向先找 baseline，再找可接入模块，组合成可验证方案。",
    examples: [
      "基于医学图像分割，先找一个可复现 baseline，再找 2-3 个可接入模块，给出新模型框架、消融实验和证据引用。",
      "针对行人重识别，先选一个 strong baseline，再从近年论文找可插拔模块，组合成可验证改进方案。",
      "基于 diffusion model 和医学图像分割，找 baseline、模块、兼容性风险和实验计划。"
    ]
  }
];

export default function Home() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [message, setMessage] = useState(DEFAULT_PROMPT);
  const [pdfDir, setPdfDir] = useState("");
  const [health, setHealth] = useState<HealthState>("checking");
  const [isRunning, setIsRunning] = useState(false);
  const [isSelectingLibraryDir, setIsSelectingLibraryDir] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isInspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  const normalizedApiUrl = useMemo(() => apiUrl.replace(/\/+$/, ""), [apiUrl]);
  const canSubmit = health === "online" && !isRunning;

  async function checkHealth() {
    setHealth("checking");
    try {
      const response = await fetch(`${normalizedApiUrl}/health`, { method: "GET" });
      setHealth(response.ok ? "online" : "offline");
    } catch {
      setHealth("offline");
    }
  }

  useEffect(() => {
    void checkHealth();
  }, [normalizedApiUrl]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(LIBRARY_DIR_STORAGE_KEY);
      if (saved !== null) {
        setPdfDir(saved);
      }
    } catch {
      return;
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [normalizedApiUrl]);

  async function loadReports(): Promise<boolean> {
    try {
      const response = await fetch(`${normalizedApiUrl}/reports`, { method: "GET" });
      if (!response.ok) {
        return false;
      }
      const payload = (await response.json()) as ReportHistoryResponse;
      setHistory(payload.reports.map(historyItemFromReport));
      return true;
    } catch {
      return false;
    }
  }

  async function refreshReports() {
    const ok = await loadReports();
    showNotice(ok ? "历史已刷新" : "刷新失败");
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (message.trim().length === 0) {
      setError("请输入研究问题。");
      return;
    }
    if (health !== "online") {
      setError("本地 API 未连接，请先启动 paper-copilot serve。");
      return;
    }

    setIsRunning(true);
    setError(null);
    try {
      const payload = {
        message: message.trim(),
        pdf_dir: pdfDir.trim().length > 0 ? pdfDir.trim() : null
      };
      let response: Response;
      try {
        response = await fetch(`${normalizedApiUrl}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
      } catch {
        setHealth("offline");
        throw new Error("无法连接本地 API。");
      }

      const raw = (await response.json()) as ChatResponse | { error?: { message?: string } };
      setHealth("online");
      if (!response.ok) {
        const messageText =
          "error" in raw && raw.error?.message ? raw.error.message : "请求失败。";
        throw new Error(messageText);
      }

      const chatResult = raw as ChatResponse;
      setResult(chatResult);
      setSelectedReportId(chatResult.session_path);
      setHistory((items) => [
        historyItemFromChatResult(chatResult),
        ...items.filter((item) => item.id !== chatResult.session_path)
      ]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "请求失败。");
    } finally {
      setIsRunning(false);
    }
  }

  function selectHistoryItem(item: RunHistoryItem) {
    setError(null);
    setMessage(item.request);
    setSelectedReportId(item.id);
    setResult(chatResponseFromHistoryItem(item));
  }

  function updateLibraryDir(value: string) {
    setPdfDir(value);
    try {
      const trimmed = value.trim();
      if (trimmed.length > 0) {
        window.localStorage.setItem(LIBRARY_DIR_STORAGE_KEY, value);
      } else {
        window.localStorage.removeItem(LIBRARY_DIR_STORAGE_KEY);
      }
    } catch {
      return;
    }
  }

  async function selectLibraryDir() {
    setIsSelectingLibraryDir(true);
    setError(null);
    try {
      let response: Response;
      try {
        response = await fetch(`${normalizedApiUrl}/library/select-directory`, {
          method: "POST"
        });
      } catch {
        setHealth("offline");
        throw new Error("无法连接本地 API，不能打开目录选择器。");
      }

      const raw = (await response.json()) as
        | DirectorySelectionResponse
        | { error?: { message?: string } };
      setHealth("online");
      if (!response.ok) {
        const messageText =
          "error" in raw && raw.error?.message ? raw.error.message : "目录选择失败。";
        throw new Error(messageText);
      }

      const selectedPath = (raw as DirectorySelectionResponse).path;
      if (selectedPath === null) {
        showNotice("未选择目录");
        return;
      }
      updateLibraryDir(selectedPath);
      showNotice("资料库已选择");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "目录选择失败。");
    } finally {
      setIsSelectingLibraryDir(false);
    }
  }

  async function copyWithNotice(value: string, label: string) {
    const ok = await copyText(value);
    showNotice(ok ? `${label}已复制` : "复制失败");
  }

  function showNotice(text: string) {
    setCopyNotice(text);
    window.setTimeout(() => setCopyNotice(null), 1600);
  }

  return (
    <main className={`app-shell${isSidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar" aria-label="报告侧边栏">
        <div className="sidebar-header">
          <div className="brand">
            <span className="brand-mark">PC</span>
            {!isSidebarCollapsed ? (
              <div>
                <p className="brand-title">Paper Copilot</p>
                <p className="brand-subtitle">本地研究助手</p>
              </div>
            ) : null}
          </div>
          <button
            aria-label={isSidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
            title={isSidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
            type="button"
          >
            <span aria-hidden="true">{isSidebarCollapsed ? "›" : "‹"}</span>
          </button>
        </div>

        {!isSidebarCollapsed ? (
          <nav className="history-list" aria-label="报告列表">
            <p className="nav-label">报告</p>
            {history.length === 0 ? (
              <p className="empty-history">暂无历史报告。</p>
            ) : (
              history.map((item) => (
                <button
                  className={`history-item${item.id === selectedReportId ? " selected" : ""}`}
                  key={item.id}
                  onClick={() => selectHistoryItem(item)}
                  type="button"
                >
                  <span>{item.request}</span>
                  <small>
                    {formatRoute(item.route)} · {formatCost(item.cost)} ·{" "}
                    {formatHistoryTime(item.updatedAt)}
                  </small>
                </button>
              ))
            )}
          </nav>
        ) : null}
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>研究工作台</h1>
            <p>{healthLabel(health)}</p>
          </div>
          <button className="ghost-button" onClick={checkHealth} type="button">
            检查 API
          </button>
        </header>

        <div className={`content-grid${isInspectorCollapsed ? " inspector-collapsed" : ""}`}>
          <section className="main-pane" aria-label="研究输入">
            <form className="composer" onSubmit={submitRequest}>
              <section className="usage-guide" aria-label="使用提示">
                <div className="usage-guide-heading">
                  <h2>可以这样用</h2>
                  <p>基于右侧资料库目录，输入自然语言研究任务。</p>
                </div>
                <div className="usage-groups">
                  {USAGE_TIPS.map((tip) => (
                    <section className="usage-group" key={tip.title}>
                      <h3>{tip.title}</h3>
                      <p>{tip.description}</p>
                      <div className="prompt-examples">
                        {tip.examples.map((example) => (
                          <button
                            className="prompt-example"
                            key={example}
                            onClick={() => setMessage(example)}
                            type="button"
                          >
                            {example}
                          </button>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              </section>
              <label htmlFor="message">研究方向或任务</label>
              <textarea
                id="message"
                onChange={(event) => setMessage(event.target.value)}
                placeholder="例如：先找一个 baseline，再找可接入模块，组合成可验证的改进方案。"
                rows={4}
                value={message}
              />
              <div className="composer-actions">
                <button className="primary-button" disabled={!canSubmit} type="submit">
                  {isRunning ? "运行中" : "开始"}
                </button>
              </div>
              {health === "offline" ? (
                <p className="inline-hint">本地 API 未连接，请先启动 paper-copilot serve。</p>
              ) : null}
            </form>

            {error ? <p className="error-strip">{error}</p> : null}

            <article className="report-pane">
              {copyNotice ? <p className="copy-toast">{copyNotice}</p> : null}
              {isRunning ? (
                <LoadingReport />
              ) : result ? (
                <>
                  <ReportToolbar
                    onCopy={copyWithNotice}
                    onRefresh={refreshReports}
                    result={result}
                  />
                  <MarkdownReport markdown={result.report_markdown} />
                </>
              ) : (
                <div className="empty-report">
                  <h2>准备就绪</h2>
                  <p>从左侧选择历史报告，或输入新任务。</p>
                  <button
                    className="secondary-button"
                    onClick={() => void refreshReports()}
                    type="button"
                  >
                    刷新历史
                  </button>
                </div>
              )}
            </article>
          </section>

          <aside
            className={`inspector${isInspectorCollapsed ? " collapsed" : ""}`}
            aria-label="运行信息"
          >
            <div className="inspector-header">
              {!isInspectorCollapsed ? <h2>运行信息</h2> : null}
              <button
                aria-label={isInspectorCollapsed ? "展开运行信息" : "折叠运行信息"}
                className="inspector-toggle"
                onClick={() => setInspectorCollapsed((collapsed) => !collapsed)}
                title={isInspectorCollapsed ? "展开运行信息" : "折叠运行信息"}
                type="button"
              >
                <span aria-hidden="true">{isInspectorCollapsed ? "‹" : "›"}</span>
              </button>
            </div>

            {!isInspectorCollapsed ? (
              <>
                <section className="settings">
                  <h2>资料库</h2>
                  <p className="settings-note">
                    指定本地论文文件夹。之后每次任务都会自动带上这个目录。
                  </p>
                  <div className="field-row">
                    <label htmlFor="pdf-dir">本地论文文件夹</label>
                    <div className="library-dir-control">
                      <input
                        id="pdf-dir"
                        onChange={(event) => updateLibraryDir(event.target.value)}
                        placeholder="/Users/a123/Documents/papers"
                        value={pdfDir}
                      />
                      <button
                        className="secondary-button"
                        disabled={isSelectingLibraryDir}
                        onClick={() => void selectLibraryDir()}
                        type="button"
                      >
                        {isSelectingLibraryDir ? "选择中" : "选择目录"}
                      </button>
                    </div>
                  </div>
                </section>

                <section className="settings">
                  <h2>本地服务</h2>
                  <div className="field-row">
                    <label htmlFor="api-url">API</label>
                    <input
                      id="api-url"
                      onChange={(event) => setApiUrl(event.target.value)}
                      value={apiUrl}
                    />
                  </div>
                </section>

                <RunMetadata onCopy={copyWithNotice} result={result} />
              </>
            ) : null}
          </aside>
        </div>
      </section>
    </main>
  );
}

function LoadingReport() {
  return (
    <div className="loading-report">
      <div className="loading-spinner" aria-hidden="true" />
      <h2>正在生成报告</h2>
      <p>请稍等，本地后端正在处理这次研究任务。</p>
    </div>
  );
}

function healthLabel(health: HealthState): string {
  switch (health) {
    case "online":
      return "API 已连接";
    case "offline":
      return "API 离线";
    case "checking":
      return "正在检查 API";
  }
}

function historyItemFromChatResult(result: ChatResponse): RunHistoryItem {
  return {
    id: result.session_path,
    request: result.request,
    route: result.route.kind ?? "research",
    cost: result.cost_cny,
    reportPath: result.report_path,
    sessionPath: result.session_path,
    reportMarkdown: result.report_markdown,
    updatedAt: new Date().toISOString(),
    terminationReason: result.termination_reason,
    eventsCount: result.events_count,
    paperBudget: result.paper_budget
  };
}

function historyItemFromReport(entry: ReportHistoryEntry): RunHistoryItem {
  return {
    id: entry.session_path,
    request: entry.request,
    route: entry.route.kind ?? "research",
    cost: entry.cost_cny,
    reportPath: entry.report_path,
    sessionPath: entry.session_path,
    reportMarkdown: entry.report_markdown,
    updatedAt: entry.updated_at,
    terminationReason: entry.termination_reason,
    eventsCount: entry.events_count,
    paperBudget: entry.paper_budget
  };
}

function chatResponseFromHistoryItem(item: RunHistoryItem): ChatResponse {
  return {
    request: item.request,
    route: { kind: item.route },
    report_markdown: item.reportMarkdown,
    session_path: item.sessionPath,
    report_path: item.reportPath,
    quality_run_path: null,
    eval_report_path: null,
    termination_reason: item.terminationReason,
    cost_cny: item.cost ?? 0,
    events_count: item.eventsCount ?? 0,
    paper_budget: item.paperBudget
  };
}

function ReportToolbar({
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
        <p className="report-title" title={result.request}>
          {result.request}
        </p>
        <p className="report-subtitle">
          {formatRoute(result.route.kind ?? "research")} · {formatCost(result.cost_cny)}
        </p>
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

function RunMetadata({
  onCopy,
  result
}: {
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
            <dd>空闲</dd>
          </div>
        </dl>
      </section>
    );
  }

  return (
    <section className="metadata">
      <h2>运行</h2>
      <dl>
        <MetaItem label="路由" value={formatRoute(result.route.kind ?? "research")} />
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

function formatCost(cost: number | null): string {
  return cost === null ? "费用未知" : `¥${cost.toFixed(4)}`;
}

function formatHistoryTime(value: string): string {
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

function formatRoute(route: string): string {
  switch (route) {
    case "idea_composer":
      return "创新方案";
    case "research":
      return "研究";
    default:
      return route;
  }
}

function formatTermination(reason: string): string {
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

function MarkdownReport({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);
  return (
    <div className="markdown-body">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading":
            return block.level === 1 ? (
              <h1 key={index}>{renderInlineText(block.text)}</h1>
            ) : block.level === 2 ? (
              <h2 key={index}>{renderInlineText(block.text)}</h2>
            ) : (
              <h3 key={index}>{renderInlineText(block.text)}</h3>
            );
          case "list":
            return (
              <ul key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{renderInlineText(item)}</li>
                ))}
              </ul>
            );
          case "code":
            return (
              <pre key={index}>
                <code>{block.text}</code>
              </pre>
            );
          case "rule":
            return <hr key={index} />;
          case "paragraph":
            return <p key={index}>{renderInlineText(block.text)}</p>;
        }
      })}
    </div>
  );
}

function renderInlineText(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const refPattern = /(\[[A-Za-z0-9_-]+:[^\]\s][^\]]*\])/g;
  let lastIndex = 0;
  for (const match of text.matchAll(refPattern)) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const ref = match[0];
    parts.push(
      <button
        className="evidence-ref"
        key={`${ref}-${match.index}`}
        onClick={() => void copyText(ref)}
        title="复制证据引用"
        type="button"
      >
        {ref}
      </button>
    );
    lastIndex = match.index + ref.length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}

async function copyText(value: string): Promise<boolean> {
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

type MarkdownBlock =
  | { kind: "heading"; level: 1 | 2 | 3; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "rule" };

function parseMarkdown(markdown: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = markdown.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] | null = null;

  function flushParagraph() {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  }

  function flushList() {
    if (list.length > 0) {
      blocks.push({ kind: "list", items: list });
      list = [];
    }
  }

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (code === null) {
        flushParagraph();
        flushList();
        code = [];
      } else {
        blocks.push({ kind: "code", text: code.join("\n") });
        code = null;
      }
      continue;
    }

    if (code !== null) {
      code.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (trimmed.length === 0) {
      flushParagraph();
      flushList();
      continue;
    }

    if (trimmed === "---") {
      flushParagraph();
      flushList();
      blocks.push({ kind: "rule" });
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading !== null) {
      flushParagraph();
      flushList();
      blocks.push({
        kind: "heading",
        level: Math.min(heading[1].length, 3) as 1 | 2 | 3,
        text: heading[2]
      });
      continue;
    }

    const listItem = /^[-*]\s+(.+)$/.exec(trimmed);
    if (listItem !== null) {
      flushParagraph();
      list.push(listItem[1]);
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  if (code !== null) {
    blocks.push({ kind: "code", text: code.join("\n") });
  }
  return blocks;
}
