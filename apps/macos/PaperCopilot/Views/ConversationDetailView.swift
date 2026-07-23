import SwiftUI

struct ConversationDetailView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var draft = ""

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
        VStack(alignment: .leading, spacing: 8) {
            TextField("询问你的论文库…", text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.body)
                .lineLimit(1...3)
                .frame(
                    minHeight: 28,
                    maxHeight: 64,
                    alignment: .topLeading
                )
                .onSubmit {
                    send()
                }

            HStack(spacing: 10) {
                Spacer()

                modelMenu
                submitControl
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 8)
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

    @ViewBuilder
    private var submitControl: some View {
        if let activeJob = appModel.selectedActiveJob {
            Button {
                appModel.interrupt(activeJob.id)
            } label: {
                Image(systemName: "stop.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .frame(width: 36, height: 36)
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
                .frame(width: 36, height: 36)
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

private struct ConversationTimeline: View {
    @EnvironmentObject private var appModel: AppModel
    let conversation: ChatConversation

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 20) {
                    ForEach(conversation.jobs) { job in
                        JobTurnView(
                            job: job,
                            events: appModel.jobEvents[job.id, default: []]
                        )
                    }
                    Color.clear
                        .frame(height: 1)
                        .id("timeline-bottom")
                }
                .padding(24)
                .frame(maxWidth: 860)
                .frame(maxWidth: .infinity)
            }
            .onChange(of: appModel.jobs) { _ in
                proxy.scrollTo("timeline-bottom", anchor: .bottom)
            }
            .onChange(of: appModel.jobEvents) { _ in
                proxy.scrollTo("timeline-bottom", anchor: .bottom)
            }
        }
    }
}

private struct JobTurnView: View {
    let job: ChatJobRecord
    let events: [ChatJobEvent]

    var body: some View {
        VStack(spacing: 14) {
            HStack {
                Spacer(minLength: 80)
                Text(job.spec.request)
                    .textSelection(.enabled)
                    .padding(12)
                    .background(Color.accentColor.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            if !events.isEmpty || job.status.isActive {
                progressCard
            }

            if let approval = job.pendingApproval {
                approvalCard(approval)
            }

            if let report = job.result?.reportMarkdown {
                MarkdownReportView(markdown: report)
            } else if let error = job.error, !job.status.isActive {
                Label(error, systemImage: job.status.systemImage)
                    .foregroundStyle(job.status == .failed ? .red : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.quaternary.opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private var progressCard: some View {
        VStack(alignment: .leading, spacing: 8) {
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
            ForEach(lifecycleEvents) { event in
                Text(event.message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            ForEach(visibleActivities) { activity in
                ActivityRow(activity: activity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var lifecycleEvents: [ChatJobEvent] {
        events.filter { $0.activityID == nil }
    }

    private var visibleActivities: [JobActivity] {
        JobActivity.reduce(events).filter {
            job.result == nil || $0.kind != .assistant
        }
    }

    private func approvalCard(_ approval: ToolApprovalRequest) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("任务等待工具操作确认", systemImage: "hand.raised.fill")
                .font(.headline)
                .foregroundStyle(.orange)
            Text(approval.reason)
            Text(approval.toolName)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
            Text("M20 当前可停止此任务；批准或拒绝界面尚未实现。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.orange.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
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

    static func reduce(_ events: [ChatJobEvent]) -> [JobActivity] {
        var order: [String] = []
        var activities: [String: JobActivity] = [:]
        for event in events {
            guard
                let id = event.activityID,
                let kindValue = event.activityKind,
                let kind = Kind(rawValue: kindValue),
                let phaseValue = event.activityPhase,
                let phase = Phase(rawValue: phaseValue)
            else {
                continue
            }
            var activity = activities[id] ?? JobActivity(
                id: id,
                kind: kind,
                phase: phase,
                title: event.title ?? defaultTitle(for: kind),
                text: "",
                detail: ""
            )
            if activities[id] == nil {
                order.append(id)
            }
            activity.phase = phase
            if let title = event.title {
                activity.title = title
            }
            if let delta = event.delta {
                activity.text += delta
            }
            if let detail = event.detail, !detail.isEmpty {
                if !activity.detail.isEmpty {
                    activity.detail += "\n"
                }
                activity.detail += detail
            }
            activities[id] = activity
        }
        return order.compactMap { activities[$0] }
    }

    private static func defaultTitle(for kind: Kind) -> String {
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
    @State private var isExpanded = true

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            if !activity.text.isEmpty {
                Text(activity.text)
                    .font(activity.kind == .reasoning ? .caption : .body)
                    .foregroundStyle(
                        activity.kind == .reasoning ? .secondary : .primary
                    )
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 4)
            }
            if !activity.detail.isEmpty {
                Text(activity.detail)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 4)
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: systemImage)
                    .foregroundStyle(statusColor)
                Text(activity.title)
                    .font(.caption.weight(.semibold))
                Spacer()
                if activity.phase == .started || activity.phase == .delta {
                    ProgressView()
                        .controlSize(.mini)
                }
            }
        }
        .padding(10)
        .background(.background.opacity(0.7))
        .clipShape(RoundedRectangle(cornerRadius: 8))
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

private struct MarkdownReportView: View {
    let markdown: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("报告", systemImage: "doc.richtext")
                .font(.headline)
            Text(attributedMarkdown)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(18)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(.separator, lineWidth: 1)
        }
    }

    private var attributedMarkdown: AttributedString {
        do {
            return try AttributedString(
                markdown: markdown,
                options: .init(interpretedSyntax: .full)
            )
        } catch {
            return AttributedString(markdown)
        }
    }
}
