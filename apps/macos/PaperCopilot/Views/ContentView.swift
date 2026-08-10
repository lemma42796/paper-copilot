import AppKit
import Foundation
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var citationDestination: PaperCitationDestination?
    @State private var citationPanelIsPresented = false
    @State private var citationPanelIsClosing = false
    @State private var citationPanelWidth: CGFloat = 460
    @State private var citationPanelDragStartWidth: CGFloat?

    var body: some View {
        NavigationSplitView {
            ConversationSidebar()
        } detail: {
            GeometryReader { geometry in
                HStack(spacing: 0) {
                    ConversationDetailView { destination in
                        presentCitation(destination)
                    }
                    .frame(minWidth: 360)
                    .layoutPriority(1)

                    citationPanelDivider

                    ZStack {
                        if let citationDestination {
                            PaperCitationPanel(
                                destination: citationDestination,
                                onClose: closeCitation
                            )
                        }
                    }
                    .frame(
                        width: citationPanelIsPresented
                            ? visibleCitationPanelWidth(
                                totalWidth: geometry.size.width
                            )
                            : 0
                    )
                    .opacity(citationPanelIsPresented ? 1 : 0)
                    .clipped()
                    .allowsHitTesting(citationPanelIsPresented)
                }
            }
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
                if citationDestination != nil,
                   !citationPanelIsClosing {
                    ToolbarItem {
                        Button {
                            setCitationPanelPresented(
                                !citationPanelIsPresented
                            )
                        } label: {
                            Label(
                                citationPanelIsPresented
                                    ? "收起论文预览"
                                    : "展开论文预览",
                                systemImage: "sidebar.right"
                            )
                        }
                        .help(
                            citationPanelIsPresented
                                ? "收起论文预览"
                                : "展开论文预览"
                        )
                    }
                }
            }
            .safeAreaInset(edge: .top) {
                errorBanner
            }
        }
        .onChange(of: appModel.selectedConversationID) { conversationID in
            withAnimation(citationPanelAnimation) {
                citationPanelIsPresented = false
            }
            citationDestination = nil
            citationPanelIsClosing = false
            appModel.selectConversation(conversationID)
        }
    }

    private var citationPanelAnimation: Animation? {
        reduceMotion
            ? nil
            : .spring(response: 0.3, dampingFraction: 0.88)
    }

    private func presentCitation(_ destination: PaperCitationDestination) {
        citationPanelIsClosing = false
        if citationPanelIsPresented {
            withAnimation(citationChangeAnimation) {
                citationDestination = destination
            }
            return
        }

        citationDestination = destination
        DispatchQueue.main.async {
            guard
                citationDestination?.id == destination.id,
                !citationPanelIsClosing
            else {
                return
            }
            withAnimation(citationPanelAnimation) {
                citationPanelIsPresented = true
            }
        }
    }

    private func closeCitation() {
        guard let closingID = citationDestination?.id else {
            return
        }
        citationPanelIsClosing = true
        withAnimation(citationPanelAnimation) {
            citationPanelIsPresented = false
        }
        if reduceMotion {
            citationDestination = nil
            citationPanelIsClosing = false
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.34) {
            guard
                citationPanelIsClosing,
                !citationPanelIsPresented,
                citationDestination?.id == closingID
            else {
                return
            }
            citationDestination = nil
            citationPanelIsClosing = false
        }
    }

    private var citationChangeAnimation: Animation? {
        reduceMotion ? nil : .easeInOut(duration: 0.16)
    }

    private func visibleCitationPanelWidth(totalWidth: CGFloat) -> CGFloat {
        min(citationPanelWidth, max(300, totalWidth - 360))
    }

    private var citationPanelDivider: some View {
        ZStack {
            Rectangle()
                .fill(Color.secondary.opacity(0.22))
                .frame(width: 1)
        }
        .frame(width: citationPanelIsPresented ? 8 : 0)
        .opacity(citationPanelIsPresented ? 1 : 0)
        .contentShape(Rectangle())
        .gesture(citationPanelResizeGesture)
        .onHover { hovering in
            guard citationPanelIsPresented else {
                return
            }
            if hovering {
                NSCursor.resizeLeftRight.set()
            } else {
                NSCursor.arrow.set()
            }
        }
    }

    private var citationPanelResizeGesture: some Gesture {
        DragGesture(minimumDistance: 1, coordinateSpace: .global)
            .onChanged { value in
                if citationPanelDragStartWidth == nil {
                    citationPanelDragStartWidth = citationPanelWidth
                }
                let startWidth = citationPanelDragStartWidth
                    ?? citationPanelWidth
                let nextWidth = min(
                    max(startWidth - value.translation.width, 300),
                    720
                )
                guard abs(nextWidth - citationPanelWidth) >= 0.5 else {
                    return
                }
                var transaction = Transaction()
                transaction.disablesAnimations = true
                withTransaction(transaction) {
                    citationPanelWidth = nextWidth
                }
            }
            .onEnded { _ in
                citationPanelDragStartWidth = nil
            }
    }

    private func setCitationPanelPresented(_ isPresented: Bool) {
        citationPanelIsClosing = false
        withAnimation(citationPanelAnimation) {
            citationPanelIsPresented = isPresented
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
