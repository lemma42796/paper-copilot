"use client";

import { type ReactNode, useMemo } from "react";

import { copyText, isChunkEvidenceRef } from "../lib/report-adapter";

type MarkdownBlock =
  | { kind: "heading"; level: 1 | 2 | 3; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "table"; headers: string[]; rows: string[][] }
  | { kind: "rule" };

export function MarkdownReport({
  markdown,
  onEvidenceRefClick
}: {
  markdown: string;
  onEvidenceRefClick?: (ref: string) => void | Promise<void>;
}) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);
  return (
    <div className="markdown-body">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading":
            return block.level === 1 ? (
              <h1 key={index}>{renderInlineText(block.text, onEvidenceRefClick)}</h1>
            ) : block.level === 2 ? (
              <h2 key={index}>{renderInlineText(block.text, onEvidenceRefClick)}</h2>
            ) : (
              <h3 key={index}>{renderInlineText(block.text, onEvidenceRefClick)}</h3>
            );
          case "list":
            return (
              <ul key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{renderInlineText(item, onEvidenceRefClick)}</li>
                ))}
              </ul>
            );
          case "code":
            return (
              <pre key={index}>
                <code>{block.text}</code>
              </pre>
            );
          case "table":
            return (
              <div className="markdown-table-wrap" key={index}>
                <table>
                  <thead>
                    <tr>
                      {block.headers.map((header, headerIndex) => (
                        <th key={`${header}-${headerIndex}`}>
                          {renderInlineText(header, onEvidenceRefClick)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {block.headers.map((_header, cellIndex) => (
                          <td key={`${rowIndex}-${cellIndex}`}>
                            {renderInlineText(row[cellIndex] ?? "", onEvidenceRefClick)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "rule":
            return <hr key={index} />;
          case "paragraph":
            return <p key={index}>{renderInlineText(block.text, onEvidenceRefClick)}</p>;
        }
      })}
    </div>
  );
}

export function renderInlineText(
  text: string,
  onEvidenceRefClick?: (ref: string) => void | Promise<void>
): ReactNode[] {
  const parts: ReactNode[] = [];
  const refPattern =
    /(\[\s*[A-Za-z0-9_-]{3,64}\s*:\s*(?:chunks\[\d+\]|[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)*)\s*\])/g;
  let lastIndex = 0;
  for (const match of text.matchAll(refPattern)) {
    const matchIndex = match.index ?? 0;
    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex));
    }
    const ref = match[0];
    parts.push(
      <button
        className="evidence-ref"
        key={`${ref}-${matchIndex}`}
        onClick={() => void (onEvidenceRefClick ? onEvidenceRefClick(ref) : copyText(ref))}
        title={isChunkEvidenceRef(ref) ? "打开证据原文" : "打开字段证据"}
        type="button"
      >
        {ref}
      </button>
    );
    lastIndex = matchIndex + ref.length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}

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

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
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
    const nextTrimmed = lines[lineIndex + 1]?.trim() ?? "";
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

    if (isMarkdownTableRow(trimmed) && isMarkdownTableSeparator(nextTrimmed)) {
      flushParagraph();
      flushList();
      const headers = parseMarkdownTableCells(trimmed);
      const rows: string[][] = [];
      lineIndex += 2;
      while (lineIndex < lines.length) {
        const rowText = lines[lineIndex].trim();
        if (!isMarkdownTableRow(rowText) || isMarkdownTableSeparator(rowText)) {
          lineIndex -= 1;
          break;
        }
        rows.push(normalizeMarkdownTableRow(parseMarkdownTableCells(rowText), headers.length));
        lineIndex += 1;
      }
      blocks.push({ kind: "table", headers, rows });
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

function isMarkdownTableRow(line: string): boolean {
  return line.startsWith("|") && line.includes("|", 1);
}

function isMarkdownTableSeparator(line: string): boolean {
  if (!isMarkdownTableRow(line)) {
    return false;
  }
  const cells = parseMarkdownTableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function parseMarkdownTableCells(line: string): string[] {
  return line
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function normalizeMarkdownTableRow(cells: string[], length: number): string[] {
  if (cells.length >= length) {
    return cells.slice(0, length);
  }
  return [...cells, ...Array.from({ length: length - cells.length }, () => "")];
}
