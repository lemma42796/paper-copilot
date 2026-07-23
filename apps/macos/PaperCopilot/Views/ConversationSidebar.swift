import SwiftUI

struct ConversationSidebar: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        List(selection: $appModel.selectedConversationID) {
            ForEach(appModel.conversations) { conversation in
                ConversationRow(conversation: conversation)
                    .tag(Optional(conversation.id))
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
    }
}

private struct ConversationRow: View {
    let conversation: ChatConversation

    var body: some View {
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
        .padding(.vertical, 4)
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
