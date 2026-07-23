import Foundation
import SwiftUI

struct MarkdownReportView: View {
    let markdown: String

    private var document: MarkdownDocument {
        MarkdownDocument(markdown: markdown)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Label("报告", systemImage: "doc.richtext")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.bottom, 14)

            Divider()

            VStack(alignment: .leading, spacing: 0) {
                ForEach(
                    Array(document.blocks.enumerated()),
                    id: \.offset
                ) { index, block in
                    MarkdownBlockView(block: block)
                        .padding(.top, block.topSpacing(at: index))
                }
            }
            .frame(maxWidth: 760, alignment: .leading)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(.separator.opacity(0.7), lineWidth: 1)
        }
        .textSelection(.enabled)
    }
}

private struct MarkdownBlockView: View {
    let block: MarkdownBlock

    @ViewBuilder
    var body: some View {
        switch block {
        case .heading(let level, let text):
            Text(inlineMarkdown(text))
                .font(headingFont(for: level))
                .foregroundStyle(.primary)
                .lineSpacing(2)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .paragraph(let text):
            Text(inlineMarkdown(text))
                .font(.system(size: 15))
                .foregroundStyle(.primary)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .list(let items):
            MarkdownListView(items: items)
        case .quote(let text):
            HStack(alignment: .top, spacing: 12) {
                RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                    .fill(Color.accentColor.opacity(0.55))
                    .frame(width: 3)
                Text(inlineMarkdown(text))
                    .font(.system(size: 14.5))
                    .foregroundStyle(.secondary)
                    .italic()
                    .lineSpacing(4)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        case .code(let language, let text):
            MarkdownCodeBlock(language: language, text: text)
        case .table(let headers, let rows):
            MarkdownTable(headers: headers, rows: rows)
        case .rule:
            Divider()
                .padding(.vertical, 4)
        }
    }

    private func headingFont(for level: Int) -> Font {
        switch level {
        case 1:
            return .system(size: 24, weight: .semibold)
        case 2:
            return .system(size: 20, weight: .semibold)
        default:
            return .system(size: 16, weight: .semibold)
        }
    }
}

private struct MarkdownListView: View {
    let items: [MarkdownListItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(item.marker)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 22, alignment: .trailing)
                    Text(inlineMarkdown(item.text))
                        .font(.system(size: 15))
                        .lineSpacing(4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.leading, CGFloat(item.depth) * 20)
            }
        }
    }
}

private struct MarkdownCodeBlock: View {
    let language: String?
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            if let language {
                Text(language.uppercased())
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.tertiary)
            }
            ScrollView(.horizontal) {
                Text(text)
                    .font(.system(size: 12.5, design: .monospaced))
                    .lineSpacing(3)
                    .fixedSize(horizontal: true, vertical: false)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct MarkdownTable: View {
    let headers: [String]
    let rows: [[String]]

    private var columnWidths: [CGFloat] {
        headers.indices.map { columnIndex in
            let values = [headers[columnIndex]] + rows.map {
                columnIndex < $0.count ? $0[columnIndex] : ""
            }
            let longestValue = values.map(\.count).max() ?? 0
            return min(max(CGFloat(longestValue) * 8, 112), 240)
        }
    }

    var body: some View {
        ScrollView(.horizontal) {
            VStack(alignment: .leading, spacing: 0) {
                tableRow(headers, isHeader: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    Divider()
                    tableRow(row, isHeader: false)
                }
            }
            .overlay {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(.separator.opacity(0.65), lineWidth: 1)
            }
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private func tableRow(_ cells: [String], isHeader: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(headers.indices, id: \.self) { columnIndex in
                Text(inlineMarkdown(
                    columnIndex < cells.count ? cells[columnIndex] : ""
                ))
                .font(.system(
                    size: 13,
                    weight: isHeader ? .semibold : .regular
                ))
                .lineSpacing(3)
                .frame(
                    width: columnWidths[columnIndex],
                    alignment: .topLeading
                )
                .padding(.horizontal, 10)
                .padding(.vertical, 9)
                .background(
                    isHeader
                        ? Color.secondary.opacity(0.08)
                        : Color.clear
                )
                .overlay(alignment: .trailing) {
                    if columnIndex < headers.count - 1 {
                        Rectangle()
                            .fill(Color.secondary.opacity(0.16))
                            .frame(width: 1)
                    }
                }
            }
        }
    }
}

private struct MarkdownDocument {
    let blocks: [MarkdownBlock]

    init(markdown: String) {
        blocks = MarkdownParser.parse(markdown)
    }
}

private enum MarkdownBlock {
    case heading(level: Int, text: String)
    case paragraph(String)
    case list([MarkdownListItem])
    case quote(String)
    case code(language: String?, text: String)
    case table(headers: [String], rows: [[String]])
    case rule

    func topSpacing(at index: Int) -> CGFloat {
        guard index > 0 else {
            return 16
        }
        switch self {
        case .heading(let level, _):
            return level <= 2 ? 30 : 22
        case .paragraph:
            return 14
        case .list, .quote, .code, .table:
            return 18
        case .rule:
            return 24
        }
    }
}

private struct MarkdownListItem {
    let marker: String
    let text: String
    let depth: Int
}

private enum MarkdownParser {
    static func parse(_ markdown: String) -> [MarkdownBlock] {
        let lines = markdown.split(
            omittingEmptySubsequences: false,
            whereSeparator: \.isNewline
        ).map(String.init)
        var blocks: [MarkdownBlock] = []
        var paragraphLines: [String] = []
        var listItems: [MarkdownListItem] = []
        var codeLines: [String]? = nil
        var codeLanguage: String? = nil
        var lineIndex = 0

        func flushParagraph() {
            guard !paragraphLines.isEmpty else {
                return
            }
            blocks.append(.paragraph(paragraphLines.joined(separator: "\n")))
            paragraphLines = []
        }

        func flushList() {
            guard !listItems.isEmpty else {
                return
            }
            blocks.append(.list(listItems))
            listItems = []
        }

        while lineIndex < lines.count {
            let line = lines[lineIndex]
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)

            if trimmed.hasPrefix("```") {
                if let currentCodeLines = codeLines {
                    blocks.append(.code(
                        language: codeLanguage,
                        text: currentCodeLines.joined(separator: "\n")
                    ))
                    codeLines = nil
                    codeLanguage = nil
                } else {
                    flushParagraph()
                    flushList()
                    let language = String(trimmed.dropFirst(3))
                        .trimmingCharacters(in: .whitespaces)
                    codeLanguage = language.isEmpty ? nil : language
                    codeLines = []
                }
                lineIndex += 1
                continue
            }

            if codeLines != nil {
                codeLines?.append(line)
                lineIndex += 1
                continue
            }

            if trimmed.isEmpty {
                flushParagraph()
                flushList()
                lineIndex += 1
                continue
            }

            if
                lineIndex + 1 < lines.count,
                isTableRow(trimmed),
                isTableSeparator(lines[lineIndex + 1])
            {
                flushParagraph()
                flushList()
                let headers = tableCells(trimmed)
                var rows: [[String]] = []
                lineIndex += 2
                while
                    lineIndex < lines.count,
                    isTableRow(lines[lineIndex])
                {
                    rows.append(tableCells(lines[lineIndex]))
                    lineIndex += 1
                }
                blocks.append(.table(headers: headers, rows: rows))
                continue
            }

            if let heading = heading(from: trimmed) {
                flushParagraph()
                flushList()
                blocks.append(.heading(level: heading.level, text: heading.text))
                lineIndex += 1
                continue
            }

            if isRule(trimmed) {
                flushParagraph()
                flushList()
                blocks.append(.rule)
                lineIndex += 1
                continue
            }

            if let item = listItem(from: line) {
                flushParagraph()
                listItems.append(item)
                lineIndex += 1
                continue
            }

            if trimmed.hasPrefix(">") {
                flushParagraph()
                flushList()
                let quote = String(trimmed.dropFirst())
                    .trimmingCharacters(in: .whitespaces)
                blocks.append(.quote(quote))
                lineIndex += 1
                continue
            }

            if !listItems.isEmpty {
                let previous = listItems.removeLast()
                listItems.append(MarkdownListItem(
                    marker: previous.marker,
                    text: previous.text + "\n" + trimmed,
                    depth: previous.depth
                ))
            } else {
                paragraphLines.append(trimmed)
            }
            lineIndex += 1
        }

        flushParagraph()
        flushList()
        if let codeLines {
            blocks.append(.code(
                language: codeLanguage,
                text: codeLines.joined(separator: "\n")
            ))
        }
        return blocks
    }

    private static func heading(from line: String) -> (
        level: Int,
        text: String
    )? {
        let level = line.prefix { $0 == "#" }.count
        guard
            (1...6).contains(level),
            line.dropFirst(level).first == " "
        else {
            return nil
        }
        return (
            level,
            String(line.dropFirst(level + 1))
                .trimmingCharacters(in: .whitespaces)
        )
    }

    private static func listItem(from line: String) -> MarkdownListItem? {
        let leadingSpaces = line.prefix { $0 == " " || $0 == "\t" }.count
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        let depth = min(leadingSpaces / 2, 4)

        for marker in ["-", "*", "+"] {
            let prefix = marker + " "
            if trimmed.hasPrefix(prefix) {
                return MarkdownListItem(
                    marker: "•",
                    text: String(trimmed.dropFirst(prefix.count)),
                    depth: depth
                )
            }
        }

        guard let dotIndex = trimmed.firstIndex(of: ".") else {
            return nil
        }
        let number = trimmed[..<dotIndex]
        let suffix = trimmed[trimmed.index(after: dotIndex)...]
        guard
            !number.isEmpty,
            number.allSatisfy(\.isNumber),
            suffix.first == " "
        else {
            return nil
        }
        return MarkdownListItem(
            marker: String(number) + ".",
            text: String(suffix.dropFirst()),
            depth: depth
        )
    }

    private static func isRule(_ line: String) -> Bool {
        let compact = line.filter { !$0.isWhitespace }
        guard compact.count >= 3, let character = compact.first else {
            return false
        }
        return ["-", "*", "_"].contains(String(character))
            && compact.allSatisfy { $0 == character }
    }

    private static func isTableRow(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        return trimmed.hasPrefix("|")
            && trimmed.hasSuffix("|")
            && tableCells(trimmed).count > 1
    }

    private static func isTableSeparator(_ line: String) -> Bool {
        let cells = tableCells(line)
        guard !cells.isEmpty else {
            return false
        }
        return cells.allSatisfy { cell in
            let compact = cell.filter { !$0.isWhitespace && $0 != ":" }
            return compact.count >= 3 && compact.allSatisfy { $0 == "-" }
        }
    }

    private static func tableCells(_ line: String) -> [String] {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        return trimmed
            .dropFirst(trimmed.hasPrefix("|") ? 1 : 0)
            .dropLast(trimmed.hasSuffix("|") ? 1 : 0)
            .split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
    }
}

private let evidenceReferenceExpression = try? NSRegularExpression(
    pattern:
        #"\[[A-Za-z0-9_-]{3,64}:(?:chunks\[\d+\]|[A-Za-z_][A-Za-z0-9_]*(?:\[\d+(?:-\d+)?\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+(?:-\d+)?\])?)*)\]"#
)

private func inlineMarkdown(_ source: String) -> AttributedString {
    let range = NSRange(source.startIndex..., in: source)
    let displaySource = evidenceReferenceExpression?.stringByReplacingMatches(
        in: source,
        range: range,
        withTemplate: "`$0`"
    ) ?? source
    let options = AttributedString.MarkdownParsingOptions(
        interpretedSyntax: .inlineOnlyPreservingWhitespace
    )
    return (try? AttributedString(markdown: displaySource, options: options))
        ?? AttributedString(source)
}
