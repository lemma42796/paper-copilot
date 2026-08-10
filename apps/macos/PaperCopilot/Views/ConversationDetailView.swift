import AppKit
import SwiftUI

private let contextWindowBaselineTokens = 12_000

struct ConversationDetailView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var draft = ""
    @State private var showsContextUsage = false

    var body: some View {
        VStack(spacing: 0) {
            if let conversation = appModel.selectedConversation {
                ConversationTimeline(conversation: conversation)
            } else {
                emptyState
            }
            composer
        }
        .navigationTitle(appModel.selectedConversation?.title ?? "新会话")
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 42))
                .foregroundStyle(.secondary)
            Text("研究你的本地论文")
                .font(.title2.weight(.semibold))
            Text("输入问题后，Paper Copilot 会在已授权的论文目录中工作。")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 4) {
            ZStack(alignment: .topLeading) {
                if draft.isEmpty {
                    Text("询问你的论文库…")
                        .foregroundStyle(.tertiary)
                        .allowsHitTesting(false)
                }

                MessageComposerTextView(text: $draft, onSubmit: send)
            }
            .font(.body)
            .frame(
                minHeight: 22,
                maxHeight: 52,
                alignment: .topLeading
            )

            HStack(spacing: 10) {
                approvalModeMenu
                Text("⇧ + 回车换行")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()

                contextUsageIndicator
                modelMenu
                submitControl
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 7)
        .padding(.bottom, 6)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .overlay {
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.secondary.opacity(0.14), lineWidth: 1)
        }
        .shadow(
            color: .black.opacity(0.05),
            radius: 10,
            x: 0,
            y: 3
        )
        .padding(.horizontal, 24)
        .frame(maxWidth: 860)
        .frame(maxWidth: .infinity)
        .padding(.top, 8)
        .padding(.bottom, 14)
        .background(.background)
    }

    private var contextUsageIndicator: some View {
        ContextUsageRing(usage: appModel.selectedConversation?.latestContextUsage)
            .frame(width: 20, height: 20, alignment: .center)
            .offset(y: 1.5)
            .contentShape(Rectangle())
            .onHover { hovering in
                showsContextUsage = hovering
            }
            .popover(
                isPresented: $showsContextUsage,
                attachmentAnchor: .rect(.bounds),
                arrowEdge: .bottom
            ) {
                ContextUsagePopover(
                    usage: appModel.selectedConversation?.latestContextUsage
                )
            }
    }

    @ViewBuilder
    private var submitControl: some View {
        if let activeJob = appModel.selectedActiveJob {
            Button {
                appModel.interrupt(activeJob.id)
            } label: {
                Image(systemName: "stop.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .frame(width: 32, height: 32)
                    .background(.red)
                    .foregroundStyle(.white)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .help("停止任务")
        } else {
            Button {
                send()
            } label: {
                Group {
                    if appModel.isSubmitting {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 17, weight: .semibold))
                    }
                }
                .frame(width: 32, height: 32)
                .background(canSend ? Color.accentColor : Color.secondary)
                .foregroundStyle(.white)
                .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
            .keyboardShortcut(.return, modifiers: [.command])
            .help("发送")
        }
    }

    private var canSend: Bool {
        appModel.runtimeIsOnline
            && appModel.libraryURL != nil
            && appModel.selectedModel != nil
            && !appModel.isSubmitting
            && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var modelMenu: some View {
        Menu {
            if appModel.availableModels.isEmpty {
                Text("请先在设置中配置模型")
            } else {
                Menu {
                    ForEach(appModel.availableModels) { model in
                        Button {
                            appModel.selectModel(model)
                        } label: {
                            if appModel.selectedModel?.id == model.id {
                                Label(model.menuTitle, systemImage: "checkmark")
                            } else {
                                Text(model.menuTitle)
                            }
                            if let detail = appModel.formulaOCRMenuDetail(
                                for: model
                            ) {
                                Text(detail)
                            }
                        }
                    }
                } label: {
                    HStack {
                        Text("模型")
                        Spacer()
                        Text(appModel.selectedModel?.displayName ?? "未选择")
                            .foregroundStyle(.secondary)
                    }
                }
                if let selectedModel = appModel.selectedModel {
                    Menu {
                        ForEach(selectedModel.availableReasoningEfforts) { effort in
                            Button {
                                appModel.selectReasoningEffort(effort)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(effort.displayName)
                                        if let detail = selectedModel.reasoningDetail(
                                            for: effort
                                        ) {
                                            Text(detail)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    if
                                        selectedModel.effectiveReasoningEffort
                                            == effort
                                    {
                                        Image(systemName: "checkmark")
                                    }
                                }
                            }
                        }
                    } label: {
                        HStack {
                            Text(selectedModel.reasoningControlTitle)
                            Spacer()
                            Text(
                                selectedModel.effectiveReasoningEffort.displayName
                            )
                            .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Text(appModel.selectedModel?.displayName ?? "配置模型")
                    .lineLimit(1)
                if let selectedModel = appModel.selectedModel {
                    Text("· \(selectedModel.effectiveReasoningEffort.displayName)")
                        .foregroundStyle(.secondary)
                }
                Image(systemName: "chevron.down")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .fixedSize()
        .disabled(appModel.hasActiveJobs || appModel.isSubmitting)
        .help(
            appModel.hasActiveJobs
                ? "任务运行期间不能切换模型或思考设置"
                : "选择模型与思考设置"
        )
    }

    private var approvalModeMenu: some View {
        Menu {
            Section("如何批准 Paper Copilot 操作？") {
                ForEach(ApprovalMode.allCases) { mode in
                    Button {
                        appModel.selectApprovalMode(mode)
                    } label: {
                        HStack {
                            Label {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(mode.displayName)
                                    Text(mode.detail)
                                        .foregroundStyle(.secondary)
                                }
                            } icon: {
                                Image(systemName: mode.systemImage)
                            }
                            if appModel.approvalMode == mode {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: appModel.approvalMode.systemImage)
                    .foregroundStyle(.secondary)
                Text(appModel.approvalMode.displayName)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .fixedSize()
        .help(appModel.approvalMode.detail)
    }

    private func send() {
        guard appModel.selectedActiveJob == nil else {
            return
        }
        if appModel.submit(
            draft,
            conversationID: appModel.selectedConversationID
        ) {
            draft = ""
        }
    }
}

private struct ContextUsageRing: View {
    let usage: ChatContextUsage?

    private var fractionUsed: Double {
        guard let usage else {
            return 0
        }
        return contextWindowFractionUsed(usage)
    }

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.18), lineWidth: 3)
            Circle()
                .trim(from: 0, to: fractionUsed)
                .stroke(
                    Color.secondary,
                    style: StrokeStyle(lineWidth: 3, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
        }
        .frame(width: 13, height: 13)
        .accessibilityLabel("工作上下文窗口 token 消耗")
        .accessibilityValue(accessibilityValue)
    }

    private var accessibilityValue: String {
        guard let usage else {
            return "暂无使用记录"
        }
        return "\(usage.contextTokens) / \(usage.contextWindowTokens)"
    }
}

private struct ContextUsagePopover: View {
    let usage: ChatContextUsage?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("工作上下文窗口：")
                .foregroundStyle(.secondary)
            if let usage {
                Text("\(percentageUsed(usage))% 已用（剩余 \(percentageRemaining(usage))%）")
                Text(
                    "已用 \(formattedTokens(usage.contextTokens)) 标记，共 "
                        + formattedTokens(usage.contextWindowTokens)
                )
            } else {
                Text("暂无 token 使用记录")
                    .foregroundStyle(.secondary)
            }
        }
        .font(.callout)
        .padding(14)
        .fixedSize()
    }

    private func percentageUsed(_ usage: ChatContextUsage) -> Int {
        Int((contextWindowFractionUsed(usage) * 100).rounded())
    }

    private func percentageRemaining(_ usage: ChatContextUsage) -> Int {
        max(100 - percentageUsed(usage), 0)
    }

    private func formattedTokens(_ tokens: Int) -> String {
        guard tokens >= 1_000 else {
            return tokens.formatted()
        }
        let thousands = Double(tokens) / 1_000
        let precision = thousands < 100 && tokens % 1_000 != 0 ? 1 : 0
        return thousands.formatted(
            .number.precision(.fractionLength(precision))
        ) + "k"
    }
}

private func contextWindowFractionUsed(_ usage: ChatContextUsage) -> Double {
    guard usage.contextWindowTokens > contextWindowBaselineTokens else {
        return 1
    }
    let effectiveWindow = usage.contextWindowTokens - contextWindowBaselineTokens
    let used = max(usage.contextTokens - contextWindowBaselineTokens, 0)
    return min(max(Double(used) / Double(effectiveWindow), 0), 1)
}

private struct MessageComposerTextView: NSViewRepresentable {
    @Binding var text: String
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let textView = SubmitTextView()
        textView.delegate = context.coordinator
        textView.onSubmit = context.coordinator.submit
        textView.isRichText = false
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.drawsBackground = false
        textView.font = NSFont.preferredFont(forTextStyle: .body)
        textView.textColor = .labelColor
        textView.textContainerInset = .zero
        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true
        textView.autoresizingMask = [.width]
        textView.allowsUndo = true

        let scrollView = NSScrollView()
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = false
        scrollView.hasHorizontalScroller = false
        scrollView.borderType = .noBorder
        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard
            let textView = scrollView.documentView as? SubmitTextView,
            textView.string != text
        else {
            return
        }
        textView.string = text
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: MessageComposerTextView

        init(parent: MessageComposerTextView) {
            self.parent = parent
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else {
                return
            }
            parent.text = textView.string
        }

        func submit() {
            parent.onSubmit()
        }
    }
}

private final class SubmitTextView: NSTextView {
    var onSubmit: () -> Void = {}

    override func keyDown(with event: NSEvent) {
        let isReturn = event.keyCode == 36 || event.keyCode == 76
        guard isReturn, !hasMarkedText() else {
            super.keyDown(with: event)
            return
        }
        if event.modifierFlags.contains(.shift) {
            super.keyDown(with: event)
        } else {
            onSubmit()
        }
    }
}

private struct ConversationTimeline: View {
    @EnvironmentObject private var appModel: AppModel
    let conversation: ChatConversation

    private var latestActivityBoundary: String {
        for job in conversation.jobs.reversed() {
            guard job.status.isActive else {
                continue
            }
            if let sequence = appModel.jobEvents[job.id]?.last(where: {
                $0.activityID != nil && $0.activityPhase != "delta"
            })?.seq {
                return "\(job.id):\(sequence)"
            }
        }
        return ""
    }

    private var latestCompletionBoundary: String {
        conversation.jobs.last(where: { $0.status == .completed })?.id ?? ""
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 20) {
                    ForEach(conversation.jobs) { job in
                        JobTurnView(
                            job: job,
                            events: appModel.jobEvents[job.id, default: []]
                        )
                        .id(job.id)
                    }
                    Color.clear
                        .frame(height: 1)
                        .id("timeline-bottom")
                }
                .padding(24)
                .frame(maxWidth: 860)
                .frame(maxWidth: .infinity)
            }
            .onChange(of: latestCompletionBoundary) { completedJobID in
                guard !completedJobID.isEmpty else {
                    return
                }
                scrollToJob(completedJobID, using: proxy)
            }
            .onChange(of: latestActivityBoundary) { _ in
                guard !latestActivityBoundary.isEmpty else {
                    return
                }
                scrollToTimelineBottom(using: proxy)
            }
            .onAppear {
                scrollToTimelineBottom(using: proxy)
            }
        }
    }

    private func scrollToTimelineBottom(using proxy: ScrollViewProxy) {
        DispatchQueue.main.async {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                proxy.scrollTo("timeline-bottom", anchor: .bottom)
            }
        }
    }

    private func scrollToJob(
        _ jobID: String,
        using proxy: ScrollViewProxy
    ) {
        DispatchQueue.main.async {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                proxy.scrollTo(jobID, anchor: .top)
            }
        }
    }
}

private struct JobTurnView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var approvalDetailsExpanded = false
    @State private var activityAccumulator: JobActivityAccumulator
    @State private var progressDetailsExpanded: Bool
    let job: ChatJobRecord
    let events: [ChatJobEvent]

    init(job: ChatJobRecord, events: [ChatJobEvent]) {
        self.job = job
        self.events = events
        let accumulator = JobActivityAccumulator(events: events)
        _activityAccumulator = State(initialValue: accumulator)
        _progressDetailsExpanded = State(
            initialValue: !accumulator.activities.contains {
                $0.kind == .assistant
            }
        )
    }

    var body: some View {
        VStack(spacing: 14) {
            HStack {
                Spacer(minLength: 80)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(job.spec.request)
                        .textSelection(.enabled)
                        .padding(12)
                        .background(Color.accentColor.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    CopyMessageButton(text: job.spec.request)
                }
            }

            if !events.isEmpty || job.status.isActive {
                progressCard
            }

            if job.result == nil, let answer = streamingAnswer,
               !answer.text.isEmpty {
                StreamingActivityText(
                    text: streamingAnswerPreview(answer.text),
                    selectionEnabled: !job.status.isActive
                )
            }

            if let approval = job.pendingApproval {
                approvalCard(approval)
            }

            if let report = job.result?.reportMarkdown {
                VStack(alignment: .leading, spacing: 4) {
                    MarkdownReportView(
                        markdown: report,
                        pdfDirectory: job.spec.pdfDir,
                        citationTargets: job.result?.citationTargets ?? [:]
                    )
                    CopyMessageButton(text: report)
                }
            } else if let error = job.error, !job.status.isActive {
                Label(error, systemImage: job.status.systemImage)
                    .foregroundStyle(job.status == .failed ? .red : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.quaternary.opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            if !job.attempts.isEmpty {
                JobDiagnosticsView(job: job)
            }
        }
        .onChange(of: events.last?.seq) { _ in
            activityAccumulator.append(events)
        }
    }

    private var progressCard: some View {
        DisclosureGroup(isExpanded: $progressDetailsExpanded) {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(lifecycleEvents) { event in
                    Text(event.message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(executionActivities) { activity in
                    ActivityRow(
                        activity: activity,
                        formalAnswerHasStarted: formalAnswerHasStarted
                    )
                }
            }
            .padding(.top, 8)
        } label: {
            HStack {
                if job.status.isActive {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: job.status.systemImage)
                }
                Text(job.status.displayName)
                    .font(.subheadline.weight(.semibold))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .onChange(of: formalAnswerHasStarted) { hasStarted in
            if hasStarted {
                progressDetailsExpanded = false
            }
        }
    }

    private var lifecycleEvents: [ChatJobEvent] {
        activityAccumulator.lifecycleEvents
    }

    private var executionActivities: [JobActivity] {
        activityAccumulator.activities.filter { $0.kind != .assistant }
    }

    private var streamingAnswer: JobActivity? {
        activityAccumulator.activities.last { $0.kind == .assistant }
    }

    private func streamingAnswerPreview(_ text: String) -> String {
        guard job.status.isActive else {
            return text
        }
        let maximumCharacters = 4_000
        guard text.count > maximumCharacters else {
            return text
        }
        return "生成中仅显示最近 \(maximumCharacters) 个字符；完成报告保留全文。\n\n…\n"
            + String(text.suffix(maximumCharacters))
    }

    private var formalAnswerHasStarted: Bool {
        activityAccumulator.activities.contains {
            $0.kind == .assistant
        }
    }

    private func approvalCard(_ approval: ToolApprovalRequest) -> some View {
        let isResolving = appModel.resolvingApprovalIDs.contains(approval.id)
        let operation = approvalOperation(approval)
        let isDestructive = operation == "trash"
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(
                    systemName: isDestructive
                        ? "trash.fill"
                        : approval.requiresExplicitConfirmation
                            ? "exclamationmark.triangle.fill"
                            : "hand.raised.fill"
                )
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(
                    isDestructive
                        ? Color.red
                        : approval.requiresExplicitConfirmation
                            ? Color.orange
                            : Color.secondary
                )
                .frame(width: 22, height: 22)

                VStack(alignment: .leading, spacing: 3) {
                    Text(approvalTitle(approval))
                        .font(.headline)
                    Text(approval.reason)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            DisclosureGroup(
                "查看操作详情",
                isExpanded: $approvalDetailsExpanded
            ) {
                VStack(alignment: .leading, spacing: 6) {
                    approvalDetailRow("工具", value: approval.toolName)
                    if let toolInput = approval.toolInput {
                        ForEach(
                            toolInput.keys.sorted().filter {
                                !(
                                    approvalOperation(approval) == "write_document"
                                        && $0 == "content"
                                )
                            },
                            id: \.self
                        ) { key in
                            approvalDetailRow(
                                approvalInputLabel(key),
                                value: toolInput[key]?.displayText ?? ""
                            )
                        }
                    }
                    if let beforeSHA = approvalPreviewString(
                        approval,
                        key: "before_sha256"
                    ) {
                        approvalDetailRow("原始哈希", value: beforeSHA)
                    }
                    if let afterSHA = approvalPreviewString(
                        approval,
                        key: "after_sha256"
                    ) {
                        approvalDetailRow("修改哈希", value: afterSHA)
                    }
                    approvalDetailRow(
                        "副作用",
                        value: approval.effects.map(approvalEffectLabel).joined(
                            separator: "、"
                        )
                    )
                }
                .padding(.top, 6)
            }
            .font(.subheadline)

            if let diff = approvalPreviewString(approval, key: "diff"),
               !diff.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("修改预览")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    ScrollView([.horizontal, .vertical]) {
                        Text(diff)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 220)
                    .padding(8)
                    .background(
                        Color.secondary.opacity(0.08),
                        in: RoundedRectangle(cornerRadius: 8)
                    )
                    if approvalPreviewBool(
                        approval,
                        key: "diff_truncated"
                    ) == true {
                        Text("修改预览已达到显示上限，请结合修改前后哈希谨慎确认。")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }

            if approval.requiresExplicitConfirmation {
                Text("仅允许执行上面这一次操作。参数或文件状态变化后，需要重新确认。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                Spacer()

                Button("取消", role: .cancel) {
                    appModel.resolveApproval(
                        jobID: job.id,
                        approvalID: approval.id,
                        approved: false
                    )
                }
                .disabled(isResolving)

                if isDestructive {
                    Button(role: .destructive) {
                        approve(approval)
                    } label: {
                        approvalButtonLabel(
                            approvalActionLabel(approval),
                            isResolving: isResolving
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .disabled(isResolving)
                } else {
                    Button {
                        approve(approval)
                    } label: {
                        approvalButtonLabel(
                            approvalActionLabel(approval),
                            isResolving: isResolving
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isResolving)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            .regularMaterial,
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(.separator.opacity(0.45), lineWidth: 1)
        }
    }

    private func approve(_ approval: ToolApprovalRequest) {
        appModel.resolveApproval(
            jobID: job.id,
            approvalID: approval.id,
            approved: true
        )
    }

    @ViewBuilder
    private func approvalButtonLabel(
        _ title: String,
        isResolving: Bool
    ) -> some View {
        HStack(spacing: 6) {
            if isResolving {
                ProgressView()
                    .controlSize(.small)
            }
            Text(title)
        }
    }

    private func approvalTitle(_ approval: ToolApprovalRequest) -> String {
        if approval.toolName == "library_exec" {
            if let permission = approval.toolInput?["sandbox_permissions"],
               case .string(let value) = permission,
               value == "require_escalated" {
                return "允许在沙箱外执行这条命令？"
            }
            return "允许扩大这条命令的沙箱权限？"
        }
        let count = approvalPathCount(approval)
        switch approvalOperation(approval) {
        case "trash":
            return count == 1
                ? "将这篇论文移到废纸篓？"
                : "将 \(count) 篇论文移到废纸篓？"
        case "restore":
            return "恢复历史回收区中的论文？"
        case "move":
            return count == 1 ? "允许移动这篇论文？" : "允许移动 \(count) 篇论文？"
        case "copy":
            return count == 1 ? "允许复制这篇论文？" : "允许复制 \(count) 篇论文？"
        case "mkdir":
            return "允许创建文件夹？"
        case "write_document":
            return "允许更新这条研究笔记？"
        default:
            return approval.requiresExplicitConfirmation
                ? "确认执行这项高影响操作？"
                : "允许执行这项操作？"
        }
    }

    private func approvalActionLabel(
        _ approval: ToolApprovalRequest
    ) -> String {
        if approval.toolName == "library_exec" {
            return "允许执行一次"
        }
        switch approvalOperation(approval) {
        case "trash":
            return "移到废纸篓"
        case "restore":
            return "恢复"
        case "move":
            return "允许移动"
        case "copy":
            return "允许复制"
        case "mkdir":
            return "允许创建"
        case "write_document":
            return "允许写入笔记"
        default:
            return approval.requiresExplicitConfirmation
                ? "确认执行一次"
                : "允许一次"
        }
    }

    private func approvalOperation(
        _ approval: ToolApprovalRequest
    ) -> String? {
        guard
            let value = approval.toolInput?["operation"],
            case .string(let operation) = value
        else {
            return nil
        }
        return operation
    }

    private func approvalPathCount(
        _ approval: ToolApprovalRequest
    ) -> Int {
        guard
            let value = approval.toolInput?["paths"],
            case .array(let paths) = value
        else {
            return 0
        }
        return paths.count
    }

    private func approvalDetailRow(
        _ label: String,
        value: String
    ) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 62, alignment: .leading)
            Text(value)
                .font(.caption.monospaced())
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func approvalPreviewString(
        _ approval: ToolApprovalRequest,
        key: String
    ) -> String? {
        guard
            let value = approval.changePreview?[key],
            case .string(let text) = value
        else {
            return nil
        }
        return text
    }

    private func approvalPreviewBool(
        _ approval: ToolApprovalRequest,
        key: String
    ) -> Bool? {
        guard
            let value = approval.changePreview?[key],
            case .bool(let flag) = value
        else {
            return nil
        }
        return flag
    }

    private func approvalInputLabel(_ key: String) -> String {
        switch key {
        case "operation":
            return "操作"
        case "paths":
            return "文件"
        case "destination":
            return "目标"
        case "receipt_id":
            return "历史回执"
        case "recursive":
            return "递归"
        case "path":
            return "笔记"
        case "content":
            return "内容"
        case "cmd":
            return "命令"
        case "sandbox_permissions":
            return "沙箱权限"
        case "additional_permissions":
            return "额外权限"
        case "justification":
            return "申请理由"
        case "administrator_privileges":
            return "管理员权限"
        case "timeout_ms":
            return "超时"
        case "yield_time_ms":
            return "返回等待"
        case "max_output_tokens":
            return "输出上限"
        default:
            return key
        }
    }

    private func approvalEffectLabel(_ effect: String) -> String {
        switch effect {
        case "write_library":
            return "修改论文库文件"
        case "write_index":
            return "更新论文索引"
        case "spend_llm_budget":
            return "使用模型额度"
        case "execute_command":
            return "执行命令"
        case "access_network":
            return "访问网络"
        case "write_external":
            return "写入论文库外的文件"
        case "execute_unsandboxed":
            return "在默认沙箱外执行"
        case "use_administrator_privileges":
            return "请求 macOS 管理员权限"
        default:
            return effect
        }
    }
}

private struct CopyMessageButton: View {
    let text: String
    @State private var isHovering = false

    var body: some View {
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
        } label: {
            Image(systemName: "doc.on.doc")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.secondary)
                .frame(width: 28, height: 28)
                .background(
                    isHovering
                        ? Color.secondary.opacity(0.12)
                        : Color.clear
                )
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .overlay(alignment: .top) {
            if isHovering {
                Text("复制")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.primary)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                    .overlay {
                        RoundedRectangle(cornerRadius: 7)
                            .stroke(Color.secondary.opacity(0.16), lineWidth: 1)
                    }
                    .shadow(
                        color: .black.opacity(0.12),
                        radius: 5,
                        x: 0,
                        y: 2
                    )
                    .fixedSize()
                    .offset(y: -34)
                    .allowsHitTesting(false)
            }
        }
        .accessibilityLabel("复制")
        .zIndex(isHovering ? 1 : 0)
        .onHover { hovering in
            isHovering = hovering
        }
    }
}

private struct JobDiagnosticsView: View {
    @EnvironmentObject private var appModel: AppModel
    let job: ChatJobRecord
    @State private var isPresented = false

    var body: some View {
        HStack {
            Button {
                isPresented = true
            } label: {
                Label("查看任务诊断", systemImage: "waveform.path.ecg")
            }
            .buttonStyle(.borderless)
            .font(.caption)
            .foregroundStyle(.secondary)
            .help("查看耗时、错误和调用溯源")
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sheet(isPresented: $isPresented) {
            JobDiagnosticsSheet(job: job)
                .environmentObject(appModel)
        }
    }
}

private struct JobDiagnosticsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var appModel: AppModel
    let job: ChatJobRecord
    @State private var selectedAttempt: Int

    init(job: ChatJobRecord) {
        self.job = job
        _selectedAttempt = State(
            initialValue: job.attempts.last?.number ?? 1
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                diagnosticContent
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(minWidth: 680, idealWidth: 720, minHeight: 540, idealHeight: 620)
        .onAppear {
            loadDiagnostics()
        }
        .onChange(of: selectedAttempt) { _ in
            loadDiagnostics()
        }
        .onChange(of: job.status) { status in
            if !status.isActive {
                loadDiagnostics(force: true)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform.path.ecg")
                .font(.title2)
                .foregroundStyle(.secondary)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 2) {
                Text("任务诊断")
                    .font(.headline)
                Text(job.id)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .textSelection(.enabled)
            }

            Spacer(minLength: 16)

            if job.attempts.count > 1 {
                Picker("Attempt", selection: $selectedAttempt) {
                    ForEach(job.attempts) { attempt in
                        Text("Attempt \(attempt.number)")
                            .tag(attempt.number)
                    }
                }
                .pickerStyle(.menu)
                .fixedSize()
            } else {
                Text("Attempt \(selectedAttempt)")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            if isLoading {
                ProgressView()
                    .controlSize(.small)
            }

            Button {
                loadDiagnostics(force: true)
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.borderless)
            .disabled(isLoading)
            .help("刷新诊断")

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.title3)
                    .symbolRenderingMode(.hierarchical)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help("关闭")
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
    }

    @ViewBuilder
    private var diagnosticContent: some View {
        if
            let diagnostics = appModel.jobDiagnostics[job.id],
            diagnostics.attempt == selectedAttempt
        {
            RolloutDiagnosticsView(diagnostics: diagnostics)
        } else if let error = appModel.jobDiagnosticErrors[job.id] {
            VStack(alignment: .leading, spacing: 8) {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                Button("重试") {
                    loadDiagnostics(force: true)
                }
                .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            VStack(spacing: 10) {
                ProgressView()
                    .controlSize(.regular)
                Text("正在归约本地 trace…")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 320)
        }
    }

    private var isLoading: Bool {
        appModel.loadingDiagnosticJobIDs.contains(job.id)
    }

    private func loadDiagnostics(force: Bool = false) {
        appModel.loadDiagnostics(
            for: job.id,
            attempt: selectedAttempt,
            force: force
        )
    }
}

private struct RolloutDiagnosticsView: View {
    let diagnostics: RolloutDiagnostics

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            summary
            phaseDurations

            if let firstError = diagnostics.firstError {
                diagnosticSection(
                    title: "首个错误",
                    systemImage: "exclamationmark.octagon.fill"
                ) {
                    OperationDiagnosticRow(
                        operation: firstError,
                        emphasizesError: true
                    )
                }
            }

            operationList(
                title: "慢操作（≥ 1 秒）",
                systemImage: "timer",
                operations: diagnostics.slowOperations,
                emptyMessage: "未检测到慢操作。"
            )
            operationList(
                title: "未完成实体",
                systemImage: "hourglass",
                operations: diagnostics.unfinishedOperations,
                emptyMessage: "没有未完成实体。"
            )
            repeatedToolCalls
        }
    }

    private var summary: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 24) {
                    DiagnosticMetric(
                        title: "状态",
                        value: diagnostics.status.displayName
                    )
                    DiagnosticMetric(
                        title: "总耗时",
                        value: formattedDuration(diagnostics.totalDurationMS)
                    )
                    DiagnosticMetric(
                        title: "事件数",
                        value: String(diagnostics.eventCount)
                    )
                }
                Divider()
                LabeledContent("Trace ID") {
                    Text(diagnostics.traceID)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            .padding(.vertical, 2)
        } label: {
            Label("概览", systemImage: "gauge")
                .font(.caption.weight(.semibold))
        }
    }

    private var phaseDurations: some View {
        diagnosticSection(
            title: "各类操作累计耗时",
            systemImage: "chart.bar.xaxis"
        ) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(TraceEntityType.allCases, id: \.rawValue) { entityType in
                    if
                        let duration = diagnostics.phaseDurationMS[
                            entityType.rawValue
                        ]
                    {
                        HStack {
                            Text(entityType.displayName)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(formattedDuration(duration))
                                .font(.caption.monospacedDigit())
                        }
                    }
                }
            }
        }
    }

    private var repeatedToolCalls: some View {
        diagnosticSection(
            title: "重复工具调用（≥ 3 次）",
            systemImage: "repeat"
        ) {
            if diagnostics.repeatedToolCalls.isEmpty {
                Text("未检测到重复工具调用。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(diagnostics.repeatedToolCalls) { call in
                        DisclosureGroup {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("输入 SHA-256")
                                    .foregroundStyle(.secondary)
                                Text(call.inputSHA256)
                                    .font(.caption.monospaced())
                                    .textSelection(.enabled)
                                Text("实体")
                                    .foregroundStyle(.secondary)
                                    .padding(.top, 2)
                                ForEach(call.entityIDs, id: \.self) { entityID in
                                    Text(entityID)
                                        .font(.caption.monospaced())
                                        .textSelection(.enabled)
                                }
                            }
                            .font(.caption)
                            .padding(.top, 4)
                        } label: {
                            HStack {
                                Text(call.toolName)
                                    .font(.caption.weight(.semibold))
                                Spacer()
                                Text("× \(call.count)")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.orange)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func operationList(
        title: String,
        systemImage: String,
        operations: [OperationDiagnostic],
        emptyMessage: String
    ) -> some View {
        diagnosticSection(title: title, systemImage: systemImage) {
            if operations.isEmpty {
                Text(emptyMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(operations) { operation in
                        OperationDiagnosticRow(
                            operation: operation,
                            emphasizesError: false
                        )
                        if operation.id != operations.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private func diagnosticSection<Content: View>(
        title: String,
        systemImage: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                content()
            }
            .padding(.vertical, 2)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label(title, systemImage: systemImage)
                .font(.caption.weight(.semibold))
        }
    }
}

private struct DiagnosticMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.semibold))
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct OperationDiagnosticRow: View {
    let operation: OperationDiagnostic
    let emphasizesError: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(operation.label)
                    .font(.caption.weight(.semibold))
                Text(operation.entityType.displayName)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(operation.status.displayName)
                    .font(.caption2)
                    .foregroundStyle(
                        emphasizesError ? Color.red : Color.secondary
                    )
                Text(formattedDuration(operation.durationMS))
                    .font(.caption.monospacedDigit())
            }
            if let errorType = operation.errorType {
                Text(errorType)
                    .font(.caption.monospaced())
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
            if let errorMessage = operation.errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
            Text(operation.entityID)
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .padding(.vertical, 4)
        .padding(.horizontal, emphasizesError ? 8 : 0)
        .background(emphasizesError ? Color.red.opacity(0.07) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

private func formattedDuration(_ milliseconds: Int?) -> String {
    guard let milliseconds else {
        return "—"
    }
    if milliseconds < 1_000 {
        return "\(milliseconds) ms"
    }
    if milliseconds < 60_000 {
        return String(format: "%.2f s", Double(milliseconds) / 1_000)
    }
    return String(format: "%.1f min", Double(milliseconds) / 60_000)
}

private struct JobActivity: Identifiable {
    enum Kind: String {
        case reasoning
        case assistant
        case tool
    }

    enum Phase: String {
        case started
        case delta
        case completed
        case failed
        case cancelled
    }

    let id: String
    let kind: Kind
    var phase: Phase
    var title: String
    var text: String
    var detail: String
    var liveReasoningTitle: String?
    var completedReasoningPresentation: ReasoningPresentation?
    var reasoningHeaderProbe: String
}

private struct JobActivityAccumulator {
    private(set) var activities: [JobActivity] = []
    private(set) var lifecycleEvents: [ChatJobEvent] = []
    private var indicesByID: [String: Int] = [:]
    private var processedEventCount = 0
    private var lastSequence = 0

    init(events: [ChatJobEvent]) {
        append(events)
    }

    mutating func append(_ events: [ChatJobEvent]) {
        guard events.count >= processedEventCount else {
            self = JobActivityAccumulator(events: events)
            return
        }
        let newEvents = events.dropFirst(processedEventCount)
        processedEventCount = events.count
        for event in newEvents {
            guard event.seq > lastSequence else {
                continue
            }
            lastSequence = event.seq
            guard event.activityID != nil else {
                lifecycleEvents.append(event)
                continue
            }
            guard
                let id = event.activityID,
                let kindValue = event.activityKind,
                let kind = JobActivity.Kind(rawValue: kindValue),
                let phaseValue = event.activityPhase,
                let phase = JobActivity.Phase(rawValue: phaseValue)
            else {
                continue
            }
            let activityIndex: Int
            if let existingIndex = indicesByID[id] {
                activityIndex = existingIndex
            } else {
                activityIndex = activities.count
                indicesByID[id] = activityIndex
                activities.append(JobActivity(
                    id: id,
                    kind: kind,
                    phase: phase,
                    title: event.title ?? defaultTitle(for: kind),
                    text: "",
                    detail: "",
                    liveReasoningTitle: nil,
                    completedReasoningPresentation: nil,
                    reasoningHeaderProbe: ""
                ))
            }
            activities[activityIndex].phase = phase
            if let title = event.title {
                activities[activityIndex].title = title
            }
            if let delta = event.delta {
                activities[activityIndex].text.append(delta)
                updateReasoningHeaderProbe(
                    at: activityIndex,
                    appending: delta
                )
            }
            if let detail = event.detail, !detail.isEmpty {
                if !activities[activityIndex].detail.isEmpty {
                    activities[activityIndex].detail.append("\n")
                }
                activities[activityIndex].detail.append(detail)
            }
            if
                kind == .reasoning,
                phase == .completed || phase == .failed || phase == .cancelled
            {
                activities[activityIndex].completedReasoningPresentation =
                    completedReasoningPresentation(
                        for: activities[activityIndex].text
                    )
                activities[activityIndex].reasoningHeaderProbe = ""
            }
        }
    }

    private mutating func updateReasoningHeaderProbe(
        at index: Int,
        appending delta: String
    ) {
        guard
            activities[index].kind == .reasoning,
            activities[index].liveReasoningTitle == nil,
            activities[index].reasoningHeaderProbe.count < 512
        else {
            return
        }
        let remainingCount = 512
            - activities[index].reasoningHeaderProbe.count
        activities[index].reasoningHeaderProbe.append(
            contentsOf: delta.prefix(remainingCount)
        )
        activities[index].liveReasoningTitle = firstBoldReasoningHeader(
            in: activities[index].reasoningHeaderProbe
        )
    }

    private func defaultTitle(for kind: JobActivity.Kind) -> String {
        switch kind {
        case .reasoning:
            return "思考过程"
        case .assistant:
            return "回答"
        case .tool:
            return "工具调用"
        }
    }
}

private struct ActivityRow: View {
    let activity: JobActivity
    let formalAnswerHasStarted: Bool
    @State private var isExpanded: Bool

    init(activity: JobActivity, formalAnswerHasStarted: Bool) {
        self.activity = activity
        self.formalAnswerHasStarted = formalAnswerHasStarted
        _isExpanded = State(
            initialValue: activity.kind != .reasoning
        )
    }

    var body: some View {
        Group {
            if isLiveReasoning {
                activityLabel
            } else {
                DisclosureGroup(isExpanded: $isExpanded) {
                    activityContent
                } label: {
                    activityLabel
                }
            }
        }
        .padding(10)
        .background(.background.opacity(0.7))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .onChange(of: activity.phase) { phase in
            if activity.kind == .reasoning, phase == .completed {
                isExpanded = false
            }
        }
        .onChange(of: formalAnswerHasStarted) { hasStarted in
            if activity.kind == .reasoning, hasStarted {
                isExpanded = false
            }
        }
    }

    @ViewBuilder
    private var activityContent: some View {
        let displayedReasoning = activity.completedReasoningPresentation
        let displayedText = displayedReasoning?.transcript ?? activity.text
        if !displayedText.isEmpty {
            if activity.kind == .assistant {
                StreamingActivityText(text: displayedText)
            } else if activity.kind == .reasoning {
                ReasoningTranscriptText(text: displayedText)
            } else {
                Text(displayedText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 4)
            }
        }
        if !activity.detail.isEmpty {
            Text(activity.detail)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 4)
        }
    }

    private var activityLabel: some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .foregroundStyle(statusColor)
            Text(displayedTitle)
                .font(.caption.weight(.semibold))
            Spacer()
            if activity.phase == .started || activity.phase == .delta {
                ProgressView()
                    .controlSize(.mini)
            }
        }
    }

    private var isLiveReasoning: Bool {
        activity.kind == .reasoning
            && (activity.phase == .started || activity.phase == .delta)
    }

    private var displayedTitle: String {
        guard activity.kind == .reasoning else {
            return activity.title
        }
        if isLiveReasoning {
            return activity.liveReasoningTitle ?? "正在思考"
        }
        return activity.completedReasoningPresentation?.title
            ?? activity.title
    }

    private var systemImage: String {
        switch activity.kind {
        case .reasoning:
            return "brain"
        case .assistant:
            return "text.bubble"
        case .tool:
            return "wrench.and.screwdriver"
        }
    }

    private var statusColor: Color {
        switch activity.phase {
        case .failed:
            return .red
        case .cancelled:
            return .orange
        case .completed:
            return .green
        case .started, .delta:
            return .secondary
        }
    }
}

private struct ReasoningPresentation {
    let title: String
    let transcript: String
}

private func firstBoldReasoningHeader(in text: String) -> String? {
    guard
        let opening = text.range(of: "**"),
        let closing = text.range(
            of: "**",
            range: opening.upperBound..<text.endIndex
        )
    else {
        return nil
    }
    let header = text[opening.upperBound..<closing.lowerBound]
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return header.isEmpty ? nil : header
}

private func completedReasoningPresentation(
    for text: String
) -> ReasoningPresentation {
    let transcript = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard
        transcript.hasPrefix("**"),
        let closing = transcript.range(
            of: "**",
            range: transcript.index(
                transcript.startIndex,
                offsetBy: 2
            )..<transcript.endIndex
        )
    else {
        return ReasoningPresentation(
            title: "思考过程",
            transcript: transcript
        )
    }

    let titleStart = transcript.index(transcript.startIndex, offsetBy: 2)
    let title = transcript[titleStart..<closing.lowerBound]
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let remainder = transcript[closing.upperBound...]
    guard
        !title.isEmpty,
        remainder.first == "\n" || remainder.first == "\r"
    else {
        return ReasoningPresentation(
            title: "思考过程",
            transcript: transcript
        )
    }
    return ReasoningPresentation(
        title: title,
        transcript: remainder.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
    )
}

private struct ReasoningTranscriptText: View {
    let text: String

    var body: some View {
        ScrollView {
            Text(text)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: 220)
        .padding(.top, 4)
    }
}

private struct StreamingActivityText: View {
    let text: String
    var selectionEnabled = true

    var body: some View {
        if selectionEnabled {
            streamingText
                .textSelection(.enabled)
        } else {
            streamingText
        }
    }

    private var streamingText: some View {
        Text(text)
            .font(.body)
            .foregroundStyle(.primary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 4)
    }
}
