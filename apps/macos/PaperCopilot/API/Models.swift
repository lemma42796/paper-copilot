import Foundation

enum ApprovalMode: String, Codable, CaseIterable, Identifiable {
    case ask
    case autoReview = "auto_review"

    var id: String {
        rawValue
    }

    var displayName: String {
        switch self {
        case .ask:
            return "请求批准"
        case .autoReview:
            return "替我审批"
        }
    }

    var detail: String {
        switch self {
        case .ask:
            return "修改论文文件时始终询问"
        case .autoReview:
            return "仅对检测到的高风险操作请求确认"
        }
    }

    var systemImage: String {
        switch self {
        case .ask:
            return "hand.raised"
        case .autoReview:
            return "checkmark.shield"
        }
    }
}

enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else {
            self = .array(try container.decode([JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var displayText: String {
        switch self {
        case .string(let value):
            return value
        case .number(let value):
            return value.formatted()
        case .bool(let value):
            return value ? "是" : "否"
        case .object(let value):
            return value.keys.sorted().map {
                "\($0): \(value[$0]?.displayText ?? "")"
            }.joined(separator: ", ")
        case .array(let value):
            return value.map(\.displayText).joined(separator: "、")
        case .null:
            return "无"
        }
    }
}

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
    let approvalMode: ApprovalMode

    enum CodingKeys: String, CodingKey {
        case request
        case conversationID = "conversation_id"
        case pdfDir = "pdf_dir"
        case approvalMode = "approval_mode"
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
    let toolCallID: String?
    let toolName: String
    let reason: String
    let effects: [String]
    let toolInput: [String: JSONValue]?
    let inputSHA256: String?
    let requirement: String?
    let autoReviewAllowed: Bool?

    enum CodingKeys: String, CodingKey {
        case id
        case toolCallID = "tool_call_id"
        case toolName = "tool_name"
        case reason
        case effects
        case toolInput = "tool_input"
        case inputSHA256 = "input_sha256"
        case requirement
        case autoReviewAllowed = "auto_review_allowed"
    }

    var requiresExplicitConfirmation: Bool {
        requirement == "explicit_confirmation"
    }
}

struct ChatJobAttempt: Codable, Equatable, Identifiable {
    let number: Int
    let status: String
    let sessionID: String
    let sessionPath: String
    let startedAt: String
    let finishedAt: String?
    let error: String?
    let resumedFromAttempt: Int?

    var id: Int {
        number
    }

    enum CodingKeys: String, CodingKey {
        case number
        case status
        case sessionID = "session_id"
        case sessionPath = "session_path"
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case error
        case resumedFromAttempt = "resumed_from_attempt"
    }
}

struct ChatJobRecord: Codable, Identifiable, Equatable {
    let id: String
    let status: ChatJobStatus
    let createdAt: String
    let updatedAt: String
    let spec: ChatJobSpec
    let attempts: [ChatJobAttempt]
    let result: ChatJobResult?
    let error: String?
    let pendingApproval: ToolApprovalRequest?

    enum CodingKeys: String, CodingKey {
        case id
        case status
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case spec
        case attempts
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

enum TraceEntityType: String, Codable, CaseIterable {
    case rollout
    case turn
    case llmCall = "llm_call"
    case toolCall = "tool_call"
    case compaction

    var displayName: String {
        switch self {
        case .rollout:
            return "任务"
        case .turn:
            return "轮次"
        case .llmCall:
            return "模型调用"
        case .toolCall:
            return "工具调用"
        case .compaction:
            return "上下文压缩"
        }
    }
}

enum TraceStatus: String, Codable {
    case running
    case completed
    case failed
    case cancelled
    case aborted

    var displayName: String {
        switch self {
        case .running:
            return "运行中"
        case .completed:
            return "已完成"
        case .failed:
            return "失败"
        case .cancelled:
            return "已取消"
        case .aborted:
            return "已中止"
        }
    }
}

struct OperationDiagnostic: Codable, Equatable, Identifiable {
    let entityID: String
    let entityType: TraceEntityType
    let label: String
    let status: TraceStatus
    let durationMS: Int?
    let errorType: String?
    let errorMessage: String?

    var id: String {
        entityID
    }

    enum CodingKeys: String, CodingKey {
        case entityID = "entity_id"
        case entityType = "entity_type"
        case label
        case status
        case durationMS = "duration_ms"
        case errorType = "error_type"
        case errorMessage = "error_message"
    }
}

struct RepeatedToolCallDiagnostic: Codable, Equatable, Identifiable {
    let toolName: String
    let inputSHA256: String
    let count: Int
    let entityIDs: [String]

    var id: String {
        "\(toolName):\(inputSHA256)"
    }

    enum CodingKeys: String, CodingKey {
        case toolName = "tool_name"
        case inputSHA256 = "input_sha256"
        case count
        case entityIDs = "entity_ids"
    }
}

struct RolloutDiagnostics: Codable, Equatable {
    let jobID: String
    let attempt: Int
    let traceID: String
    let status: TraceStatus
    let eventCount: Int
    let totalDurationMS: Int?
    let phaseDurationMS: [String: Int]
    let firstError: OperationDiagnostic?
    let slowOperations: [OperationDiagnostic]
    let unfinishedOperations: [OperationDiagnostic]
    let repeatedToolCalls: [RepeatedToolCallDiagnostic]

    enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
        case attempt
        case traceID = "trace_id"
        case status
        case eventCount = "event_count"
        case totalDurationMS = "total_duration_ms"
        case phaseDurationMS = "phase_duration_ms"
        case firstError = "first_error"
        case slowOperations = "slow_operations"
        case unfinishedOperations = "unfinished_operations"
        case repeatedToolCalls = "repeated_tool_calls"
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
    let approvalMode: ApprovalMode

    enum CodingKeys: String, CodingKey {
        case message
        case pdfDir = "pdf_dir"
        case conversationID = "conversation_id"
        case approvalMode = "approval_mode"
    }
}

struct JobApprovalRequest: Encodable {
    let approvalID: String
    let approved: Bool

    enum CodingKeys: String, CodingKey {
        case approvalID = "approval_id"
        case approved
    }
}

struct ConversationDeletionResponse: Decodable {
    let conversationID: String
    let deletedJobs: Int

    enum CodingKeys: String, CodingKey {
        case conversationID = "conversation_id"
        case deletedJobs = "deleted_jobs"
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
