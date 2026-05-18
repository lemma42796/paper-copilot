"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

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

type RunHistoryItem = {
  id: string;
  request: string;
  route: string;
  cost: number;
  reportPath: string;
};

const DEFAULT_API_URL = "http://127.0.0.1:8765";
const DEFAULT_PROMPT = "比较 Transformer 和 ViT 的注意力机制演化，给出证据引用。";

export default function Home() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [message, setMessage] = useState(DEFAULT_PROMPT);
  const [pdfDir, setPdfDir] = useState("");
  const [maxPapers, setMaxPapers] = useState(5);
  const [budgetCny, setBudgetCny] = useState(2);
  const [maxTurns, setMaxTurns] = useState(16);
  const [health, setHealth] = useState<HealthState>("checking");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);

  const normalizedApiUrl = useMemo(() => apiUrl.replace(/\/+$/, ""), [apiUrl]);

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

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (message.trim().length === 0) {
      setError("请输入研究问题。");
      return;
    }

    setIsRunning(true);
    setError(null);
    try {
      const payload = {
        message: message.trim(),
        pdf_dir: pdfDir.trim().length > 0 ? pdfDir.trim() : null,
        max_turns: maxTurns,
        budget_cny: budgetCny,
        max_papers: maxPapers
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
      setHistory((items) => [
        {
          id: chatResult.session_path,
          request: chatResult.request,
          route: chatResult.route.kind ?? "research",
          cost: chatResult.cost_cny,
          reportPath: chatResult.report_path
        },
        ...items.filter((item) => item.id !== chatResult.session_path)
      ]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "请求失败。");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="window-controls" aria-hidden="true">
          <span className="control control-red" />
          <span className="control control-yellow" />
          <span className="control control-green" />
        </div>
        <div className="brand">
          <span className="brand-mark">PC</span>
          <div>
            <p className="brand-title">Paper Copilot</p>
            <p className="brand-subtitle">Local Research</p>
          </div>
        </div>

        <nav className="history-list" aria-label="Reports">
          <p className="nav-label">Reports</p>
          {history.length === 0 ? (
            <p className="empty-history">No local runs yet.</p>
          ) : (
            history.map((item) => (
              <button
                className="history-item"
                key={item.id}
                onClick={() => setMessage(item.request)}
                type="button"
              >
                <span>{item.request}</span>
                <small>
                  {item.route} · ¥{item.cost.toFixed(4)}
                </small>
              </button>
            ))
          )}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Research Desk</h1>
            <p>{healthLabel(health)}</p>
          </div>
          <button className="ghost-button" onClick={checkHealth} type="button">
            Check API
          </button>
        </header>

        <div className="content-grid">
          <section className="main-pane" aria-label="Chat">
            <form className="composer" onSubmit={submitRequest}>
              <label htmlFor="message">Prompt</label>
              <textarea
                id="message"
                onChange={(event) => setMessage(event.target.value)}
                rows={4}
                value={message}
              />
              <div className="composer-actions">
                <div className="field-row compact">
                  <label htmlFor="max-papers">Papers</label>
                  <input
                    id="max-papers"
                    min={1}
                    onChange={(event) => setMaxPapers(Number(event.target.value))}
                    type="number"
                    value={maxPapers}
                  />
                </div>
                <div className="field-row compact">
                  <label htmlFor="budget">Budget</label>
                  <input
                    id="budget"
                    min={0.01}
                    onChange={(event) => setBudgetCny(Number(event.target.value))}
                    step={0.01}
                    type="number"
                    value={budgetCny}
                  />
                </div>
                <div className="field-row compact">
                  <label htmlFor="turns">Turns</label>
                  <input
                    id="turns"
                    min={1}
                    onChange={(event) => setMaxTurns(Number(event.target.value))}
                    type="number"
                    value={maxTurns}
                  />
                </div>
                <button className="primary-button" disabled={isRunning} type="submit">
                  {isRunning ? "Running" : "Run"}
                </button>
              </div>
            </form>

            {error ? <p className="error-strip">{error}</p> : null}

            <article className="report-pane">
              {result ? (
                <MarkdownReport markdown={result.report_markdown} />
              ) : (
                <div className="empty-report">
                  <h2>Ready</h2>
                  <p>Start the local API, then run a research prompt.</p>
                </div>
              )}
            </article>
          </section>

          <aside className="inspector" aria-label="Run metadata">
            <section className="settings">
              <h2>Connection</h2>
              <div className="field-row">
                <label htmlFor="api-url">API</label>
                <input
                  id="api-url"
                  onChange={(event) => setApiUrl(event.target.value)}
                  value={apiUrl}
                />
              </div>
              <div className="field-row">
                <label htmlFor="pdf-dir">PDF Dir</label>
                <input
                  id="pdf-dir"
                  onChange={(event) => setPdfDir(event.target.value)}
                  placeholder="/Users/a123/Documents/papers"
                  value={pdfDir}
                />
              </div>
            </section>

            <RunMetadata result={result} />
          </aside>
        </div>
      </section>
    </main>
  );
}

function healthLabel(health: HealthState): string {
  switch (health) {
    case "online":
      return "API online";
    case "offline":
      return "API offline";
    case "checking":
      return "Checking API";
  }
}

function RunMetadata({ result }: { result: ChatResponse | null }) {
  if (result === null) {
    return (
      <section className="metadata">
        <h2>Run</h2>
        <dl>
          <div>
            <dt>Status</dt>
            <dd>Idle</dd>
          </div>
        </dl>
      </section>
    );
  }

  return (
    <section className="metadata">
      <h2>Run</h2>
      <dl>
        <MetaItem label="Route" value={result.route.kind ?? "research"} />
        <MetaItem label="Stop" value={result.termination_reason} />
        <MetaItem label="Cost" value={`¥${result.cost_cny.toFixed(4)}`} />
        <MetaItem label="Events" value={String(result.events_count)} />
        <MetaItem label="Papers" value={formatPaperBudget(result.paper_budget)} />
        <MetaItem label="Session" value={result.session_path} />
        <MetaItem label="Report" value={result.report_path} />
        <MetaItem label="Quality" value={result.quality_run_path ?? "Not recorded"} />
        <MetaItem label="Eval" value={result.eval_report_path ?? "Not updated"} />
      </dl>
    </section>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}

function formatPaperBudget(budget: Record<string, unknown>): string {
  const touched = budget.touched_count;
  const max = budget.max_papers;
  if (typeof touched === "number" && typeof max === "number") {
    return `${touched}/${max}`;
  }
  return "Unavailable";
}

function MarkdownReport({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);
  return (
    <div className="markdown-body">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading":
            return block.level === 1 ? (
              <h1 key={index}>{block.text}</h1>
            ) : block.level === 2 ? (
              <h2 key={index}>{block.text}</h2>
            ) : (
              <h3 key={index}>{block.text}</h3>
            );
          case "list":
            return (
              <ul key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{item}</li>
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
            return <p key={index}>{block.text}</p>;
        }
      })}
    </div>
  );
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
