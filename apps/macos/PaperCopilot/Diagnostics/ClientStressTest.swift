import CryptoKit
import Darwin
import Foundation

enum ClientStressTestPreset: String, CaseIterable, Hashable, Identifiable {
    case regression3278
    case burst10000
    case endurance50000
    case formulas500

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .regression3278:
            return appLocalized("3,278 条回归")
        case .burst10000:
            return appLocalized("10,000 条突发")
        case .endurance50000:
            return appLocalized("50,000 条耐久")
        case .formulas500:
            return appLocalized("500 个公式")
        }
    }

    var detail: String {
        switch self {
        case .regression3278:
            return appLocalized("接近已复现故障的事件规模，约 35 秒。")
        case .burst10000:
            return appLocalized("快速批量灌入 10,000 条事件，约 15 秒。")
        case .endurance50000:
            return appLocalized("持续灌入 50,000 条事件，约 20 秒。")
        case .formulas500:
            return appLocalized("先回放 5,000 条事件，再渲染 500 个展示公式。")
        }
    }

    var reasoningDeltaCount: Int {
        switch self {
        case .regression3278:
            return 2_749
        case .burst10000:
            return 8_000
        case .endurance50000:
            return 40_000
        case .formulas500:
            return 4_000
        }
    }

    var assistantDeltaCount: Int {
        switch self {
        case .regression3278:
            return 511
        case .burst10000:
            return 1_982
        case .endurance50000:
            return 9_982
        case .formulas500:
            return 982
        }
    }

    var formulaCount: Int {
        self == .formulas500 ? 500 : 3
    }

    var sourceBatchSize: Int {
        switch self {
        case .regression3278:
            return 1
        case .burst10000, .formulas500:
            return 20
        case .endurance50000:
            return 50
        }
    }

    var sourceBatchIntervalNanoseconds: UInt64 {
        switch self {
        case .regression3278:
            return 8_000_000
        case .burst10000, .endurance50000, .formulas500:
            return 10_000_000
        }
    }

    var totalEventCount: Int {
        reasoningDeltaCount + assistantDeltaCount + 18
    }

    var cooldownSeconds: TimeInterval { 10 }
}

struct ClientStressTestStatus: Equatable {
    enum Phase: String {
        case idle
        case preparing
        case replaying
        case coolingDown
        case completed
        case cancelled
        case failed
    }

    let phase: Phase
    let preset: ClientStressTestPreset?
    let runID: String?
    let deliveredEvents: Int
    let totalEvents: Int
    let progress: Double
    let currentCPUPercent: Double?
    let residentBytes: UInt64?
    let outputPath: String?
    let message: String

    static var idle: ClientStressTestStatus {
        ClientStressTestStatus(
            phase: .idle,
            preset: nil,
            runID: nil,
            deliveredEvents: 0,
            totalEvents: 0,
            progress: 0,
            currentCPUPercent: nil,
            residentBytes: nil,
            outputPath: nil,
            message: appLocalized("尚未运行")
        )
    }

    var isRunning: Bool {
        phase == .preparing || phase == .replaying || phase == .coolingDown
    }
}

struct ClientStressProcessSample: Codable {
    let elapsedSeconds: Double
    let phase: String
    let deliveredEvents: Int
    let cpuPercent: Double
    let residentBytes: UInt64?
    let mainActorGapSeconds: Double
}

struct ClientStressRunMetadata: Codable {
    let generatorVersion: Int
    let eventSource: String
    let modelCallCount: Int
    let runtimeRequestCount: Int
    let apiKeyReadCount: Int
    let runID: String
    let preset: String
    let startedAt: String
    let expectedEventCount: Int
    let reasoningDeltaCount: Int
    let assistantDeltaCount: Int
    let formulaCount: Int
    let sourceBatchSize: Int
    let sourceBatchIntervalMilliseconds: Double
    let cooldownSeconds: Double
}

struct ClientStressTestSummary: Codable {
    let generatorVersion: Int
    let eventSource: String
    let modelCallCount: Int
    let runtimeRequestCount: Int
    let apiKeyReadCount: Int
    let runID: String
    let preset: String
    let reasoningDeltaCount: Int
    let assistantDeltaCount: Int
    let formulaCount: Int
    let sourceBatchSize: Int
    let sourceBatchIntervalMilliseconds: Double
    let cooldownSeconds: Double
    let outcome: String
    let startedAt: String
    let finishedAt: String
    let durationSeconds: Double
    let expectedEventCount: Int
    let actualEventCount: Int
    let expectedFinalSequence: Int
    let actualFinalSequence: Int?
    let orderingValid: Bool
    let expectedReasoningCharacters: Int
    let actualReasoningCharacters: Int
    let expectedAssistantCharacters: Int
    let actualAssistantCharacters: Int
    let expectedReasoningSHA256: String
    let actualReasoningSHA256: String
    let expectedAssistantSHA256: String
    let actualAssistantSHA256: String
    let contentValid: Bool
    let responsivenessThresholdSeconds: Double
    let responsivenessValid: Bool
    let passed: Bool
    let averageCPUPercent: Double
    let maximumCPUPercent: Double
    let cooldownAverageCPUPercent: Double
    let peakResidentBytes: UInt64?
    let maximumMainActorGapSeconds: Double
    let sampleCount: Int
    let error: String?
}

struct ClientStressTextAccumulator {
    private(set) var eventCount = 0
    private(set) var finalSequence: Int?
    private(set) var reasoningText = ""
    private(set) var assistantText = ""

    mutating func append(_ event: ChatJobEvent) -> Void {
        eventCount += 1
        finalSequence = event.seq
        guard let delta = event.delta else {
            return
        }
        switch event.activityKind {
        case "reasoning":
            reasoningText.append(delta)
        case "assistant":
            assistantText.append(delta)
        default:
            break
        }
    }

    var reasoningSHA256: String {
        ClientStressHash.sha256(reasoningText)
    }

    var assistantSHA256: String {
        ClientStressHash.sha256(assistantText)
    }
}

struct ClientStressEventGenerator {
    private enum Stage {
        case lifecycle
        case reasoningStarted
        case reasoningDelta
        case reasoningCompleted
        case assistantStarted
        case assistantDelta
        case assistantCompleted
        case jobCompleted
        case finished
    }

    let preset: ClientStressTestPreset
    private let timestamp: String
    private var stage: Stage = .lifecycle
    private var stageIndex = 0
    private var sequence = 1

    init(
        preset: ClientStressTestPreset,
        timestamp: String
    ) {
        self.preset = preset
        self.timestamp = timestamp
    }

    mutating func next() -> ChatJobEvent? {
        switch stage {
        case .lifecycle:
            guard stageIndex < 13 else {
                stage = .reasoningStarted
                stageIndex = 0
                return next()
            }
            let event: ChatJobEvent
            if stageIndex == 0 {
                event = lifecycleEvent(
                    type: "created",
                    message: appLocalized("已创建客户端压测任务")
                )
            } else if stageIndex == 1 {
                event = lifecycleEvent(
                    type: "started",
                    message: appLocalized("客户端压测开始")
                )
            } else {
                event = lifecycleEvent(
                    type: "progress",
                    message: "压测预热阶段 \(stageIndex - 1)/11"
                )
            }
            stageIndex += 1
            return event
        case .reasoningStarted:
            stage = .reasoningDelta
            return activityEvent(
                kind: "reasoning",
                phase: "started",
                title: appLocalized("思考过程"),
                delta: nil
            )
        case .reasoningDelta:
            guard stageIndex < preset.reasoningDeltaCount else {
                stage = .reasoningCompleted
                stageIndex = 0
                return next()
            }
            let index = stageIndex + 1
            stageIndex += 1
            let prefix = index == 1
                ? (AppLanguage.current == .english
                    ? "**Client stress-test reasoning**\n"
                    : "**客户端压测推理**\n")
                : ""
            return activityEvent(
                kind: "reasoning",
                phase: "delta",
                title: nil,
                delta: prefix + (AppLanguage.current == .english
                    ? "Reasoning fragment \(index): checking event accumulation, main-thread publishing, and scrolling layout.\n"
                    : "推理片段 \(index)：检查事件累计、主线程发布和滚动布局。\n")
            )
        case .reasoningCompleted:
            stage = .assistantStarted
            return activityEvent(
                kind: "reasoning",
                phase: "completed",
                title: appLocalized("思考过程"),
                delta: nil
            )
        case .assistantStarted:
            stage = .assistantDelta
            return activityEvent(
                kind: "assistant",
                phase: "started",
                title: appLocalized("回答"),
                delta: nil
            )
        case .assistantDelta:
            guard stageIndex < preset.assistantDeltaCount else {
                stage = .assistantCompleted
                stageIndex = 0
                return next()
            }
            let index = stageIndex + 1
            stageIndex += 1
            return activityEvent(
                kind: "assistant",
                phase: "delta",
                title: nil,
                delta: AppLanguage.current == .english
                    ? "Answer fragment \(index): synthetic content for validating streaming text integrity.\n"
                    : "回答片段 \(index)：这是用于验证流式文本完整性的合成内容。\n"
            )
        case .assistantCompleted:
            stage = .jobCompleted
            return activityEvent(
                kind: "assistant",
                phase: "completed",
                title: appLocalized("回答"),
                delta: nil
            )
        case .jobCompleted:
            stage = .finished
            return lifecycleEvent(
                type: "completed",
                message: appLocalized("客户端压测事件回放完成")
            )
        case .finished:
            return nil
        }
    }

    private mutating func lifecycleEvent(
        type: String,
        message: String
    ) -> ChatJobEvent {
        defer { sequence += 1 }
        return ChatJobEvent(
            seq: sequence,
            timestamp: timestamp,
            type: type,
            status: type == "completed" ? .completed : .running,
            attempt: 1,
            message: message,
            activityID: nil,
            activityKind: nil,
            activityPhase: nil,
            title: nil,
            delta: nil,
            detail: nil
        )
    }

    private mutating func activityEvent(
        kind: String,
        phase: String,
        title: String?,
        delta: String?
    ) -> ChatJobEvent {
        defer { sequence += 1 }
        return ChatJobEvent(
            seq: sequence,
            timestamp: timestamp,
            type: "progress",
            status: .running,
            attempt: 1,
            message: appLocalized(
                kind == "reasoning" ? "正在思考" : "正在生成回答"
            ),
            activityID: "stress-\(kind)",
            activityKind: kind,
            activityPhase: phase,
            title: title,
            delta: delta,
            detail: nil
        )
    }
}

struct ClientStressResourceProbe {
    private var previousWallTime: TimeInterval
    private var previousCPUTime: TimeInterval

    init() {
        previousWallTime = Date.timeIntervalSinceReferenceDate
        previousCPUTime = Self.processCPUTime()
    }

    mutating func sample(
        startedAt: TimeInterval,
        phase: String,
        deliveredEvents: Int,
        expectedInterval: TimeInterval
    ) -> ClientStressProcessSample {
        let wallTime = Date.timeIntervalSinceReferenceDate
        let cpuTime = Self.processCPUTime()
        let wallDelta = max(wallTime - previousWallTime, 0.000_001)
        let cpuDelta = max(cpuTime - previousCPUTime, 0)
        previousWallTime = wallTime
        previousCPUTime = cpuTime
        return ClientStressProcessSample(
            elapsedSeconds: wallTime - startedAt,
            phase: phase,
            deliveredEvents: deliveredEvents,
            cpuPercent: cpuDelta / wallDelta * 100,
            residentBytes: Self.residentBytes(),
            mainActorGapSeconds: max(wallDelta - expectedInterval, 0)
        )
    }

    private static func processCPUTime() -> TimeInterval {
        var usage = rusage()
        guard getrusage(RUSAGE_SELF, &usage) == 0 else {
            return 0
        }
        let user = TimeInterval(usage.ru_utime.tv_sec)
            + TimeInterval(usage.ru_utime.tv_usec) / 1_000_000
        let system = TimeInterval(usage.ru_stime.tv_sec)
            + TimeInterval(usage.ru_stime.tv_usec) / 1_000_000
        return user + system
    }

    private static func residentBytes() -> UInt64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(
            MemoryLayout<mach_task_basic_info>.size
                / MemoryLayout<natural_t>.size
        )
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(
                to: integer_t.self,
                capacity: Int(count)
            ) { reboundPointer in
                task_info(
                    mach_task_self_,
                    task_flavor_t(MACH_TASK_BASIC_INFO),
                    reboundPointer,
                    &count
                )
            }
        }
        guard result == KERN_SUCCESS else {
            return nil
        }
        return UInt64(info.resident_size)
    }
}

enum ClientStressArtifactStore {
    static func createRunDirectory(runID: String) throws -> URL {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".paper-copilot", isDirectory: true)
            .appendingPathComponent("stress-tests", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }

    static func write<Payload: Encodable>(
        _ payload: Payload,
        named filename: String,
        to directory: URL
    ) throws -> Void {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let data = try encoder.encode(payload)
        try data.write(
            to: directory.appendingPathComponent(filename),
            options: .atomic
        )
    }
}

actor ClientStressSampleRecorder {
    private let directory: URL

    init(directory: URL) {
        self.directory = directory
    }

    func checkpoint(_ samples: [ClientStressProcessSample]) throws -> Void {
        try ClientStressArtifactStore.write(
            samples,
            named: "samples.json",
            to: directory
        )
    }
}

enum ClientStressReportBuilder {
    static func markdown(
        preset: ClientStressTestPreset,
        runID: String
    ) -> String {
        var lines = [
            AppLanguage.current == .english
                ? "# Client Stress Test Report"
                : "# 客户端压测报告",
            "",
            AppLanguage.current == .english
                ? "Run: `\(runID)`"
                : "运行：`\(runID)`",
            "",
            AppLanguage.current == .english
                ? "Preset: **\(preset.displayName)**"
                : "预设：**\(preset.displayName)**",
            "",
            AppLanguage.current == .english
                ? "All content below is locally synthesized without model or network calls."
                : "下列内容全部为本地合成数据，不调用模型或网络。",
            "",
        ]
        for index in 1...preset.formulaCount {
            lines.append(
                AppLanguage.current == .english
                    ? "### Synthetic Formula \(index)"
                    : "### 合成公式 \(index)"
            )
            lines.append("")
            lines.append("```latex")
            lines.append(
                "L_{\(index)} = \\sum_{i=1}^{n} "
                    + "\\left(x_i - \\mu_{\(index)}\\right)^2 / n"
            )
            lines.append("```")
            lines.append("")
        }
        return lines.joined(separator: "\n")
    }
}

enum ClientStressHash {
    static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
