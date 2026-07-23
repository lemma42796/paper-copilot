import SwiftUI

struct ConversationSidebar: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var pendingDeletion: ChatConversation?

    var body: some View {
        List(selection: $appModel.selectedConversationID) {
            ForEach(appModel.conversations) { conversation in
                ConversationRow(
                    conversation: conversation,
                    isDeleting: appModel.deletingConversationIDs.contains(
                        conversation.id
                    )
                ) {
                    pendingDeletion = conversation
                }
                    .tag(Optional(conversation.id))
                    .contextMenu {
                        Button(role: .destructive) {
                            pendingDeletion = conversation
                        } label: {
                            Label("删除会话", systemImage: "trash")
                        }
                        .disabled(
                            conversation.jobs.contains {
                                $0.status.isActive
                            }
                                || appModel.deletingConversationIDs.contains(
                                    conversation.id
                                )
                        )
                    }
            }
        }
        .navigationTitle("Paper Copilot")
        .navigationSplitViewColumnWidth(min: 200, ideal: 240)
        .overlay {
            if appModel.conversations.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.title2)
                    Text("暂无会话")
                }
                .foregroundStyle(.secondary)
            }
        }
        .toolbar {
            ToolbarItem {
                Button {
                    appModel.selectConversation(nil)
                } label: {
                    Label("新会话", systemImage: "square.and.pencil")
                }
                .help("新会话")
            }
        }
        .alert(item: $pendingDeletion) { conversation in
            Alert(
                title: Text("永久删除“\(conversation.title)”？"),
                message: Text(
                    "该会话的消息、任务记录、执行轨迹和报告将从本机彻底删除，且无法恢复。论文原文件与共享知识索引不会被删除。"
                ),
                primaryButton: .destructive(Text("删除")) {
                    appModel.deleteConversation(conversation)
                },
                secondaryButton: .cancel()
            )
        }
    }
}

private struct ConversationRow: View {
    let conversation: ChatConversation
    let isDeleting: Bool
    let onDelete: () -> Void
    @State private var isHovering = false
    @State private var isDeleteButtonHovering = false

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 5) {
                Text(conversation.title)
                    .font(.body.weight(.medium))
                    .lineLimit(2)
                if let latestJob = conversation.latestJob {
                    Label(
                        latestJob.status.displayName,
                        systemImage: latestJob.status.systemImage
                    )
                    .font(.caption)
                    .foregroundStyle(statusColor(latestJob.status))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if isDeleting {
                ProgressView()
                    .controlSize(.small)
            } else if isHovering {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(.system(size: 12, weight: .medium))
                        .frame(width: 24, height: 24)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .foregroundStyle(
                    isDeleteButtonHovering
                        ? Color.primary
                        : Color.secondary.opacity(0.55)
                )
                .disabled(hasActiveJob)
                .help(
                    hasActiveJob
                        ? "请先停止正在运行的任务"
                        : "删除会话"
                )
                .onHover { hovering in
                    withAnimation(.easeOut(duration: 0.1)) {
                        isDeleteButtonHovering = hovering
                    }
                }
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) {
                isHovering = hovering
            }
        }
    }

    private var hasActiveJob: Bool {
        conversation.jobs.contains { $0.status.isActive }
    }

    private func statusColor(_ status: ChatJobStatus) -> Color {
        switch status {
        case .completed:
            return .green
        case .failed:
            return .red
        case .waitingForApproval:
            return .orange
        case .queued, .running, .interrupted:
            return .secondary
        }
    }
}
