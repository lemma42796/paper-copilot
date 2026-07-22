"use client";

import type { FormEvent } from "react";

import type { HealthState, UsageTip } from "../lib/chat-types";

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
      "基于可见光-红外行人重识别（VI-ReID），先选一个性能强但仍有改进故事的强基线，再从本地 CCF A 论文里找 3 个可兼容模块，给出中文实验方案。",
      "针对行人重识别，先选一个 strong baseline，再从近年论文找 3 个可插拔模块，组合成可验证改进方案。",
      "基于 diffusion model 的视觉任务，找强 baseline、3 个模块、兼容性风险和实验计划。"
    ]
  }
];

export function ResearchComposer({
  canStop,
  canSubmit,
  health,
  isInterrupting,
  isRunning,
  message,
  onMessageChange,
  onStop,
  onSubmit,
  showSuggestions
}: {
  canStop: boolean;
  canSubmit: boolean;
  health: HealthState;
  isInterrupting: boolean;
  isRunning: boolean;
  message: string;
  onMessageChange: (message: string) => void;
  onStop: () => void | Promise<void>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  showSuggestions: boolean;
}) {
  return (
    <form className="composer" onSubmit={onSubmit}>
      {showSuggestions ? (
        <section className="usage-guide" aria-label="使用提示">
          {USAGE_TIPS.map((tip) => (
            <section className="usage-group" key={tip.title}>
              <h3>{tip.title}</h3>
              <div className="prompt-examples">
                {tip.examples.slice(0, 2).map((example) => (
                  <button
                    className="prompt-example"
                    key={example}
                    onClick={() => onMessageChange(example)}
                    type="button"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </section>
      ) : null}
      <div className="composer-shell">
        <textarea
          aria-label="研究方向或任务"
          id="message"
          onChange={(event) => onMessageChange(event.target.value)}
          placeholder="向 Paper Copilot 提问"
          rows={2}
          value={message}
        />
        <div className="composer-actions">
          <span className="composer-context-chip">本地论文库</span>
          <button
            aria-label={isRunning ? "停止生成" : "发送"}
            className={`primary-button${isRunning ? " stop-button" : ""}`}
            disabled={isRunning ? !canStop || isInterrupting : !canSubmit}
            onClick={isRunning ? () => void onStop() : undefined}
            title={isRunning ? (isInterrupting ? "正在停止" : "停止生成") : "发送"}
            type={isRunning ? "button" : "submit"}
          >
            <span
              aria-hidden="true"
              className={isRunning ? "stop-icon" : undefined}
            >
              {isRunning ? "" : "↑"}
            </span>
          </button>
        </div>
      </div>
      {health === "offline" ? (
        <p className="inline-hint">本地 API 未连接，请先启动后端服务。</p>
      ) : (
        <p className="composer-caption">Paper Copilot 会基于本地资料生成回答，请核对重要结论。</p>
      )}
    </form>
  );
}
