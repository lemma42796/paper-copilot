import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        NavigationSplitView {
            ConversationSidebar()
        } detail: {
            ConversationDetailView()
                .toolbar {
                    ToolbarItemGroup {
                        Button {
                            appModel.chooseLibrary()
                        } label: {
                            Label("选择论文目录", systemImage: "folder")
                        }
                        .help(appModel.libraryURL?.path ?? "选择论文目录")

                        settingsEntry
                    }
                    ToolbarItem {
                        runtimeToolbarStatus
                    }
                }
                .safeAreaInset(edge: .top) {
                    errorBanner
                }
        }
        .onChange(of: appModel.selectedConversationID) { conversationID in
            appModel.selectConversation(conversationID)
        }
    }

    @ViewBuilder
    private var errorBanner: some View {
        if let message = appModel.libraryError ?? appModel.jobError {
            HStack {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                Spacer()
                if appModel.jobError != nil {
                    Button {
                        appModel.dismissJobError()
                    } label: {
                        Image(systemName: "xmark")
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
            .background(.red.opacity(0.08))
        }
    }

    @ViewBuilder
    private var runtimeToolbarStatus: some View {
        switch appModel.runtimeStatus {
        case .starting:
            ProgressView()
                .controlSize(.small)
                .help("Runtime 正在启动")
        case .online:
            Label("Runtime 在线", systemImage: "circle.fill")
                .foregroundStyle(.green)
        case .stopped:
            Label("Runtime 已停止", systemImage: "circle")
                .foregroundStyle(.secondary)
        case .failed:
            Button {
                appModel.retryRuntime()
            } label: {
                Label("重试 Runtime", systemImage: "exclamationmark.triangle")
            }
        }
    }

    @ViewBuilder
    private var settingsEntry: some View {
        if #available(macOS 14.0, *) {
            SettingsLink {
                Label("设置", systemImage: "gearshape")
            }
        } else {
            Button {
                NSApp.sendAction(
                    Selector(("showSettingsWindow:")),
                    to: nil,
                    from: nil
                )
            } label: {
                Label("设置", systemImage: "gearshape")
            }
        }
    }
}
