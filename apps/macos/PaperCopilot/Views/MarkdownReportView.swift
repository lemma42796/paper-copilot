import AppKit
import Foundation
import PDFKit
import SwiftMath
import SwiftUI

struct MarkdownReportView: View {
    let markdown: String
    let pdfDirectory: String?
    let citationTargets: [String: String]
    let onOpenCitation: (PaperCitationDestination) -> Void
    @State private var document: MarkdownDocument

    init(
        markdown: String,
        pdfDirectory: String?,
        citationTargets: [String: String],
        onOpenCitation: @escaping (PaperCitationDestination) -> Void
    ) {
        self.markdown = markdown
        self.pdfDirectory = pdfDirectory
        self.citationTargets = citationTargets
        self.onOpenCitation = onOpenCitation
        _document = State(
            initialValue: MarkdownDocument(markdown: markdown)
        )
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
        .onChange(of: markdown) { updatedMarkdown in
            document = MarkdownDocument(markdown: updatedMarkdown)
        }
        .environment(\.openURL, OpenURLAction { url in
            openCitation(url)
        })
    }

    private func openCitation(_ url: URL) -> OpenURLAction.Result {
        guard url.scheme == "paper-copilot", url.host == "open" else {
            return .systemAction
        }
        guard
            let pdfDirectory,
            let components = URLComponents(
                url: url,
                resolvingAgainstBaseURL: false
            ),
            let citationRef = components.queryItems?.first(where: {
                $0.name == "ref"
            })?.value,
            let locator = citationTargets[citationRef],
            let pageText = components.queryItems?.first(where: {
                $0.name == "page"
            })?.value,
            let page = Int(pageText),
            page > 0
        else {
            return .discarded
        }

        let root = URL(fileURLWithPath: pdfDirectory, isDirectory: true)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        let target = root
            .appendingPathComponent(locator)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        let rootPrefix = root.path.hasSuffix("/") ? root.path : root.path + "/"
        guard
            target.path.hasPrefix(rootPrefix),
            target.pathExtension.lowercased() == "pdf",
            FileManager.default.fileExists(atPath: target.path)
        else {
            return .discarded
        }

        onOpenCitation(PaperCitationDestination(url: target, page: page))
        return .handled
    }
}

struct PaperCitationDestination: Identifiable {
    let url: URL
    let page: Int

    var id: String {
        "\(url.path)#page=\(page)"
    }
}

struct PaperCitationPanel: View {
    let destination: PaperCitationDestination
    let onClose: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(
                    destination.url.deletingPathExtension().lastPathComponent
                        + (AppLanguage.current == .english
                            ? " · Page \(destination.page)"
                            : " · 第 \(destination.page) 页")
                )
                    .font(.headline)
                    .lineLimit(1)
                    .id(destination.id)
                    .transition(.opacity)
                Spacer()
                Button {
                    onClose()
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
                .help("关闭论文预览")
            }
            .padding()

            Divider()

            ZStack {
                PaperPDFView(url: destination.url, page: destination.page)
                    .id(destination.id)
                    .transition(.opacity)
            }
        }
        .frame(minWidth: 300, idealWidth: 460)
        .background(.background)
        .animation(citationChangeAnimation, value: destination.id)
    }

    private var citationChangeAnimation: Animation? {
        reduceMotion ? nil : .easeInOut(duration: 0.16)
    }
}

private struct PaperPDFView: NSViewRepresentable {
    let url: URL
    let page: Int

    func makeNSView(context: Context) -> PDFView {
        let pdfView = PDFView()
        pdfView.autoScales = true
        pdfView.displayMode = .singlePageContinuous
        pdfView.displayDirection = .vertical
        showPage(in: pdfView)
        return pdfView
    }

    func updateNSView(_ pdfView: PDFView, context: Context) {
        showPage(in: pdfView)
    }

    private func showPage(in pdfView: PDFView) {
        if pdfView.document?.documentURL != url {
            pdfView.document = PDFDocument(url: url)
        }
        guard
            let document = pdfView.document,
            document.pageCount > 0,
            let targetPage = document.page(
                at: min(page - 1, document.pageCount - 1)
            )
        else {
            return
        }
        pdfView.go(to: targetPage)
    }
}

private struct MarkdownBlockView: View {
    let block: MarkdownBlock

    @ViewBuilder
    var body: some View {
        switch block {
        case .heading(let level, let text):
            MarkdownInlineView(
                source: text,
                fontSize: headingFontSize(for: level),
                fontWeight: .semibold,
                foregroundColor: .labelColor,
                lineSpacing: 2
            )
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .paragraph(let text):
            MarkdownInlineView(
                source: text,
                fontSize: 15,
                foregroundColor: .labelColor,
                lineSpacing: 5
            )
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .list(let items):
            MarkdownListView(items: items)
        case .quote(let text):
            HStack(alignment: .top, spacing: 12) {
                RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                    .fill(Color.accentColor.opacity(0.55))
                    .frame(width: 3)
                MarkdownInlineView(
                    source: text,
                    fontSize: 14.5,
                    foregroundColor: .secondaryLabelColor,
                    lineSpacing: 4,
                    italic: true
                )
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 4)
        case .code(let language, let text):
            MarkdownCodeBlock(language: language, text: text)
        case .math(let latex):
            MarkdownMathBlock(latex: latex)
        case .table(let headers, let rows):
            MarkdownTable(headers: headers, rows: rows)
        case .rule:
            Divider()
                .padding(.vertical, 4)
        }
    }

    private func headingFontSize(for level: Int) -> CGFloat {
        switch level {
        case 1:
            return 24
        case 2:
            return 20
        default:
            return 16
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
                    MarkdownInlineView(
                        source: item.text,
                        fontSize: 15,
                        foregroundColor: .labelColor,
                        lineSpacing: 4
                    )
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
                MarkdownInlineView(
                    source: columnIndex < cells.count
                        ? cells[columnIndex]
                        : "",
                    fontSize: 13,
                    fontWeight: isHeader ? .semibold : .regular,
                    foregroundColor: .labelColor,
                    lineSpacing: 3
                )
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
    case math(String)
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
        case .list, .quote, .code, .math, .table:
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
                    let text = currentCodeLines.joined(separator: "\n")
                    if isMathLanguage(codeLanguage) {
                        blocks.append(.math(text))
                    } else {
                        blocks.append(.code(
                            language: codeLanguage,
                            text: text
                        ))
                    }
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

            if let displayMath = displayMathBlock(
                in: lines,
                startingAt: lineIndex
            ) {
                flushParagraph()
                flushList()
                blocks.append(.math(displayMath.latex))
                lineIndex = displayMath.nextIndex
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
            let text = codeLines.joined(separator: "\n")
            if isMathLanguage(codeLanguage) {
                blocks.append(.math(text))
            } else {
                blocks.append(.code(
                    language: codeLanguage,
                    text: text
                ))
            }
        }
        return blocks
    }

    private static func isMathLanguage(_ language: String?) -> Bool {
        guard let language else {
            return false
        }
        return ["latex", "tex", "math"].contains(language.lowercased())
    }

    private static func displayMathBlock(
        in lines: [String],
        startingAt index: Int
    ) -> (latex: String, nextIndex: Int)? {
        let trimmed = lines[index]
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if
            trimmed.hasPrefix("$$"),
            trimmed.hasSuffix("$$"),
            trimmed.count > 4
        {
            return (
                String(trimmed.dropFirst(2).dropLast(2)),
                index + 1
            )
        }
        if
            trimmed.hasPrefix("\\["),
            trimmed.hasSuffix("\\]"),
            trimmed.count > 4
        {
            return (
                String(trimmed.dropFirst(2).dropLast(2)),
                index + 1
            )
        }
        if trimmed == "$$" || trimmed == "\\[" {
            let closing = trimmed == "$$" ? "$$" : "\\]"
            var mathLines: [String] = []
            var currentIndex = index + 1
            while currentIndex < lines.count {
                let candidate = lines[currentIndex]
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if candidate == closing {
                    return (
                        mathLines.joined(separator: "\n"),
                        currentIndex + 1
                    )
                }
                mathLines.append(lines[currentIndex])
                currentIndex += 1
            }
            return nil
        }

        guard let environment = latexEnvironmentName(in: trimmed) else {
            return nil
        }
        let closing = "\\end{\(environment)}"
        var mathLines: [String] = []
        var currentIndex = index
        while currentIndex < lines.count {
            mathLines.append(lines[currentIndex])
            if lines[currentIndex].contains(closing) {
                return (
                    mathLines.joined(separator: "\n"),
                    currentIndex + 1
                )
            }
            currentIndex += 1
        }
        return nil
    }

    private static func latexEnvironmentName(in line: String) -> String? {
        guard line.hasPrefix("\\begin{") else {
            return nil
        }
        let nameStart = line.index(line.startIndex, offsetBy: 7)
        guard let nameEnd = line[nameStart...].firstIndex(of: "}") else {
            return nil
        }
        let name = String(line[nameStart..<nameEnd])
        return name.isEmpty ? nil : name
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

private struct MarkdownMathBlock: View {
    let latex: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                if let image = MathImageRenderer.image(
                    latex: row,
                    fontSize: 18,
                    mode: .display
                ) {
                    ScrollView(.horizontal) {
                        Image(nsImage: image)
                            .fixedSize()
                            .accessibilityLabel(row)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    MarkdownCodeBlock(language: "latex", text: row)
                }
            }
        }
    }

    private var rows: [String] {
        let trimmed = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return [latex]
        }
        if trimmed.contains("\\begin{") {
            return [trimmed]
        }
        let lines = trimmed
            .split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter {
                !$0.isEmpty && $0 != "\\quad" && $0 != "\\qquad"
            }
        return lines.isEmpty ? [trimmed] : lines
    }
}

private struct MarkdownInlineView: View {
    let source: String
    let fontSize: CGFloat
    let fontWeight: NSFont.Weight
    let foregroundColor: NSColor
    let lineSpacing: CGFloat
    let italic: Bool

    init(
        source: String,
        fontSize: CGFloat,
        fontWeight: NSFont.Weight = .regular,
        foregroundColor: NSColor,
        lineSpacing: CGFloat,
        italic: Bool = false
    ) {
        self.source = source
        self.fontSize = fontSize
        self.fontWeight = fontWeight
        self.foregroundColor = foregroundColor
        self.lineSpacing = lineSpacing
        self.italic = italic
    }

    @ViewBuilder
    var body: some View {
        if InlineMathParser.containsMath(in: source) {
            MarkdownInlineMathText(
                source: source,
                fontSize: fontSize,
                fontWeight: fontWeight,
                foregroundColor: foregroundColor,
                lineSpacing: lineSpacing,
                italic: italic
            )
        } else {
            if italic {
                plainMarkdownText.italic()
            } else {
                plainMarkdownText
            }
        }
    }

    private var plainMarkdownText: some View {
        Text(inlineMarkdown(source))
            .font(.system(
                size: fontSize,
                weight: swiftUIFontWeight
            ))
            .lineSpacing(lineSpacing)
    }

    private var swiftUIFontWeight: Font.Weight {
        fontWeight == .semibold ? .semibold : .regular
    }
}

private struct MarkdownInlineMathText: NSViewRepresentable {
    let source: String
    let fontSize: CGFloat
    let fontWeight: NSFont.Weight
    let foregroundColor: NSColor
    let lineSpacing: CGFloat
    let italic: Bool
    @Environment(\.openURL) private var openURL

    func makeCoordinator() -> Coordinator {
        Coordinator(openURL: openURL)
    }

    func makeNSView(context: Context) -> NSTextView {
        let textView = NSTextView()
        textView.delegate = context.coordinator
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = false
        textView.textContainerInset = .zero
        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true
        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true
        textView.maxSize = CGSize(
            width: CGFloat.greatestFiniteMagnitude,
            height: CGFloat.greatestFiniteMagnitude
        )
        textView.linkTextAttributes = [
            .foregroundColor: NSColor.linkColor,
            .underlineStyle: NSUnderlineStyle.single.rawValue,
        ]
        update(textView, coordinator: context.coordinator)
        return textView
    }

    func updateNSView(_ textView: NSTextView, context: Context) {
        context.coordinator.openURL = openURL
        update(textView, coordinator: context.coordinator)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        nsView textView: NSTextView,
        context: Context
    ) -> CGSize? {
        let width = proposal.width ?? 760
        guard width.isFinite, width > 0 else {
            return nil
        }
        textView.frame.size.width = width
        textView.textContainer?.containerSize = CGSize(
            width: width,
            height: CGFloat.greatestFiniteMagnitude
        )
        guard
            let layoutManager = textView.layoutManager,
            let textContainer = textView.textContainer
        else {
            return CGSize(width: width, height: fontSize + lineSpacing)
        }
        layoutManager.ensureLayout(for: textContainer)
        let usedRect = layoutManager.usedRect(for: textContainer)
        return CGSize(
            width: width,
            height: max(ceil(usedRect.height), fontSize + lineSpacing)
        )
    }

    private func update(
        _ textView: NSTextView,
        coordinator: Coordinator
    ) {
        let styleKey = [
            String(describing: fontSize),
            String(describing: fontWeight.rawValue),
            foregroundColor.description,
            String(describing: lineSpacing),
            String(describing: italic),
        ].joined(separator: "|")
        guard
            coordinator.source != source
                || coordinator.styleKey != styleKey
        else {
            return
        }
        coordinator.source = source
        coordinator.styleKey = styleKey
        textView.textStorage?.setAttributedString(
            InlineMathAttributedStringBuilder.build(
                source: source,
                fontSize: fontSize,
                fontWeight: fontWeight,
                foregroundColor: foregroundColor,
                lineSpacing: lineSpacing,
                italic: italic
            )
        )
        textView.invalidateIntrinsicContentSize()
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var openURL: OpenURLAction
        var source: String?
        var styleKey: String?

        init(openURL: OpenURLAction) {
            self.openURL = openURL
        }

        func textView(
            _ textView: NSTextView,
            clickedOnLink link: Any,
            at charIndex: Int
        ) -> Bool {
            let url: URL?
            if let link = link as? URL {
                url = link
            } else if let link = link as? String {
                url = URL(string: link)
            } else {
                url = nil
            }
            guard let url else {
                return false
            }
            openURL(url)
            return true
        }
    }
}

private enum InlineMathAttributedStringBuilder {
    private enum PresentationMask {
        static let emphasized: UInt = 1 << 0
        static let stronglyEmphasized: UInt = 1 << 1
        static let code: UInt = 1 << 2
        static let strikethrough: UInt = 1 << 5
    }

    static func build(
        source: String,
        fontSize: CGFloat,
        fontWeight: NSFont.Weight,
        foregroundColor: NSColor,
        lineSpacing: CGFloat,
        italic: Bool
    ) -> NSAttributedString {
        let output = NSMutableAttributedString(string: "")
        let font = resolvedFont(
            size: fontSize,
            weight: fontWeight,
            italic: italic
        )
        for segment in InlineMathParser.parse(source) {
            switch segment {
            case .text(let text):
                output.append(styledMarkdown(
                    text,
                    font: font,
                    foregroundColor: foregroundColor,
                    lineSpacing: lineSpacing,
                    italic: italic
                ))
            case .math(let latex, let raw):
                guard let image = MathImageRenderer.image(
                    latex: latex,
                    fontSize: fontSize + 1,
                    mode: .text
                ) else {
                    output.append(styledMarkdown(
                        raw,
                        font: NSFont.monospacedSystemFont(
                            ofSize: fontSize - 1,
                            weight: .regular
                        ),
                        foregroundColor: foregroundColor,
                        lineSpacing: lineSpacing,
                        italic: false
                    ))
                    continue
                }
                let attachment = NSTextAttachment()
                attachment.image = image
                let attachmentText = NSMutableAttributedString(
                    attachment: attachment
                )
                let baselineOffset = min(
                    0,
                    (font.capHeight - image.size.height) / 2
                )
                attachmentText.addAttribute(
                    .baselineOffset,
                    value: baselineOffset,
                    range: NSRange(location: 0, length: attachmentText.length)
                )
                output.append(attachmentText)
            }
        }
        return output
    }

    private static func styledMarkdown(
        _ source: String,
        font: NSFont,
        foregroundColor: NSColor,
        lineSpacing: CGFloat,
        italic: Bool
    ) -> NSAttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
        let parsed = (try? NSAttributedString(
            markdown: source,
            options: options
        )) ?? NSAttributedString(string: source)
        let result = NSMutableAttributedString(attributedString: parsed)
        let fullRange = NSRange(location: 0, length: result.length)
        guard fullRange.length > 0 else {
            return result
        }
        var fontRuns: [(NSRange, NSFont)] = []
        result.enumerateAttribute(
            .font,
            in: fullRange
        ) { value, range, _ in
            let runFont: NSFont
            if let existingFont = value as? NSFont {
                runFont = NSFontManager.shared.convert(
                    existingFont,
                    toSize: font.pointSize
                )
            } else {
                runFont = font
            }
            fontRuns.append((range, runFont))
        }
        for (range, runFont) in fontRuns {
            let styledFont = italic
                ? NSFontManager.shared.convert(
                    runFont,
                    toHaveTrait: .italicFontMask
                )
                : runFont
            result.addAttribute(.font, value: styledFont, range: range)
        }
        result.addAttribute(
            .foregroundColor,
            value: foregroundColor,
            range: fullRange
        )
        applyInlinePresentationIntents(
            to: result,
            baseFont: font,
            forceItalic: italic
        )
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineSpacing = lineSpacing
        result.addAttribute(
            .paragraphStyle,
            value: paragraphStyle,
            range: fullRange
        )
        return result
    }

    private static func applyInlinePresentationIntents(
        to result: NSMutableAttributedString,
        baseFont: NSFont,
        forceItalic: Bool
    ) {
        let fullRange = NSRange(location: 0, length: result.length)
        var runs: [(NSRange, UInt)] = []
        result.enumerateAttribute(
            .inlinePresentationIntent,
            in: fullRange
        ) { value, range, _ in
            guard let rawValue = (value as? NSNumber)?.uintValue else {
                return
            }
            runs.append((range, rawValue))
        }
        for (range, rawValue) in runs {
            var runFont = baseFont
            if rawValue & PresentationMask.stronglyEmphasized != 0 {
                runFont = NSFontManager.shared.convert(
                    runFont,
                    toHaveTrait: .boldFontMask
                )
            }
            if forceItalic || rawValue & PresentationMask.emphasized != 0 {
                runFont = NSFontManager.shared.convert(
                    runFont,
                    toHaveTrait: .italicFontMask
                )
            }
            if rawValue & PresentationMask.code != 0 {
                runFont = NSFont.monospacedSystemFont(
                    ofSize: baseFont.pointSize - 1,
                    weight: .regular
                )
            }
            result.addAttribute(.font, value: runFont, range: range)
            if rawValue & PresentationMask.strikethrough != 0 {
                result.addAttribute(
                    .strikethroughStyle,
                    value: NSUnderlineStyle.single.rawValue,
                    range: range
                )
            }
        }
    }

    private static func resolvedFont(
        size: CGFloat,
        weight: NSFont.Weight,
        italic: Bool
    ) -> NSFont {
        let font = NSFont.systemFont(ofSize: size, weight: weight)
        guard italic else {
            return font
        }
        return NSFontManager.shared.convert(
            font,
            toHaveTrait: .italicFontMask
        )
    }
}

private enum MathImageRenderer {
    private static let cache = NSCache<NSString, NSImage>()

    static func image(
        latex: String,
        fontSize: CGFloat,
        mode: MTMathUILabelMode
    ) -> NSImage? {
        let normalized = normalizedLatex(latex)
        guard !normalized.isEmpty else {
            return nil
        }
        let modeKey: String
        switch mode {
        case .display:
            modeKey = "display"
        case .text:
            modeKey = "text"
        }
        let cacheKey = "\(modeKey)|\(fontSize)|\(normalized)" as NSString
        if let cached = cache.object(forKey: cacheKey) {
            return cached
        }
        let renderer = MTMathImage(
            latex: normalized,
            fontSize: fontSize,
            textColor: NSColor.labelColor,
            labelMode: mode,
            textAlignment: .left
        )
        let (error, image) = renderer.asImage()
        guard error == nil, let image else {
            return nil
        }
        cache.setObject(image, forKey: cacheKey)
        return image
    }

    private static func normalizedLatex(_ latex: String) -> String {
        let trimmed = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        if
            trimmed.hasPrefix("$$"),
            trimmed.hasSuffix("$$"),
            trimmed.count > 4
        {
            return String(trimmed.dropFirst(2).dropLast(2))
        }
        if
            trimmed.hasPrefix("\\["),
            trimmed.hasSuffix("\\]"),
            trimmed.count > 4
        {
            return String(trimmed.dropFirst(2).dropLast(2))
        }
        if
            trimmed.hasPrefix("\\("),
            trimmed.hasSuffix("\\)"),
            trimmed.count > 4
        {
            return String(trimmed.dropFirst(2).dropLast(2))
        }
        if
            trimmed.hasPrefix("$"),
            trimmed.hasSuffix("$"),
            trimmed.count > 2
        {
            return String(trimmed.dropFirst().dropLast())
        }
        return trimmed
    }
}

private enum InlineMathSegment {
    case text(String)
    case math(latex: String, raw: String)
}

private enum InlineMathParser {
    static func containsMath(in source: String) -> Bool {
        parse(source).contains { segment in
            if case .math = segment {
                return true
            }
            return false
        }
    }

    static func parse(_ source: String) -> [InlineMathSegment] {
        var segments: [InlineMathSegment] = []
        var textStart = source.startIndex
        var cursor = source.startIndex

        func appendText(until end: String.Index) {
            guard textStart < end else {
                return
            }
            segments.append(.text(String(source[textStart..<end])))
        }

        while cursor < source.endIndex {
            if source[cursor] == "`", !isEscaped(cursor, in: source) {
                let afterOpening = source.index(after: cursor)
                if let closing = source[afterOpening...].firstIndex(of: "`") {
                    cursor = source.index(after: closing)
                    continue
                }
            }

            if
                source[cursor...].hasPrefix("\\("),
                !isEscaped(cursor, in: source),
                let closing = closingParenthesis(
                    in: source,
                    after: source.index(cursor, offsetBy: 2)
                )
            {
                appendText(until: cursor)
                let contentStart = source.index(cursor, offsetBy: 2)
                let rawEnd = closing.upperBound
                segments.append(.math(
                    latex: String(source[contentStart..<closing.lowerBound]),
                    raw: String(source[cursor..<rawEnd])
                ))
                cursor = rawEnd
                textStart = rawEnd
                continue
            }

            if
                source[cursor] == "$",
                !isEscaped(cursor, in: source),
                let contentStart = validDollarContentStart(
                    in: source,
                    after: cursor
                ),
                let closing = closingDollar(
                    in: source,
                    after: contentStart
                )
            {
                appendText(until: cursor)
                let rawEnd = source.index(after: closing)
                segments.append(.math(
                    latex: String(source[contentStart..<closing]),
                    raw: String(source[cursor..<rawEnd])
                ))
                cursor = rawEnd
                textStart = rawEnd
                continue
            }
            cursor = source.index(after: cursor)
        }
        appendText(until: source.endIndex)
        return segments.isEmpty ? [.text(source)] : segments
    }

    private static func validDollarContentStart(
        in source: String,
        after opening: String.Index
    ) -> String.Index? {
        let next = source.index(after: opening)
        guard
            next < source.endIndex,
            source[next] != "$",
            !source[next].isWhitespace
        else {
            return nil
        }
        return next
    }

    private static func closingDollar(
        in source: String,
        after start: String.Index
    ) -> String.Index? {
        var cursor = start
        while cursor < source.endIndex {
            if source[cursor] == "$", !isEscaped(cursor, in: source) {
                let previous = source.index(before: cursor)
                let next = source.index(after: cursor)
                if
                    !source[previous].isWhitespace,
                    next == source.endIndex || source[next] != "$"
                {
                    return cursor
                }
            }
            cursor = source.index(after: cursor)
        }
        return nil
    }

    private static func closingParenthesis(
        in source: String,
        after start: String.Index
    ) -> Range<String.Index>? {
        var searchStart = start
        while
            let range = source.range(
                of: "\\)",
                range: searchStart..<source.endIndex
            )
        {
            if !isEscaped(range.lowerBound, in: source) {
                return range
            }
            searchStart = range.upperBound
        }
        return nil
    }

    private static func isEscaped(
        _ index: String.Index,
        in source: String
    ) -> Bool {
        var slashCount = 0
        var cursor = index
        while cursor > source.startIndex {
            let previous = source.index(before: cursor)
            guard source[previous] == "\\" else {
                break
            }
            slashCount += 1
            cursor = previous
        }
        return slashCount.isMultiple(of: 2) == false
    }
}

private func inlineMarkdown(_ source: String) -> AttributedString {
    let options = AttributedString.MarkdownParsingOptions(
        interpretedSyntax: .inlineOnlyPreservingWhitespace
    )
    return (try? AttributedString(markdown: source, options: options))
        ?? AttributedString(source)
}
