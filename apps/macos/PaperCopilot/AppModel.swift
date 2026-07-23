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
                return "请先在设置中配置并启用一个模型。"
            case .missingProviderKey(let provider):
                return "缺少 \(provider) API Key。"
            case .invalidConfiguration:
                return "模型配置不完整或价格无效。"
            case .configurationLocked:
                return "任务运行期间不能修改模型配置。"
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
    @Published private(set) var isSubmitting = false
    @Published private(set) var modelConfigurations: [ModelConfiguration] = []
    @Published private(set) var availableModels: [ModelConfiguration] = []
    @Published private(set) var selectedModel: ModelConfiguration?
    @Published var selectedConversationID: String?

    private let bookmarkStore = LibraryBookmarkStore()
    private let keychain = KeychainStore()
    private let modelStore = ModelConfigurationStore()
    private let runtimeManager = RuntimeManager()
    private var api: PaperCopilotAPI?
    private var eventCursors: [String: Int] = [:]
    private var observationTasks: [String: Task<Void, Never>] = [:]

    init() {
        restoreLibrary()
        initializeModelRuntime()
    }

    private func initializeModelRuntime() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                let keychain = KeychainStore()
                let modelStore = ModelConfigurationStore()
                try Self.migrateLegacyModelConfiguration(
                    modelStore: modelStore
                )
                let snapshot = try Self.modelConfigurationSnapshot(
                    keychain: keychain,
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
            jobError = "任务运行期间不能切换模型。"
            return
        }
        selectedModel = model
        modelStore.saveSelectedID(model.id)
        restartRuntime()
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
            jobError = "任务运行期间不能切换思考设置。"
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
        try keychain.readModelKey(configuration.id)
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

        try keychain.saveModelKey(apiKey, modelID: configuration.id)
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
        try keychain.deleteModelKey(configuration.id)
        reloadModelConfigurations()
    }

    @discardableResult
    func submit(_ message: String, conversationID: String? = nil) -> Bool {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSubmitting else {
            return false
        }
        guard let api else {
            jobError = "本地 Runtime 尚未连接。"
            return false
        }
        guard let libraryURL else {
            jobError = "请先选择论文目录。"
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
                    conversationID: conversationID
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

    func interrupt(_ jobID: String) {
        guard let api else {
            jobError = "本地 Runtime 尚未连接。"
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

    func selectConversation(_ conversationID: String?) {
        selectedConversationID = conversationID
        guard
            let conversation = conversations.first(
                where: { $0.id == conversationID }
            )
        else {
            return
        }
        for job in conversation.jobs {
            loadEvents(for: job.id)
        }
    }

    func dismissJobError() {
        jobError = nil
    }

    func chooseLibrary() {
        let panel = NSOpenPanel()
        panel.title = "选择论文目录"
        panel.prompt = "选择"
        panel.message = "Paper Copilot 将读取此目录中的本地 PDF。"
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
        let providerKey = try keychain.readModelKey(selectedModel.id)
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
        ]
        let selectedHost = URL(string: selectedModel.baseURL)?.host ?? ""
        let dashscopeAPIKey = selectedHost.contains("dashscope.aliyuncs.com")
            ? providerKey
            : try keychain.read(.dashscopeAPIKey)
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
            let qwen = ModelConfiguration.qwen36Flash()
            try modelStore.save([qwen])
            modelStore.saveSelectedID(qwen.id)
        }
        defaults.set(true, forKey: migrationKey)
    }

    nonisolated private static func modelConfigurationSnapshot(
        keychain: KeychainStore,
        modelStore: ModelConfigurationStore
    ) throws -> ModelConfigurationSnapshot {
        let configurations = try modelStore.load()
        var available: [ModelConfiguration] = []
        for configuration in configurations
        where configuration.isEnabled && configuration.hasCompleteMetadata {
            let apiKey = try keychain.readModelKey(configuration.id)
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
                keychain: keychain,
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
        api = nil
    }

    private func loadJobs() async {
        guard let api else {
            return
        }
        do {
            jobs = try await api.listJobs()
            if selectedConversationID == nil {
                selectedConversationID = conversations.first?.id
            }
            for record in jobs where record.status.isActive {
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
            jobEvents[jobID, default: []].append(contentsOf: freshEvents)
        }
        eventCursors[jobID] = max(cursor, nextAfter)
    }

    private func upsert(_ record: ChatJobRecord) {
        jobs.removeAll { $0.id == record.id }
        jobs.append(record)
        jobs.sort { $0.updatedAt > $1.updatedAt }
    }
}
