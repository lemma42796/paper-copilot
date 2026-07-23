import Foundation

@MainActor
final class RuntimeManager {
    private struct ReadyMessage: Decodable {
        let status: String
        let httpURL: URL

        enum CodingKeys: String, CodingKey {
            case status
            case httpURL = "http_url"
        }
    }

    private enum LaunchError: LocalizedError {
        case runtimeAlreadyRunning
        case runtimeUnavailable
        case handshakeEnded
        case invalidHandshake

        var errorDescription: String? {
            switch self {
            case .runtimeAlreadyRunning:
                return "Python Runtime 已在运行。"
            case .runtimeUnavailable:
                return "找不到应用内 Python Runtime，源码开发模式也无法使用 uv。"
            case .handshakeEnded:
                return "Python Runtime 在发送 ready 握手前退出。"
            case .invalidHandshake:
                return "Python Runtime 返回了无效的 ready 握手。"
            }
        }
    }

    private var process: Process?
    private var stdinPipe: Pipe?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?
    private var stopRequested = false
    private var stopCompletion: (() -> Void)?

    func start(
        environmentOverrides: [String: String],
        onReady: @escaping (URL) -> Void,
        onFailure: @escaping (String) -> Void,
        onUnexpectedExit: @escaping (String) -> Void
    ) {
        guard process == nil else {
            onFailure(LaunchError.runtimeAlreadyRunning.localizedDescription)
            return
        }
        guard let launch = launchConfiguration() else {
            onFailure(LaunchError.runtimeUnavailable.localizedDescription)
            return
        }

        let runtimeProcess = Process()
        let runtimeStdin = Pipe()
        let runtimeStdout = Pipe()
        let runtimeStderr = Pipe()
        runtimeProcess.executableURL = launch.executableURL
        runtimeProcess.arguments = launch.arguments
        runtimeProcess.currentDirectoryURL = launch.currentDirectoryURL
        runtimeProcess.environment = ProcessInfo.processInfo.environment.merging(
            environmentOverrides
        ) { _, configuredValue in
            configuredValue
        }
        runtimeProcess.standardInput = runtimeStdin
        runtimeProcess.standardOutput = runtimeStdout
        runtimeProcess.standardError = runtimeStderr
        runtimeStderr.fileHandleForReading.readabilityHandler = { handle in
            _ = handle.availableData
        }
        runtimeProcess.terminationHandler = { [weak self] terminatedProcess in
            Task { @MainActor in
                guard let self else {
                    return
                }
                let expected = self.stopRequested
                let completion = self.stopCompletion
                self.clearProcess()
                if expected {
                    completion?()
                } else {
                    onUnexpectedExit(
                        "Python Runtime 意外退出，状态码 \(terminatedProcess.terminationStatus)。"
                    )
                }
            }
        }

        do {
            try runtimeProcess.run()
        } catch {
            runtimeStderr.fileHandleForReading.readabilityHandler = nil
            onFailure("无法启动 Python Runtime：\(error.localizedDescription)")
            return
        }

        process = runtimeProcess
        stdinPipe = runtimeStdin
        stdoutPipe = runtimeStdout
        stderrPipe = runtimeStderr
        stopRequested = false

        DispatchQueue.global(qos: .userInitiated).async {
            let handshake = Self.readHandshake(from: runtimeStdout.fileHandleForReading)
            Task { @MainActor in
                switch handshake {
                case .success(let url):
                    onReady(url)
                case .failure(let error):
                    onFailure(error.localizedDescription)
                }
            }
        }
    }

    func stop(onStopped: (() -> Void)? = nil) {
        guard let process else {
            onStopped?()
            return
        }
        stopRequested = true
        stopCompletion = onStopped
        if process.isRunning {
            stdinPipe?.fileHandleForWriting.closeFile()
        }
    }

    private func clearProcess() {
        stderrPipe?.fileHandleForReading.readabilityHandler = nil
        process = nil
        stdinPipe = nil
        stdoutPipe = nil
        stderrPipe = nil
        stopRequested = false
        stopCompletion = nil
    }

    private func launchConfiguration() -> (
        executableURL: URL,
        arguments: [String],
        currentDirectoryURL: URL?
    )? {
        if let executableURL = bundledRuntimeExecutableURL() {
            return (
                executableURL,
                ["--exit-on-stdin-eof"],
                executableURL.deletingLastPathComponent()
            )
        }
        guard let sourceRoot = sourceRootURL(), let uvURL = uvExecutableURL() else {
            return nil
        }
        return (
            uvURL,
            ["run", "paper-copilot-runtime", "--exit-on-stdin-eof"],
            sourceRoot
        )
    }

    private func bundledRuntimeExecutableURL() -> URL? {
        let executableURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents", isDirectory: true)
            .appendingPathComponent("Resources", isDirectory: true)
            .appendingPathComponent("PaperCopilotRuntime", isDirectory: true)
            .appendingPathComponent("PaperCopilotRuntime")
        return FileManager.default.isExecutableFile(atPath: executableURL.path)
            ? executableURL
            : nil
    }

    private func sourceRootURL() -> URL? {
        guard
            let path = Bundle.main.object(
                forInfoDictionaryKey: "PaperCopilotSourceRoot"
            ) as? String
        else {
            return nil
        }
        let url = URL(fileURLWithPath: path).standardizedFileURL
        let manifest = url.appendingPathComponent("pyproject.toml")
        return FileManager.default.fileExists(atPath: manifest.path) ? url : nil
    }

    private func uvExecutableURL() -> URL? {
        let environment = ProcessInfo.processInfo.environment
        var candidates: [String] = []
        if let configuredPath = environment["PAPER_COPILOT_UV_PATH"] {
            candidates.append(configuredPath)
        }
        candidates.append(contentsOf: [
            "/opt/homebrew/bin/uv",
            "/usr/local/bin/uv",
            "~/.local/bin/uv",
        ])

        for candidate in candidates {
            let expanded = NSString(string: candidate).expandingTildeInPath
            if FileManager.default.isExecutableFile(atPath: expanded) {
                return URL(fileURLWithPath: expanded)
            }
        }
        return nil
    }

    nonisolated private static func readHandshake(
        from handle: FileHandle
    ) -> Result<URL, Error> {
        var buffer = Data()
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty {
                return .failure(LaunchError.handshakeEnded)
            }
            buffer.append(chunk)
            guard let newline = buffer.firstIndex(of: 0x0A) else {
                continue
            }
            let line = buffer[..<newline]
            guard
                let message = try? JSONDecoder().decode(ReadyMessage.self, from: line),
                message.status == "ready",
                message.httpURL.host == "127.0.0.1"
            else {
                return .failure(LaunchError.invalidHandshake)
            }
            return .success(message.httpURL)
        }
    }
}
