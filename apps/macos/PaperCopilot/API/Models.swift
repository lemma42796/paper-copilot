import Foundation

enum ModelThinkingProtocol: String, Codable, CaseIterable, Identifiable {
    case qwen
    case deepSeek = "deepseek"

    var id: String {
        rawValue
    }

    var displayName: String {
        switch self {
        case .qwen:
            return "Qwen / DashScope"
        case .deepSeek:
            return "DeepSeek"
        }
    }
}

enum ReasoningEffort: String, Codable, CaseIterable, Identifiable {
    case low
    case medium
    case high
    case xhigh
    case max

    var id: String {
        rawValue
    }

    var displayName: String {
        switch self {
        case .low:
            return "轻度"
        case .medium:
            return "中"
        case .high:
            return "高"
        case .xhigh:
            return "极高"
        case .max:
            return "最高"
        }
    }

    var qwenThinkingBudget: Int {
        switch self {
        case .low:
            return 4_096
        case .medium:
            return 8_192
        case .high:
            return 16_384
        case .xhigh:
            return 24_576
        case .max:
            return 32_768
        }
    }
}

struct ModelConfiguration: Codable, Identifiable, Equatable {
    let id: UUID
    var displayName: String
    var providerName: String
    var modelID: String
    var baseURL: String
    var inputPricePerMillion: Double
    var cacheCreationPricePerMillion: Double
    var cacheHitPricePerMillion: Double
    var outputPricePerMillion: Double
    var thinkingProtocol: ModelThinkingProtocol?
    var reasoningEffort: ReasoningEffort?
    var isEnabled: Bool

    var menuTitle: String {
        "\(displayName) · \(providerName)"
    }

    var hasValidEndpoint: Bool {
        guard
            let components = URLComponents(string: baseURL),
            let scheme = components.scheme?.lowercased(),
            scheme == "https" || scheme == "http",
            components.host != nil
        else {
            return false
        }
        return true
    }

    var hasCompleteMetadata: Bool {
        !displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !providerName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !modelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && hasValidEndpoint
            && inputPricePerMillion >= 0
            && cacheCreationPricePerMillion >= 0
            && cacheHitPricePerMillion >= 0
            && outputPricePerMillion >= 0
            && effectiveThinkingProtocol != nil
            && !availableReasoningEfforts.isEmpty
    }

    var effectiveThinkingProtocol: ModelThinkingProtocol? {
        if let thinkingProtocol {
            return thinkingProtocol
        }
        let normalizedModel = modelID.lowercased()
        let host = URL(string: baseURL)?.host?.lowercased() ?? ""
        if normalizedModel.hasPrefix("qwen")
            || host.contains("dashscope.aliyuncs.com")
        {
            return .qwen
        }
        if normalizedModel.hasPrefix("deepseek")
            || host.contains("deepseek.com")
        {
            return .deepSeek
        }
        return nil
    }

    var availableReasoningEfforts: [ReasoningEffort] {
        switch effectiveThinkingProtocol {
        case .qwen:
            return ReasoningEffort.allCases
        case .deepSeek:
            return [.high, .max]
        case nil:
            return []
        }
    }

    var effectiveReasoningEffort: ReasoningEffort {
        let configured = reasoningEffort ?? .high
        return availableReasoningEfforts.contains(configured)
            ? configured
            : .high
    }

    var reasoningControlTitle: String {
        effectiveThinkingProtocol == .qwen ? "思考预算" : "推理强度"
    }

    func reasoningDetail(for effort: ReasoningEffort) -> String? {
        switch effectiveThinkingProtocol {
        case .qwen:
            return "\(effort.qwenThinkingBudget / 1_024)K 思考 Token 上限"
        case .deepSeek:
            return effort == .max ? "更快消耗使用额度" : nil
        case nil:
            return nil
        }
    }

    static func qwen36Flash(id: UUID = UUID()) -> ModelConfiguration {
        ModelConfiguration(
            id: id,
            displayName: "Qwen 3.6 Flash",
            providerName: "阿里云百炼",
            modelID: "qwen3.6-flash",
            baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1",
            inputPricePerMillion: 1.2,
            cacheCreationPricePerMillion: 1.5,
            cacheHitPricePerMillion: 0.12,
            outputPricePerMillion: 7.2,
            thinkingProtocol: .qwen,
            reasoningEffort: .high,
            isEnabled: true
        )
    }
}

enum ChatJobStatus: String, Codable {
    case queued
    case running
    case waitingForApproval = "waiting_for_approval"
    case completed
    case interrupted
    case failed

    var isActive: Bool {
        switch self {
        case .queued, .running, .waitingForApproval:
            return true
        case .completed, .interrupted, .failed:
            return false
        }
    }

    var displayName: String {
        switch self {
        case .queued:
            return "排队中"
        case .running:
            return "运行中"
        case .waitingForApproval:
            return "等待确认"
        case .completed:
            return "已完成"
        case .interrupted:
            return "已停止"
        case .failed:
            return "失败"
        }
    }

    var systemImage: String {
        switch self {
        case .queued:
            return "clock"
        case .running:
            return "circle.dotted"
        case .waitingForApproval:
            return "hand.raised"
        case .completed:
            return "checkmark.circle"
        case .interrupted:
            return "stop.circle"
        case .failed:
            return "exclamationmark.triangle"
        }
    }
}

struct ChatJobSpec: Codable, Equatable {
    let request: String
    let conversationID: String?
    let pdfDir: String?

    enum CodingKeys: String, CodingKey {
        case request
        case conversationID = "conversation_id"
        case pdfDir = "pdf_dir"
    }
}

struct ChatJobResult: Codable, Equatable {
    let request: String
    let reportMarkdown: String
    let terminationReason: String
    let costCNY: Double

    enum CodingKeys: String, CodingKey {
        case request
        case reportMarkdown = "report_markdown"
        case terminationReason = "termination_reason"
        case costCNY = "cost_cny"
    }
}

struct ToolApprovalRequest: Codable, Equatable {
    let id: String
    let toolName: String
    let reason: String
    let effects: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case toolName = "tool_name"
        case reason
        case effects
    }
}

struct ChatJobRecord: Codable, Identifiable, Equatable {
    let id: String
    let status: ChatJobStatus
    let createdAt: String
    let updatedAt: String
    let spec: ChatJobSpec
    let result: ChatJobResult?
    let error: String?
    let pendingApproval: ToolApprovalRequest?

    enum CodingKeys: String, CodingKey {
        case id
        case status
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case spec
        case result
        case error
        case pendingApproval = "pending_approval"
    }
}

struct ChatJobEvent: Codable, Identifiable, Equatable {
    let seq: Int
    let timestamp: String
    let type: String
    let status: ChatJobStatus
    let attempt: Int
    let message: String
    let activityID: String?
    let activityKind: String?
    let activityPhase: String?
    let title: String?
    let delta: String?
    let detail: String?

    var id: Int {
        seq
    }

    enum CodingKeys: String, CodingKey {
        case seq
        case timestamp = "ts"
        case type
        case status
        case attempt
        case message
        case activityID = "activity_id"
        case activityKind = "activity_kind"
        case activityPhase = "activity_phase"
        case title
        case delta
        case detail
    }
}

struct ChatJobsResponse: Decodable {
    let jobs: [ChatJobRecord]
}

struct ChatJobEventsResponse: Decodable {
    let events: [ChatJobEvent]
    let nextAfter: Int

    enum CodingKeys: String, CodingKey {
        case events
        case nextAfter = "next_after"
    }
}

struct ChatJobStreamPayload: Decodable {
    let record: ChatJobRecord
    let events: [ChatJobEvent]
    let nextAfter: Int

    enum CodingKeys: String, CodingKey {
        case record
        case events
        case nextAfter = "next_after"
    }
}

struct ChatJobCreateRequest: Encodable {
    let message: String
    let pdfDir: String
    let conversationID: String?

    enum CodingKeys: String, CodingKey {
        case message
        case pdfDir = "pdf_dir"
        case conversationID = "conversation_id"
    }
}

struct ChatConversation: Identifiable, Equatable {
    let id: String
    let jobs: [ChatJobRecord]

    var title: String {
        guard let request = jobs.first?.spec.request else {
            return "新会话"
        }
        let firstLine = request.split(separator: "\n", maxSplits: 1).first
            .map(String.init) ?? request
        if firstLine.count <= 34 {
            return firstLine
        }
        return String(firstLine.prefix(34)) + "…"
    }

    var latestJob: ChatJobRecord? {
        jobs.last
    }
}
