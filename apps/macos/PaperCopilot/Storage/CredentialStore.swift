import Foundation

struct CredentialStore {
    enum Account: String, Equatable {
        case llmAPIKey = "LLM_API_KEY"
        case dashscopeAPIKey = "DASHSCOPE_API_KEY"
    }

    private struct StoredCredentials: Codable {
        var accounts: [String: String] = [:]
        var modelAPIKeys: [String: String] = [:]

        enum CodingKeys: String, CodingKey {
            case accounts
            case modelAPIKeys = "model_api_keys"
        }
    }

    private enum CredentialStoreError: LocalizedError {
        case applicationSupportUnavailable

        var errorDescription: String? {
            "无法访问用户的 Application Support 目录。"
        }
    }

    func read(_ account: Account) throws -> String {
        try load().accounts[account.rawValue] ?? ""
    }

    func readModelKey(_ modelID: UUID) throws -> String {
        try load().modelAPIKeys[modelID.uuidString] ?? ""
    }

    func saveModelKey(_ value: String, modelID: UUID) throws {
        var credentials = try load()
        if value.isEmpty {
            credentials.modelAPIKeys.removeValue(forKey: modelID.uuidString)
        } else {
            credentials.modelAPIKeys[modelID.uuidString] = value
        }
        try save(credentials)
    }

    func deleteModelKey(_ modelID: UUID) throws {
        var credentials = try load()
        credentials.modelAPIKeys.removeValue(forKey: modelID.uuidString)
        try save(credentials)
    }

    func save(_ value: String, for account: Account) throws {
        var credentials = try load()
        if value.isEmpty {
            credentials.accounts.removeValue(forKey: account.rawValue)
        } else {
            credentials.accounts[account.rawValue] = value
        }
        try save(credentials)
    }

    private func load() throws -> StoredCredentials {
        let url = try authFileURL()
        guard FileManager.default.fileExists(atPath: url.path) else {
            return StoredCredentials()
        }
        return try JSONDecoder().decode(
            StoredCredentials.self,
            from: Data(contentsOf: url)
        )
    }

    private func save(_ credentials: StoredCredentials) throws {
        let url = try authFileURL()
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let encoded = try JSONEncoder().encode(credentials)
        try encoded.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    private func authFileURL() throws -> URL {
        guard
            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first
        else {
            throw CredentialStoreError.applicationSupportUnavailable
        }
        return applicationSupport
            .appendingPathComponent("PaperCopilot", isDirectory: true)
            .appendingPathComponent("auth.json")
    }
}
