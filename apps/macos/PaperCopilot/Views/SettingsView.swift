import Foundation
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var appModel: AppModel

    @State private var editorContext: ModelEditorContext?
    @State private var pendingDeletion: ModelConfiguration?
    @State private var errorMessage: String?
    @State private var selectedStressPreset: ClientStressTestPreset =
        .regression3278

    var body: some View {
        Form {
            Section("论文目录") {
                LabeledContent("当前目录") {
                    Text(appModel.libraryURL?.path ?? "尚未选择")
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.middle)
                }
                Button("选择论文目录…") {
                    appModel.chooseLibrary()
                }
            }

            Section("已添加模型") {
                if appModel.modelConfigurations.isEmpty {
                    Text("尚未添加模型。")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(appModel.modelConfigurations) { configuration in
                        modelRow(configuration)
                    }
                }

                Button {
                    editorContext = .new()
                } label: {
                    Label("添加模型", systemImage: "plus")
                }
                .disabled(appModel.hasActiveJobs || appModel.isSubmitting)

                Text("只有已启用、配置完整且 API Key 非空的模型才会出现在聊天区菜单。")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if appModel.hasActiveJobs {
                    Text("任务运行期间不能修改模型配置。")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            Section("本地公式识别") {
                formulaOCRStatus

                switch appModel.formulaOCRStatus {
                case .notInstalled, .failed(_):
                    Button("下载本地公式 OCR…") {
                        appModel.downloadFormulaOCR()
                    }
                    .disabled(appModel.hasActiveJobs || appModel.isSubmitting)
                case .downloading:
                    ProgressView()
                        .controlSize(.small)
                case .installed(_):
                    Button("检查并更新本地公式 OCR…") {
                        appModel.downloadFormulaOCR()
                    }
                    .disabled(appModel.hasActiveJobs || appModel.isSubmitting)
                }

                Text(
                    "仅在点击下载后校验并复用本机已有组件；缺失时才获取 PaddlePaddle、PaddleOCR、运行依赖和 PP-FormulaNet_plus-M 权重。选择或指向模型不会联网。"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }

            Section("客户端压测") {
                Picker("测试预设", selection: $selectedStressPreset) {
                    ForEach(ClientStressTestPreset.allCases) { preset in
                        Text(preset.displayName).tag(preset)
                    }
                }
                .disabled(appModel.clientStressTestStatus.isRunning)

                Text(selectedStressPreset.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                LabeledContent(
                    "状态",
                    value: stressStatusTitle
                )

                if appModel.clientStressTestStatus.isRunning {
                    ProgressView(
                        value: appModel.clientStressTestStatus.progress
                    )
                    Text(
                        "\(appModel.clientStressTestStatus.deliveredEvents.formatted()) / \(appModel.clientStressTestStatus.totalEvents.formatted()) 条事件"
                    )
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                }

                if
                    let cpu = appModel.clientStressTestStatus.currentCPUPercent
                {
                    LabeledContent(
                        "当前 CPU",
                        value: String(format: "%.1f%%", cpu)
                    )
                }

                if let bytes = appModel.clientStressTestStatus.residentBytes {
                    LabeledContent(
                        "当前内存",
                        value: ByteCountFormatter.string(
                            fromByteCount: Int64(bytes),
                            countStyle: .memory
                        )
                    )
                }

                Text(appModel.clientStressTestStatus.message)
                    .font(.caption)
                    .foregroundStyle(stressStatusColor)
                    .fixedSize(horizontal: false, vertical: true)

                if
                    let outputPath = appModel.clientStressTestStatus.outputPath
                {
                    LabeledContent("结果目录") {
                        Text(outputPath)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                    }
                }

                if appModel.clientStressTestStatus.isRunning {
                    Button("停止测试", role: .destructive) {
                        appModel.stopClientStressTest()
                    }
                } else {
                    Button("开始测试") {
                        appModel.startClientStressTest(selectedStressPreset)
                    }
                    .disabled(appModel.hasActiveJobs || appModel.isSubmitting)
                }

                Text(
                    "全部事件、回答和公式都由客户端本地生成；不调用模型、不连接 Runtime、不读取 API Key，模型费用始终为 0。"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }

            Section("本地与云端数据边界") {
                Text(
                    "PDF、索引和 session 保存在本机。为了完成分析，本地检索选出的必要文本片段可能发送给你配置的云端模型。Paper Copilot 不提供论文上传接口或云端论文库。"
                )
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }

            if let errorMessage {
                Section {
                    Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 640, height: 660)
        .sheet(item: $editorContext) { context in
            ModelEditorView(context: context) { configuration, apiKey in
                try appModel.saveModelConfiguration(
                    configuration,
                    apiKey: apiKey
                )
                errorMessage = nil
            }
        }
        .alert(item: $pendingDeletion) { configuration in
            Alert(
                title: Text("删除“\(configuration.displayName)”？"),
                message: Text("模型配置及其本地 API Key 将被删除。"),
                primaryButton: .destructive(Text("删除")) {
                    delete(configuration)
                },
                secondaryButton: .cancel()
            )
        }
    }

    private var stressStatusTitle: String {
        switch appModel.clientStressTestStatus.phase {
        case .idle:
            return "未运行"
        case .preparing:
            return "准备中"
        case .replaying:
            return "事件回放中"
        case .coolingDown:
            return "观察回落中"
        case .completed:
            return "已完成"
        case .cancelled:
            return "已停止"
        case .failed:
            return "失败"
        }
    }

    private var stressStatusColor: Color {
        switch appModel.clientStressTestStatus.phase {
        case .failed:
            return .red
        case .cancelled:
            return .orange
        case .completed:
            return .green
        default:
            return .secondary
        }
    }

    @ViewBuilder
    private var formulaOCRStatus: some View {
        switch appModel.formulaOCRStatus {
        case .notInstalled:
            LabeledContent("状态", value: "未下载")
        case .downloading:
            LabeledContent("状态", value: "正在复用或下载并校验…")
        case .installed(let version):
            LabeledContent("状态", value: "已安装 · \(version)")
        case .failed(let message):
            VStack(alignment: .leading, spacing: 4) {
                LabeledContent("状态", value: "下载失败")
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private func modelRow(
        _ configuration: ModelConfiguration
    ) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(configuration.displayName)
                    .font(.body.weight(.medium))
                Text("\(configuration.providerName) · \(configuration.modelID)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if let thinkingProtocol = configuration.effectiveThinkingProtocol {
                    let effort = configuration.effectiveReasoningEffort
                    Text(thinkingSummary(
                        configuration: configuration,
                        protocolType: thinkingProtocol,
                        effort: effort
                    ))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("缺少 Thinking 协议")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
                if
                    configuration.isEnabled,
                    !appModel.availableModels.contains(
                        where: { $0.id == configuration.id }
                    )
                {
                    Text("缺少 API Key")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            Spacer()

            Toggle(
                "启用",
                isOn: Binding(
                    get: { configuration.isEnabled },
                    set: { enabled in
                        setEnabled(configuration, enabled: enabled)
                    }
                )
            )
            .toggleStyle(.switch)
            .labelsHidden()
            .disabled(appModel.hasActiveJobs || appModel.isSubmitting)

            Button {
                edit(configuration)
            } label: {
                Image(systemName: "pencil")
            }
            .buttonStyle(.borderless)
            .help("编辑模型")
            .disabled(appModel.hasActiveJobs || appModel.isSubmitting)

            Button(role: .destructive) {
                pendingDeletion = configuration
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .help("删除模型")
            .disabled(appModel.hasActiveJobs || appModel.isSubmitting)
        }
        .padding(.vertical, 4)
    }

    private func thinkingSummary(
        configuration: ModelConfiguration,
        protocolType: ModelThinkingProtocol,
        effort: ReasoningEffort
    ) -> String {
        let detail = configuration.reasoningDetail(for: effort)
        return [
            "Thinking",
            protocolType.displayName,
            "\(configuration.reasoningControlTitle) \(effort.displayName)",
            detail,
        ]
        .compactMap { $0 }
        .joined(separator: " · ")
    }

    private func edit(_ configuration: ModelConfiguration) {
        do {
            editorContext = ModelEditorContext(
                configuration: configuration,
                apiKey: try appModel.modelAPIKey(for: configuration)
            )
            errorMessage = nil
        } catch {
            errorMessage = "无法读取模型 API Key：\(error.localizedDescription)"
        }
    }

    private func setEnabled(
        _ configuration: ModelConfiguration,
        enabled: Bool
    ) {
        do {
            try appModel.setModelConfiguration(
                configuration,
                enabled: enabled
            )
            errorMessage = nil
        } catch {
            errorMessage = "无法更新模型：\(error.localizedDescription)"
        }
    }

    private func delete(_ configuration: ModelConfiguration) {
        do {
            try appModel.deleteModelConfiguration(configuration)
            errorMessage = nil
        } catch {
            errorMessage = "无法删除模型：\(error.localizedDescription)"
        }
    }
}

private struct ModelEditorContext: Identifiable {
    let configuration: ModelConfiguration
    let apiKey: String

    var id: UUID {
        configuration.id
    }

    static func new() -> ModelEditorContext {
        ModelEditorContext(
            configuration: ModelConfiguration(
                id: UUID(),
                displayName: "",
                providerName: "",
                modelID: "",
                baseURL: "",
                inputPricePerMillion: 0,
                cacheCreationPricePerMillion: 0,
                cacheHitPricePerMillion: 0,
                outputPricePerMillion: 0,
                thinkingProtocol: nil,
                reasoningEffort: .high,
                inputModalities: [.text, .image],
                isEnabled: true
            ),
            apiKey: ""
        )
    }
}

private struct ModelEditorView: View {
    @Environment(\.dismiss) private var dismiss

    @State private var configuration: ModelConfiguration
    @State private var apiKey: String
    @State private var errorMessage: String?

    let onSave: (ModelConfiguration, String) throws -> Void

    init(
        context: ModelEditorContext,
        onSave: @escaping (ModelConfiguration, String) throws -> Void
    ) {
        _configuration = State(initialValue: context.configuration)
        _apiKey = State(initialValue: context.apiKey)
        self.onSave = onSave
    }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("模型信息") {
                    TextField("显示名称", text: $configuration.displayName)
                    TextField("厂商名称", text: $configuration.providerName)
                    TextField("Model ID", text: $configuration.modelID)
                    TextField("API Base URL", text: $configuration.baseURL)
                    if configuration.baseURL.contains("{WorkspaceId}") {
                        Text("请将 {WorkspaceId} 替换为阿里云百炼业务空间 ID")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    SecureField("API Key", text: $apiKey)
                    LabeledContent("Thinking 协议") {
                        Text(
                            configuration.effectiveThinkingProtocol?
                                .displayName
                                ?? "根据 Model ID 和 Base URL 自动识别"
                        )
                        .foregroundStyle(
                            configuration.effectiveThinkingProtocol == nil
                                ? .secondary
                                : .primary
                        )
                    }
                    Picker(
                        configuration.reasoningControlTitle,
                        selection: reasoningEffortBinding
                    ) {
                        ForEach(configuration.availableReasoningEfforts) { effort in
                            Text(reasoningOptionTitle(effort))
                            .tag(effort)
                        }
                    }
                    Toggle(
                        "支持图像输入",
                        isOn: supportsImageInputBinding
                    )
                    Toggle("启用此模型", isOn: $configuration.isEnabled)

                    Button("填入 Qwen 3.6 Flash 预设") {
                        applyQwenPreset()
                    }
                }

                Section("价格（元 / 百万 Token）") {
                    priceField(
                        "输入",
                        value: $configuration.inputPricePerMillion
                    )
                    priceField(
                        "缓存创建",
                        value: $configuration.cacheCreationPricePerMillion
                    )
                    priceField(
                        "缓存命中",
                        value: $configuration.cacheHitPricePerMillion
                    )
                    priceField(
                        "输出",
                        value: $configuration.outputPricePerMillion
                    )
                }

                if let errorMessage {
                    Section {
                        Label(
                            errorMessage,
                            systemImage: "exclamationmark.triangle.fill"
                        )
                        .foregroundStyle(.red)
                    }
                }
            }
            .formStyle(.grouped)

            Divider()

            HStack {
                Spacer()
                Button("取消") {
                    dismiss()
                }
                Button("保存") {
                    save()
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canSave)
            }
            .padding()
        }
        .frame(width: 560, height: 590)
    }

    private var canSave: Bool {
        configuration.hasCompleteMetadata
            && !apiKey.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).isEmpty
    }

    private var reasoningEffortBinding: Binding<ReasoningEffort> {
        Binding(
            get: { configuration.effectiveReasoningEffort },
            set: { configuration.reasoningEffort = $0 }
        )
    }

    private var supportsImageInputBinding: Binding<Bool> {
        Binding(
            get: { configuration.supportsImageInput },
            set: { supportsImageInput in
                configuration.inputModalities = supportsImageInput
                    ? [.text, .image]
                    : [.text]
            }
        )
    }

    private func reasoningOptionTitle(_ effort: ReasoningEffort) -> String {
        guard let detail = configuration.reasoningDetail(for: effort) else {
            return effort.displayName
        }
        return "\(effort.displayName) · \(detail)"
    }

    private func priceField(
        _ label: String,
        value: Binding<Double>
    ) -> some View {
        LabeledContent(label) {
            TextField("", value: value, format: .number)
                .multilineTextAlignment(.trailing)
                .frame(width: 140)
        }
    }

    private func applyQwenPreset() {
        let preset = ModelConfiguration.qwen36Flash(id: configuration.id)
        configuration.displayName = preset.displayName
        configuration.providerName = preset.providerName
        configuration.modelID = preset.modelID
        configuration.baseURL = preset.baseURL
        configuration.inputPricePerMillion = preset.inputPricePerMillion
        configuration.cacheCreationPricePerMillion =
            preset.cacheCreationPricePerMillion
        configuration.cacheHitPricePerMillion =
            preset.cacheHitPricePerMillion
        configuration.outputPricePerMillion = preset.outputPricePerMillion
        configuration.thinkingProtocol = preset.thinkingProtocol
        configuration.reasoningEffort = preset.reasoningEffort
        configuration.inputModalities = preset.inputModalities
    }

    private func save() {
        do {
            try onSave(configuration, apiKey)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
