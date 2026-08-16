import AppKit
import Foundation

@MainActor
final class AppModel: ObservableObject {
    private struct ModelConfigurationSnapshot {
        let configurations: [ModelConfiguration]
        let available: [ModelConfiguration]
        let selected: ModelConfiguration?
    }

    private enum ModelConfigurationError: LocalizedError {
        case noConfiguredModel
        case missingProviderKey(String)
        case invalidConfiguration
        case configurationLocked

        var errorDescription: String? {
            switch self {
            case .noConfiguredModel:
                return appLocalized("请先在设置中配置并启用一个模型。")
            case .missingProviderKey(let provider):
                if AppLanguage.current == .english {
                    return "Missing API key for \(provider)."
                }
                return "缺少 \(provider) API Key。"
            case .invalidConfiguration:
                return appLocalized("模型配置不完整或价格无效。")
            case .configurationLocked:
                return appLocalized("任务运行期间不能修改模型配置。")
            }
        }
    }

    enum RuntimeStatus: Equatable {
        case starting
        case online(URL)
        case stopped
        case failed(String)
    }

    @Published private(set) var runtimeStatus: RuntimeStatus = .stopped
    @Published private(set) var libraryURL: URL?
    @Published private(set) var libraryError: String?
    @Published private(set) var jobs: [ChatJobRecord] = []
    @Published private(set) var jobEvents: [String: [ChatJobEvent]] = [:]
    @Published private(set) var jobError: String?
    @Published private(set) var jobDiagnostics: [String: RolloutDiagnostics] = [:]
    @Published private(set) var jobDiagnosticErrors: [String: String] = [:]
    @Published private(set) var loadingDiagnosticJobIDs: Set<String> = []
    @Published private(set) var isSubmitting = false
    @Published private(set) var modelConfigurations: [ModelConfiguration] = []
    @Published private(set) var availableModels: [ModelConfiguration] = []
    @Published private(set) var selectedModel: ModelConfiguration?
    @Published private(set) var formulaOCRStatus: FormulaOCRInstallStatus
    @Published private(set) var clientStressTestStatus =
        ClientStressTestStatus.idle
    @Published private(set) var deletingConversationIDs: Set<String> = []
    @Published private(set) var resolvingApprovalIDs: Set<String> = []
    @Published private(set) var approvalMode: ApprovalMode
    @Published private(set) var appLanguage: AppLanguage
    @Published var selectedConversationID: String?

    private let bookmarkStore = LibraryBookmarkStore()
    private let credentialStore = CredentialStore()
    private let modelStore = ModelConfigurationStore()
    private let runtimeManager = RuntimeManager()
    private let formulaOCRManager = FormulaOCRManager()
    private var api: PaperCopilotAPI?
    private var eventCursors: [String: Int] = [:]
    private var observationTasks: [String: Task<Void, Never>] = [:]
    private var pendingJobEvents: [String: [ChatJobEvent]] = [:]
    private var eventFlushTasks: [String: Task<Void, Never>] = [:]
    private var clientStressTestTask: Task<Void, Never>?
    private var clientStressTestJobIDs: Set<String> = []
    private var requestedDiagnosticAttempts: [String: Int] = [:]
    private var hasInitializedConversationSelection = false
    private static let approvalModeKey = "approvalMode"
    private static let eventPresentationIntervalNanoseconds: UInt64 =
        200_000_000

    init() {
        formulaOCRStatus = .notInstalled
        appLanguage = AppLanguage.current
        approvalMode = ApprovalMode(
            rawValue: UserDefaults.standard.string(
                forKey: Self.approvalModeKey
            ) ?? ""
        ) ?? .ask
        formulaOCRStatus = formulaOCRManager.localStatus()
        restoreLibrary()
        initializeModelRuntime()
    }

    func selectAppLanguage(_ language: AppLanguage) {
        guard appLanguage != language else {
            return
        }
        AppLanguage.save(language)
        appLanguage = language
        if clientStressTestStatus.phase == .idle {
            clientStressTestStatus = .idle
        }
    }

    private func initializeModelRuntime() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                let credentialStore = CredentialStore()
                let modelStore = ModelConfigurationStore()
                try Self.migrateLegacyModelConfiguration(
                    modelStore: modelStore
                )
                let snapshot = try Self.modelConfigurationSnapshot(
                    credentialStore: credentialStore,
                    modelStore: modelStore
                )
                DispatchQueue.main.async {
                    guard let self else {
                        return
                    }
                    self.apply(snapshot)
                    if self.selectedModel != nil {
                        self.startRuntime()
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    self?.runtimeStatus = .failed(
                        "无法迁移已有模型配置：\(error.localizedDescription)"
                    )
                }
            }
        }
    }

    func startRuntime() {
        let environmentOverrides: [String: String]
        do {
            environmentOverrides = try runtimeEnvironmentOverrides()
        } catch {
            runtimeStatus = .failed(
                "无法读取 Runtime 配置：\(error.localizedDescription)"
            )
            return
        }
        runtimeStatus = .starting
        runtimeManager.start(
            environmentOverrides: environmentOverrides,
            onReady: { [weak self] url in
                self?.connectRuntime(url)
            },
            onFailure: { [weak self] message in
                self?.disconnectRuntime()
                self?.runtimeStatus = .failed(message)
            },
            onUnexpectedExit: { [weak self] message in
                self?.disconnectRuntime()
                self?.runtimeStatus = .failed(message)
            }
        )
    }

    func retryRuntime() {
        guard selectedModel != nil else {
            jobError = ModelConfigurationError.noConfiguredModel.localizedDescription
            return
        }
        startRuntime()
    }

    func stopRuntime() {
        disconnectRuntime()
        runtimeManager.stop()
        runtimeStatus = .stopped
    }

    var conversations: [ChatConversation] {
        let grouped = Dictionary(grouping: jobs) { record in
            record.spec.conversationID ?? record.id
        }
        return grouped.map { conversationID, records in
            ChatConversation(
                id: conversationID,
                jobs: records.sorted { $0.createdAt < $1.createdAt }
            )
        }
        .sorted {
            ($0.latestJob?.updatedAt ?? "") > ($1.latestJob?.updatedAt ?? "")
        }
    }

    var selectedConversation: ChatConversation? {
        conversations.first { $0.id == selectedConversationID }
    }

    var selectedActiveJob: ChatJobRecord? {
        selectedConversation?.jobs.last { $0.status.isActive }
    }

    var runtimeIsOnline: Bool {
        if case .online = runtimeStatus {
            return true
        }
        return false
    }

    var hasActiveJobs: Bool {
        jobs.contains { $0.status.isActive }
    }

    func selectModel(_ model: ModelConfiguration) {
        guard
            availableModels.contains(where: { $0.id == model.id }),
            selectedModel?.id != model.id
        else {
            return
        }
        guard !hasActiveJobs, !isSubmitting else {
            jobError = appLocalized("任务运行期间不能切换模型。")
            return
        }
        selectedModel = model
        modelStore.saveSelectedID(model.id)
        restartRuntime()
    }

    func downloadFormulaOCR() {
        guard
            formulaOCRStatus != .downloading,
            !hasActiveJobs,
            !isSubmitting
        else {
            return
        }
        Task {
            await formulaOCRManager.downloadAndInstall { [weak self] status in
                self?.formulaOCRStatus = status
            }
        }
    }

    func startClientStressTest(_ preset: ClientStressTestPreset) {
        guard !clientStressTestStatus.isRunning else {
            return
        }
        guard !hasActiveJobs, !isSubmitting else {
            jobError = appLocalized("请先等待当前任务结束，再运行客户端压测。")
            return
        }

        removePreviousClientStressJobs()
        let timestamp = Self.clientStressTimestamp()
        let runID = "client-stress-\(Self.clientStressRunStamp())-\(UUID().uuidString.prefix(6).lowercased())"
        let conversationID = "conversation-\(runID)"
        let jobID = "job-\(runID)"
        let outputDirectory: URL
        do {
            outputDirectory = try ClientStressArtifactStore.createRunDirectory(
                runID: runID
            )
            try ClientStressArtifactStore.write(
                ClientStressRunMetadata(
                    generatorVersion: 1,
                    eventSource: "local_synthetic",
                    modelCallCount: 0,
                    runtimeRequestCount: 0,
                    apiKeyReadCount: 0,
                    runID: runID,
                    preset: preset.rawValue,
                    startedAt: timestamp,
                    expectedEventCount: preset.totalEventCount,
                    reasoningDeltaCount: preset.reasoningDeltaCount,
                    assistantDeltaCount: preset.assistantDeltaCount,
                    formulaCount: preset.formulaCount,
                    sourceBatchSize: preset.sourceBatchSize,
                    sourceBatchIntervalMilliseconds: Double(
                        preset.sourceBatchIntervalNanoseconds
                    ) / 1_000_000,
                    cooldownSeconds: preset.cooldownSeconds
                ),
                named: "run.json",
                to: outputDirectory
            )
        } catch {
            clientStressTestStatus = ClientStressTestStatus(
                phase: .failed,
                preset: preset,
                runID: runID,
                deliveredEvents: 0,
                totalEvents: preset.totalEventCount,
                progress: 0,
                currentCPUPercent: nil,
                residentBytes: nil,
                outputPath: nil,
                message: "无法创建压测产物目录：\(error.localizedDescription)"
            )
            return
        }

        let record = clientStressRecord(
            jobID: jobID,
            conversationID: conversationID,
            timestamp: timestamp,
            status: .running,
            result: nil,
            error: nil
        )
        clientStressTestJobIDs.insert(jobID)
        eventCursors[jobID] = 0
        jobEvents[jobID] = []
        upsert(record)
        hasInitializedConversationSelection = true
        selectedConversationID = conversationID
        jobError = nil
        clientStressTestStatus = ClientStressTestStatus(
            phase: .preparing,
            preset: preset,
            runID: runID,
            deliveredEvents: 0,
            totalEvents: preset.totalEventCount,
            progress: 0,
            currentCPUPercent: nil,
            residentBytes: nil,
            outputPath: outputDirectory.path,
            message: appLocalized("正在准备本地合成事件，模型调用数为 0。")
        )
        clientStressTestTask = Task { [weak self] in
            await self?.runClientStressTest(
                preset: preset,
                runID: runID,
                jobID: jobID,
                conversationID: conversationID,
                timestamp: timestamp,
                outputDirectory: outputDirectory
            )
        }
    }

    func stopClientStressTest() {
        clientStressTestTask?.cancel()
    }

    func formulaOCRMenuDetail(for model: ModelConfiguration) -> String? {
        guard !model.supportsImageInput else {
            return nil
        }
        if formulaOCRStatus.isInstalled {
            return appLocalized("已安装本地公式 OCR")
        }
        return appLocalized("公式 OCR 未安装，可在设置中下载")
    }

    func selectReasoningEffort(_ effort: ReasoningEffort) {
        guard
            var selectedModel,
            selectedModel.availableReasoningEfforts.contains(effort),
            selectedModel.effectiveReasoningEffort != effort
        else {
            return
        }
        guard !hasActiveJobs, !isSubmitting else {
            jobError = appLocalized("任务运行期间不能切换思考设置。")
            return
        }
        selectedModel.reasoningEffort = effort
        var configurations = modelConfigurations
        guard let index = configurations.firstIndex(
            where: { $0.id == selectedModel.id }
        ) else {
            return
        }
        configurations[index] = selectedModel
        do {
            try modelStore.save(configurations)
            try loadModelConfigurations()
            restartRuntime()
        } catch {
            jobError = "无法更新思考设置：\(error.localizedDescription)"
        }
    }

    func selectApprovalMode(_ mode: ApprovalMode) {
        approvalMode = mode
        UserDefaults.standard.set(
            mode.rawValue,
            forKey: Self.approvalModeKey
        )
    }

    func reloadModelConfigurations(restartRuntime: Bool = true) {
        do {
            try loadModelConfigurations()
        } catch {
            jobError = "无法读取模型配置：\(error.localizedDescription)"
            return
        }

        guard restartRuntime else {
            return
        }
        if selectedModel == nil {
            stopRuntime()
        } else {
            self.restartRuntime()
        }
    }

    func modelAPIKey(for configuration: ModelConfiguration) throws -> String {
        try credentialStore.readModelKey(configuration.id)
    }

    func saveModelConfiguration(
        _ configuration: ModelConfiguration,
        apiKey: String
    ) throws {
        guard !hasActiveJobs, !isSubmitting else {
            throw ModelConfigurationError.configurationLocked
        }
        guard
            configuration.hasCompleteMetadata,
            !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw ModelConfigurationError.invalidConfiguration
        }

        try credentialStore.saveModelKey(apiKey, modelID: configuration.id)
        var configurations = modelConfigurations
        if let index = configurations.firstIndex(
            where: { $0.id == configuration.id }
        ) {
            configurations[index] = configuration
        } else {
            configurations.append(configuration)
        }
        try modelStore.save(configurations)
        reloadModelConfigurations()
    }

    func setModelConfiguration(
        _ configuration: ModelConfiguration,
        enabled: Bool
    ) throws {
        guard !hasActiveJobs, !isSubmitting else {
            throw ModelConfigurationError.configurationLocked
        }
        guard let index = modelConfigurations.firstIndex(
            where: { $0.id == configuration.id }
        ) else {
            return
        }
        var configurations = modelConfigurations
        configurations[index].isEnabled = enabled
        try modelStore.save(configurations)
        reloadModelConfigurations()
    }

    func deleteModelConfiguration(_ configuration: ModelConfiguration) throws {
        guard !hasActiveJobs, !isSubmitting else {
            throw ModelConfigurationError.configurationLocked
        }
        let configurations = modelConfigurations.filter {
            $0.id != configuration.id
        }
        try modelStore.save(configurations)
        try credentialStore.deleteModelKey(configuration.id)
        reloadModelConfigurations()
    }

    @discardableResult
    func submit(_ message: String, conversationID: String? = nil) -> Bool {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSubmitting else {
            return false
        }
        if
            let conversationID,
            conversations.first(where: { $0.id == conversationID })?.jobs
                .contains(where: { clientStressTestJobIDs.contains($0.id) })
                == true
        {
            jobError = appLocalized("客户端压测会话不接受真实模型请求。")
            return false
        }
        guard let api else {
            jobError = appLocalized("本地 Runtime 尚未连接。")
            return false
        }
        guard let libraryURL else {
            jobError = appLocalized("请先选择论文目录。")
            return false
        }
        guard selectedModel != nil else {
            jobError = ModelConfigurationError.noConfiguredModel.localizedDescription
            return false
        }

        isSubmitting = true
        jobError = nil
        Task {
            do {
                let record = try await api.createJob(
                    message: trimmed,
                    pdfDir: libraryURL.path,
                    conversationID: conversationID,
                    approvalMode: approvalMode,
                    maxPapers: paperBudget(for: libraryURL)
                )
                upsert(record)
                selectedConversationID = record.spec.conversationID ?? record.id
                observe(record.id)
            } catch {
                jobError = error.localizedDescription
            }
            isSubmitting = false
        }
        return true
    }

    private func paperBudget(for libraryURL: URL) -> Int {
        guard let enumerator = FileManager.default.enumerator(
            at: libraryURL,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else {
            return 1
        }
        let pdfCount = enumerator.reduce(into: 0) { count, entry in
            guard
                let url = entry as? URL,
                url.pathExtension.caseInsensitiveCompare("pdf") == .orderedSame
            else {
                return
            }
            count += 1
        }
        return max(pdfCount, 1)
    }

    func interrupt(_ jobID: String) {
        if clientStressTestJobIDs.contains(jobID) {
            stopClientStressTest()
            return
        }
        guard let api else {
            jobError = appLocalized("本地 Runtime 尚未连接。")
            return
        }
        jobError = nil
        Task {
            do {
                upsert(try await api.interrupt(jobID))
            } catch {
                jobError = error.localizedDescription
            }
        }
    }

    func resolveApproval(
        jobID: String,
        approvalID: String,
        approved: Bool
    ) {
        guard let api else {
            jobError = appLocalized("本地 Runtime 尚未连接。")
            return
        }
        guard !resolvingApprovalIDs.contains(approvalID) else {
            return
        }
        resolvingApprovalIDs.insert(approvalID)
        jobError = nil
        Task {
            defer {
                resolvingApprovalIDs.remove(approvalID)
            }
            do {
                upsert(
                    try await api.resolveApproval(
                        jobID: jobID,
                        approvalID: approvalID,
                        approved: approved
                    )
                )
            } catch {
                jobError = error.localizedDescription
            }
        }
    }

    func deleteConversation(_ conversation: ChatConversation) {
        let jobIDs = Set(conversation.jobs.map(\.id))
        guard !conversation.jobs.contains(where: { $0.status.isActive }) else {
            jobError = appLocalized("请先停止会话中正在运行的任务。")
            return
        }
        if !jobIDs.isEmpty, jobIDs.isSubset(of: clientStressTestJobIDs) {
            for jobID in jobIDs {
                eventFlushTasks[jobID]?.cancel()
                eventFlushTasks.removeValue(forKey: jobID)
                pendingJobEvents.removeValue(forKey: jobID)
                eventCursors.removeValue(forKey: jobID)
                jobEvents.removeValue(forKey: jobID)
                clientStressTestJobIDs.remove(jobID)
            }
            jobs.removeAll { jobIDs.contains($0.id) }
            if selectedConversationID == conversation.id {
                selectedConversationID = conversations.first?.id
            }
            return
        }
        guard let api else {
            jobError = appLocalized("本地 Runtime 尚未连接。")
            return
        }
        guard !deletingConversationIDs.contains(conversation.id) else {
            return
        }

        let conversationOrder = conversations
        let deletedIndex = conversationOrder.firstIndex {
            $0.id == conversation.id
        }
        deletingConversationIDs.insert(conversation.id)
        jobError = nil
        Task {
            do {
                _ = try await api.deleteConversation(conversation.id)
                for jobID in jobIDs {
                    observationTasks[jobID]?.cancel()
                    observationTasks.removeValue(forKey: jobID)
                    eventFlushTasks[jobID]?.cancel()
                    eventFlushTasks.removeValue(forKey: jobID)
                    pendingJobEvents.removeValue(forKey: jobID)
                    eventCursors.removeValue(forKey: jobID)
                    jobEvents.removeValue(forKey: jobID)
                    jobDiagnostics.removeValue(forKey: jobID)
                    jobDiagnosticErrors.removeValue(forKey: jobID)
                    loadingDiagnosticJobIDs.remove(jobID)
                    requestedDiagnosticAttempts.removeValue(forKey: jobID)
                }
                jobs.removeAll { jobIDs.contains($0.id) }
                if selectedConversationID == conversation.id {
                    let remaining = conversations
                    if let deletedIndex, !remaining.isEmpty {
                        selectedConversationID = remaining[
                            min(deletedIndex, remaining.count - 1)
                        ].id
                    } else {
                        selectedConversationID = remaining.first?.id
                    }
                }
            } catch {
                jobError = error.localizedDescription
            }
            deletingConversationIDs.remove(conversation.id)
        }
    }

    func loadEvents(for jobID: String) {
        guard let api else {
            return
        }
        Task {
            do {
                while true {
                    let response = try await api.events(
                        for: jobID,
                        after: eventCursors[jobID, default: 0]
                    )
                    applyEvents(
                        response.events,
                        nextAfter: response.nextAfter,
                        jobID: jobID
                    )
                    if response.events.count < 1000 {
                        break
                    }
                }
            } catch {
                jobError = error.localizedDescription
            }
        }
    }

    func loadDiagnostics(
        for jobID: String,
        attempt: Int,
        force: Bool = false
    ) {
        guard let api else {
            jobDiagnosticErrors[jobID] = "本地 Runtime 尚未连接。"
            return
        }
        if
            !force,
            jobDiagnostics[jobID]?.attempt == attempt
        {
            return
        }

        requestedDiagnosticAttempts[jobID] = attempt
        loadingDiagnosticJobIDs.insert(jobID)
        jobDiagnosticErrors[jobID] = nil
        Task {
            do {
                let diagnostics = try await api.diagnostics(
                    for: jobID,
                    attempt: attempt
                )
                guard requestedDiagnosticAttempts[jobID] == attempt else {
                    return
                }
                jobDiagnostics[jobID] = diagnostics
            } catch {
                guard requestedDiagnosticAttempts[jobID] == attempt else {
                    return
                }
                jobDiagnosticErrors[jobID] = error.localizedDescription
            }
            if requestedDiagnosticAttempts[jobID] == attempt {
                loadingDiagnosticJobIDs.remove(jobID)
            }
        }
    }

    func selectConversation(_ conversationID: String?) {
        hasInitializedConversationSelection = true
        selectedConversationID = conversationID
        guard
            let conversation = conversations.first(
                where: { $0.id == conversationID }
            )
        else {
            return
        }
        for job in conversation.jobs {
            if !clientStressTestJobIDs.contains(job.id) {
                loadEvents(for: job.id)
            }
        }
    }

    func dismissJobError() {
        jobError = nil
    }

    func chooseLibrary() {
        let panel = NSOpenPanel()
        panel.title = appLocalized("选择论文目录")
        panel.prompt = appLocalized("选择")
        panel.message = appLocalized("Paper Copilot 将读取此目录中的本地 PDF。")
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true

        guard panel.runModal() == .OK, let url = panel.url else {
            return
        }
        do {
            try bookmarkStore.select(url)
            libraryURL = url
            libraryError = nil
        } catch {
            libraryError = "无法保存论文目录授权：\(error.localizedDescription)"
        }
    }

    private func restoreLibrary() {
        do {
            libraryURL = try bookmarkStore.restore()
            libraryError = nil
        } catch {
            libraryURL = nil
            libraryError = error.localizedDescription
        }
    }

    private func runtimeEnvironmentOverrides() throws -> [String: String] {
        guard let selectedModel else {
            throw ModelConfigurationError.noConfiguredModel
        }
        guard
            let thinkingProtocol = selectedModel.effectiveThinkingProtocol
        else {
            throw ModelConfigurationError.invalidConfiguration
        }
        let providerKey = try credentialStore.readModelKey(selectedModel.id)
        guard !providerKey.trimmingCharacters(
            in: .whitespacesAndNewlines
        ).isEmpty else {
            throw ModelConfigurationError.missingProviderKey(
                selectedModel.providerName
            )
        }
        var environment: [String: String] = [
            "LLM_BASE_URL": selectedModel.baseURL,
            "LLM_MODEL": selectedModel.modelID,
            "LLM_API_KEY": providerKey,
            "LLM_INPUT_PER_MTOK_CNY": String(
                selectedModel.inputPricePerMillion
            ),
            "LLM_CACHE_CREATE_PER_MTOK_CNY": String(
                selectedModel.cacheCreationPricePerMillion
            ),
            "LLM_CACHE_HIT_PER_MTOK_CNY": String(
                selectedModel.cacheHitPricePerMillion
            ),
            "LLM_OUTPUT_PER_MTOK_CNY": String(
                selectedModel.outputPricePerMillion
            ),
            "LLM_THINKING_PROTOCOL": thinkingProtocol.rawValue,
            "LLM_REASONING_EFFORT":
                selectedModel.effectiveReasoningEffort.rawValue,
            "LLM_INPUT_MODALITIES": selectedModel.effectiveInputModalities
                .map(\.rawValue)
                .joined(separator: ","),
        ]
        let dashscopeAPIKey = selectedModel.isDashScopeEndpoint
            ? providerKey
            : try credentialStore.read(.dashscopeAPIKey)
        if !dashscopeAPIKey.isEmpty {
            environment["DASHSCOPE_API_KEY"] = dashscopeAPIKey
        }
        return environment
    }

    nonisolated private static func migrateLegacyModelConfiguration(
        modelStore: ModelConfigurationStore
    ) throws {
        let defaults = UserDefaults.standard
        let migrationKey = "dynamicModelConfigurationMigrationV1"
        guard !defaults.bool(forKey: migrationKey) else {
            return
        }

        if !(try modelStore.load()).isEmpty {
            defaults.set(true, forKey: migrationKey)
            return
        }

        let qwenWasEnabled = defaults.bool(
            forKey: "modelEnabled.qwen3.6-flash"
        )
        let legacyModelID = defaults.string(forKey: "llmModel")
        if qwenWasEnabled || legacyModelID == "qwen3.6-flash" {
            var qwen = ModelConfiguration.qwen37Flash()
            qwen.baseURL =
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            try modelStore.save([qwen])
            modelStore.saveSelectedID(qwen.id)
        }
        defaults.set(true, forKey: migrationKey)
    }

    nonisolated private static func modelConfigurationSnapshot(
        credentialStore: CredentialStore,
        modelStore: ModelConfigurationStore
    ) throws -> ModelConfigurationSnapshot {
        let configurations = try modelStore.load()
        var available: [ModelConfiguration] = []
        for configuration in configurations
        where configuration.isEnabled && configuration.hasCompleteMetadata {
            let apiKey = try credentialStore.readModelKey(configuration.id)
            if !apiKey.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).isEmpty {
                available.append(configuration)
            }
        }

        let storedID = modelStore.selectedID()
        let selected: ModelConfiguration?
        if
            let storedID,
            let stored = available.first(where: { $0.id == storedID })
        {
            selected = stored
        } else {
            selected = available.first
            modelStore.saveSelectedID(selected?.id)
        }
        return ModelConfigurationSnapshot(
            configurations: configurations,
            available: available,
            selected: selected
        )
    }

    private func loadModelConfigurations() throws {
        apply(
            try Self.modelConfigurationSnapshot(
                credentialStore: credentialStore,
                modelStore: modelStore
            )
        )
    }

    private func apply(_ snapshot: ModelConfigurationSnapshot) {
        modelConfigurations = snapshot.configurations
        availableModels = snapshot.available
        selectedModel = snapshot.selected
    }

    private func restartRuntime() {
        disconnectRuntime()
        runtimeStatus = .starting
        runtimeManager.stop { [weak self] in
            self?.startRuntime()
        }
    }

    private func runClientStressTest(
        preset: ClientStressTestPreset,
        runID: String,
        jobID: String,
        conversationID: String,
        timestamp: String,
        outputDirectory: URL
    ) async {
        defer {
            clientStressTestTask = nil
        }

        let startedDate = Date()
        let startedWallTime = Date.timeIntervalSinceReferenceDate
        var generator = ClientStressEventGenerator(
            preset: preset,
            timestamp: timestamp
        )
        let sampleRecorder = ClientStressSampleRecorder(
            directory: outputDirectory
        )
        var expected = ClientStressTextAccumulator()
        var probe = ClientStressResourceProbe()
        var samples: [ClientStressProcessSample] = []
        var deliveredEvents = 0
        var latestCPUPercent: Double?
        var latestResidentBytes: UInt64?
        var lastSampleWallTime = startedWallTime
        var lastArtifactCheckpointWallTime = startedWallTime - 2
        let sampleInterval: TimeInterval = 0.5
        let artifactCheckpointInterval: TimeInterval = 2

        do {
            while true {
                try Task.checkCancellation()
                var batch: [ChatJobEvent] = []
                batch.reserveCapacity(preset.sourceBatchSize)
                for _ in 0..<preset.sourceBatchSize {
                    guard let event = generator.next() else {
                        break
                    }
                    expected.append(event)
                    batch.append(event)
                }
                guard let finalSequence = batch.last?.seq else {
                    break
                }
                applyEvents(
                    batch,
                    nextAfter: finalSequence,
                    jobID: jobID
                )
                deliveredEvents += batch.count

                let now = Date.timeIntervalSinceReferenceDate
                if now - lastSampleWallTime >= sampleInterval {
                    let sample = probe.sample(
                        startedAt: startedWallTime,
                        phase: "replaying",
                        deliveredEvents: deliveredEvents,
                        expectedInterval: sampleInterval
                    )
                    samples.append(sample)
                    latestCPUPercent = sample.cpuPercent
                    latestResidentBytes = sample.residentBytes
                    lastSampleWallTime = now
                    if
                        now - lastArtifactCheckpointWallTime
                            >= artifactCheckpointInterval
                    {
                        try await sampleRecorder.checkpoint(samples)
                        lastArtifactCheckpointWallTime = now
                    }
                    clientStressTestStatus = ClientStressTestStatus(
                        phase: .replaying,
                        preset: preset,
                        runID: runID,
                        deliveredEvents: deliveredEvents,
                        totalEvents: preset.totalEventCount,
                        progress: 0.9 * Double(deliveredEvents)
                            / Double(preset.totalEventCount),
                        currentCPUPercent: latestCPUPercent,
                        residentBytes: latestResidentBytes,
                        outputPath: outputDirectory.path,
                        message: appLocalized("本地回放中；未连接模型或 Runtime。")
                    )
                }
                try await Task.sleep(
                    nanoseconds: preset.sourceBatchIntervalNanoseconds
                )
            }

            flushPendingEvents(for: jobID)
            let report = ClientStressReportBuilder.markdown(
                preset: preset,
                runID: runID
            )
            upsert(clientStressRecord(
                jobID: jobID,
                conversationID: conversationID,
                timestamp: timestamp,
                status: .completed,
                result: ChatJobResult(
                    request: "客户端本地压测：\(preset.displayName)",
                    reportMarkdown: report,
                    terminationReason: "local_stress_test",
                    costCNY: 0,
                    citationTargets: [:]
                ),
                error: nil
            ))

            let cooldownStarted = Date.timeIntervalSinceReferenceDate
            while true {
                try Task.checkCancellation()
                let now = Date.timeIntervalSinceReferenceDate
                let cooldownElapsed = now - cooldownStarted
                guard cooldownElapsed < preset.cooldownSeconds else {
                    break
                }
                try await Task.sleep(nanoseconds: 500_000_000)
                let sample = probe.sample(
                    startedAt: startedWallTime,
                    phase: "cooldown",
                    deliveredEvents: deliveredEvents,
                    expectedInterval: sampleInterval
                )
                samples.append(sample)
                latestCPUPercent = sample.cpuPercent
                latestResidentBytes = sample.residentBytes
                if
                    now - lastArtifactCheckpointWallTime
                        >= artifactCheckpointInterval
                {
                    try await sampleRecorder.checkpoint(samples)
                    lastArtifactCheckpointWallTime = now
                }
                clientStressTestStatus = ClientStressTestStatus(
                    phase: .coolingDown,
                    preset: preset,
                    runID: runID,
                    deliveredEvents: deliveredEvents,
                    totalEvents: preset.totalEventCount,
                    progress: min(
                        0.9 + 0.1 * cooldownElapsed / preset.cooldownSeconds,
                        0.99
                    ),
                    currentCPUPercent: latestCPUPercent,
                    residentBytes: latestResidentBytes,
                    outputPath: outputDirectory.path,
                    message: appLocalized("事件完成，正在观察 CPU 与内存回落。")
                )
            }

            try finishClientStressTest(
                outcome: "completed",
                error: nil,
                preset: preset,
                runID: runID,
                jobID: jobID,
                startedDate: startedDate,
                startedWallTime: startedWallTime,
                expected: expected,
                samples: samples,
                outputDirectory: outputDirectory
            )
        } catch is CancellationError {
            flushPendingEvents(for: jobID)
            upsert(clientStressRecord(
                jobID: jobID,
                conversationID: conversationID,
                timestamp: timestamp,
                status: .interrupted,
                result: nil,
                error: appLocalized("用户停止了客户端压测。")
            ))
            do {
                try finishClientStressTest(
                    outcome: "cancelled",
                    error: appLocalized("用户停止"),
                    preset: preset,
                    runID: runID,
                    jobID: jobID,
                    startedDate: startedDate,
                    startedWallTime: startedWallTime,
                    expected: expected,
                    samples: samples,
                    outputDirectory: outputDirectory
                )
            } catch {
                clientStressTestStatus = failedClientStressStatus(
                    preset: preset,
                    runID: runID,
                    deliveredEvents: deliveredEvents,
                    outputDirectory: outputDirectory,
                    message: "压测已停止，但写入产物失败：\(error.localizedDescription)"
                )
            }
        } catch {
            flushPendingEvents(for: jobID)
            upsert(clientStressRecord(
                jobID: jobID,
                conversationID: conversationID,
                timestamp: timestamp,
                status: .failed,
                result: nil,
                error: error.localizedDescription
            ))
            do {
                try finishClientStressTest(
                    outcome: "failed",
                    error: error.localizedDescription,
                    preset: preset,
                    runID: runID,
                    jobID: jobID,
                    startedDate: startedDate,
                    startedWallTime: startedWallTime,
                    expected: expected,
                    samples: samples,
                    outputDirectory: outputDirectory
                )
            } catch {
                clientStressTestStatus = failedClientStressStatus(
                    preset: preset,
                    runID: runID,
                    deliveredEvents: deliveredEvents,
                    outputDirectory: outputDirectory,
                    message: "压测失败且无法写入产物：\(error.localizedDescription)"
                )
            }
        }
    }

    private func finishClientStressTest(
        outcome: String,
        error: String?,
        preset: ClientStressTestPreset,
        runID: String,
        jobID: String,
        startedDate: Date,
        startedWallTime: TimeInterval,
        expected: ClientStressTextAccumulator,
        samples: [ClientStressProcessSample],
        outputDirectory: URL
    ) throws {
        let actualEvents = jobEvents[jobID, default: []]
        var actual = ClientStressTextAccumulator()
        for event in actualEvents {
            actual.append(event)
        }
        let orderingValid = actualEvents.enumerated().allSatisfy {
            index, event in
            event.seq == index + 1
        }
        let contentValid = outcome == "completed"
            && expected.eventCount == preset.totalEventCount
            && actual.eventCount == expected.eventCount
            && actual.reasoningSHA256 == expected.reasoningSHA256
            && actual.assistantSHA256 == expected.assistantSHA256
            && orderingValid
        let responsivenessThresholdSeconds = 1.0
        let maximumMainActorGapSeconds = samples
            .map(\.mainActorGapSeconds)
            .max() ?? 0
        let responsivenessValid = outcome == "completed"
            && maximumMainActorGapSeconds <= responsivenessThresholdSeconds
        let passed = contentValid && responsivenessValid
        let cpuValues = samples.map(\.cpuPercent)
        let cooldownCPUValues = samples
            .filter { $0.phase == "cooldown" }
            .map(\.cpuPercent)
        let finishedDate = Date()
        let summary = ClientStressTestSummary(
            generatorVersion: 1,
            eventSource: "local_synthetic",
            modelCallCount: 0,
            runtimeRequestCount: 0,
            apiKeyReadCount: 0,
            runID: runID,
            preset: preset.rawValue,
            reasoningDeltaCount: preset.reasoningDeltaCount,
            assistantDeltaCount: preset.assistantDeltaCount,
            formulaCount: preset.formulaCount,
            sourceBatchSize: preset.sourceBatchSize,
            sourceBatchIntervalMilliseconds: Double(
                preset.sourceBatchIntervalNanoseconds
            ) / 1_000_000,
            cooldownSeconds: preset.cooldownSeconds,
            outcome: outcome,
            startedAt: Self.clientStressTimestamp(startedDate),
            finishedAt: Self.clientStressTimestamp(finishedDate),
            durationSeconds: Date.timeIntervalSinceReferenceDate
                - startedWallTime,
            expectedEventCount: preset.totalEventCount,
            actualEventCount: actual.eventCount,
            expectedFinalSequence: preset.totalEventCount,
            actualFinalSequence: actual.finalSequence,
            orderingValid: orderingValid,
            expectedReasoningCharacters: expected.reasoningText.count,
            actualReasoningCharacters: actual.reasoningText.count,
            expectedAssistantCharacters: expected.assistantText.count,
            actualAssistantCharacters: actual.assistantText.count,
            expectedReasoningSHA256: expected.reasoningSHA256,
            actualReasoningSHA256: actual.reasoningSHA256,
            expectedAssistantSHA256: expected.assistantSHA256,
            actualAssistantSHA256: actual.assistantSHA256,
            contentValid: contentValid,
            responsivenessThresholdSeconds: responsivenessThresholdSeconds,
            responsivenessValid: responsivenessValid,
            passed: passed,
            averageCPUPercent: average(cpuValues),
            maximumCPUPercent: cpuValues.max() ?? 0,
            cooldownAverageCPUPercent: average(cooldownCPUValues),
            peakResidentBytes: samples.compactMap(\.residentBytes).max(),
            maximumMainActorGapSeconds: maximumMainActorGapSeconds,
            sampleCount: samples.count,
            error: error
        )
        try ClientStressArtifactStore.write(
            summary,
            named: "summary.json",
            to: outputDirectory
        )
        try ClientStressArtifactStore.write(
            samples,
            named: "samples.json",
            to: outputDirectory
        )

        let phase: ClientStressTestStatus.Phase
        let message: String
        switch outcome {
        case "completed":
            phase = passed ? .completed : .failed
            if !contentValid {
                message = appLocalized("压测完成，但事件完整性校验失败。")
            } else if !responsivenessValid {
                message = AppLanguage.current == .english
                    ? String(
                        format: "Events were complete, but the longest main-thread pause was %.2f seconds; responsiveness failed.",
                        maximumMainActorGapSeconds
                    )
                    : String(
                        format: "事件完整，但主线程最长停顿 %.2f 秒，响应性未通过。",
                        maximumMainActorGapSeconds
                    )
            } else {
                message = appLocalized("压测通过，事件完整且主线程停顿未超过 1 秒；模型调用数为 0。")
            }
        case "cancelled":
            phase = .cancelled
            message = appLocalized("压测已停止，已保存部分产物。")
        default:
            phase = .failed
            message = "压测失败：\(error ?? "未知错误")"
        }
        clientStressTestStatus = ClientStressTestStatus(
            phase: phase,
            preset: preset,
            runID: runID,
            deliveredEvents: actual.eventCount,
            totalEvents: preset.totalEventCount,
            progress: outcome == "completed" ? 1 : 0,
            currentCPUPercent: samples.last?.cpuPercent,
            residentBytes: samples.last?.residentBytes,
            outputPath: outputDirectory.path,
            message: message
        )
    }

    private func clientStressRecord(
        jobID: String,
        conversationID: String,
        timestamp: String,
        status: ChatJobStatus,
        result: ChatJobResult?,
        error: String?
    ) -> ChatJobRecord {
        ChatJobRecord(
            id: jobID,
            status: status,
            createdAt: timestamp,
            updatedAt: Self.clientStressTimestamp(),
            spec: ChatJobSpec(
                request: appLocalized("客户端本地压测"),
                conversationID: conversationID,
                pdfDir: nil,
                approvalMode: .ask
            ),
            attempts: [],
            result: result,
            error: error,
            pendingApproval: nil,
            contextUsage: nil
        )
    }

    private func failedClientStressStatus(
        preset: ClientStressTestPreset,
        runID: String,
        deliveredEvents: Int,
        outputDirectory: URL,
        message: String
    ) -> ClientStressTestStatus {
        ClientStressTestStatus(
            phase: .failed,
            preset: preset,
            runID: runID,
            deliveredEvents: deliveredEvents,
            totalEvents: preset.totalEventCount,
            progress: 0,
            currentCPUPercent: nil,
            residentBytes: nil,
            outputPath: outputDirectory.path,
            message: message
        )
    }

    private func removePreviousClientStressJobs() {
        for jobID in clientStressTestJobIDs {
            eventFlushTasks[jobID]?.cancel()
            eventFlushTasks.removeValue(forKey: jobID)
            pendingJobEvents.removeValue(forKey: jobID)
            eventCursors.removeValue(forKey: jobID)
            jobEvents.removeValue(forKey: jobID)
        }
        jobs.removeAll { clientStressTestJobIDs.contains($0.id) }
        clientStressTestJobIDs.removeAll()
    }

    private func average(_ values: [Double]) -> Double {
        guard !values.isEmpty else {
            return 0
        }
        return values.reduce(0, +) / Double(values.count)
    }

    private static func clientStressTimestamp(_ date: Date = Date()) -> String {
        ISO8601DateFormatter().string(from: date)
    }

    private static func clientStressRunStamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        return formatter.string(from: Date())
    }

    private func connectRuntime(_ url: URL) {
        runtimeStatus = .online(url)
        api = PaperCopilotAPI(baseURL: url)
        jobError = nil
        Task {
            await loadJobs()
        }
    }

    private func disconnectRuntime() {
        for task in observationTasks.values {
            task.cancel()
        }
        observationTasks.removeAll()
        for jobID in Array(pendingJobEvents.keys) {
            flushPendingEvents(for: jobID)
        }
        api = nil
    }

    private func loadJobs() async {
        guard let api else {
            return
        }
        do {
            let persistedJobs = try await api.listJobs()
            let localStressJobs = jobs.filter {
                clientStressTestJobIDs.contains($0.id)
            }
            jobs = persistedJobs + localStressJobs
            jobs.sort { $0.updatedAt > $1.updatedAt }
            if !hasInitializedConversationSelection {
                hasInitializedConversationSelection = true
                selectedConversationID = conversations.first?.id
            }
            for record in persistedJobs where record.status.isActive {
                observe(record.id)
            }
        } catch {
            jobError = error.localizedDescription
        }
    }

    private func observe(_ jobID: String) {
        guard observationTasks[jobID] == nil else {
            return
        }
        observationTasks[jobID] = Task { [weak self] in
            await self?.observeJob(jobID)
        }
    }

    private func observeJob(_ jobID: String) async {
        guard let api else {
            observationTasks[jobID] = nil
            return
        }
        do {
            let stream = try api.stream(
                jobID: jobID,
                after: eventCursors[jobID, default: 0]
            )
            for try await payload in stream {
                apply(payload)
            }
        } catch is CancellationError {
            observationTasks[jobID] = nil
            return
        } catch {
            if Task.isCancelled {
                observationTasks[jobID] = nil
                return
            }
        }

        if jobs.first(where: { $0.id == jobID })?.status.isActive == true {
            await pollJob(jobID, api: api)
        }
        observationTasks[jobID] = nil
    }

    private func pollJob(_ jobID: String, api: PaperCopilotAPI) async {
        while !Task.isCancelled {
            do {
                let eventsResponse = try await api.events(
                    for: jobID,
                    after: eventCursors[jobID, default: 0]
                )
                applyEvents(
                    eventsResponse.events,
                    nextAfter: eventsResponse.nextAfter,
                    jobID: jobID
                )
                let record = try await api.job(jobID)
                upsert(record)
                if !record.status.isActive {
                    return
                }
                try await Task.sleep(nanoseconds: 1_000_000_000)
            } catch is CancellationError {
                return
            } catch {
                jobError = error.localizedDescription
                return
            }
        }
    }

    private func apply(_ payload: ChatJobStreamPayload) {
        applyEvents(
            payload.events,
            nextAfter: payload.nextAfter,
            jobID: payload.record.id
        )
        upsert(payload.record)
    }

    private func applyEvents(
        _ events: [ChatJobEvent],
        nextAfter: Int,
        jobID: String
    ) {
        let cursor = eventCursors[jobID, default: 0]
        let freshEvents = events.filter { $0.seq > cursor }
        if !freshEvents.isEmpty {
            pendingJobEvents[jobID, default: []].append(
                contentsOf: freshEvents
            )
            if freshEvents.contains(where: { $0.activityPhase != "delta" }) {
                flushPendingEvents(for: jobID)
            } else {
                scheduleEventFlush(for: jobID)
            }
        }
        eventCursors[jobID] = max(cursor, nextAfter)
    }

    private func scheduleEventFlush(for jobID: String) {
        guard eventFlushTasks[jobID] == nil else {
            return
        }
        eventFlushTasks[jobID] = Task { [weak self] in
            do {
                try await Task.sleep(
                    nanoseconds: Self.eventPresentationIntervalNanoseconds
                )
            } catch {
                return
            }
            self?.flushPendingEvents(for: jobID)
        }
    }

    private func flushPendingEvents(for jobID: String) {
        eventFlushTasks[jobID]?.cancel()
        eventFlushTasks.removeValue(forKey: jobID)
        guard
            let events = pendingJobEvents.removeValue(forKey: jobID),
            !events.isEmpty
        else {
            return
        }
        jobEvents[jobID, default: []].append(contentsOf: events)
    }

    private func upsert(_ record: ChatJobRecord) {
        if let index = jobs.firstIndex(where: { $0.id == record.id }) {
            let current = jobs[index]
            guard current.hasMaterialPresentationChange(comparedWith: record) else {
                return
            }
            jobs[index] = record
        } else {
            jobs.append(record)
        }
        jobs.sort { $0.updatedAt > $1.updatedAt }
    }
}

private extension ChatJobRecord {
    func hasMaterialPresentationChange(
        comparedWith other: ChatJobRecord
    ) -> Bool {
        status != other.status
            || createdAt != other.createdAt
            || spec != other.spec
            || attempts != other.attempts
            || result != other.result
            || error != other.error
            || pendingApproval != other.pendingApproval
            || contextUsage != other.contextUsage
    }
}
