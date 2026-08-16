import AppKit
import SwiftUI

@main
struct PaperCopilotApp: App {
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appModel)
                .environment(\.locale, appModel.appLanguage.locale)
                .frame(minWidth: 760, minHeight: 520)
                .onReceive(
                    NotificationCenter.default.publisher(
                        for: NSApplication.willTerminateNotification
                    )
                ) { _ in
                    appModel.stopRuntime()
                }
        }
        .windowStyle(.titleBar)

        Settings {
            SettingsView()
                .environmentObject(appModel)
                .environment(\.locale, appModel.appLanguage.locale)
        }
    }
}
