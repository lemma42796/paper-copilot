import Foundation
import Security

struct KeychainStore {
    enum Account: String, Equatable {
        case llmAPIKey = "LLM_API_KEY"
        case dashscopeAPIKey = "DASHSCOPE_API_KEY"
    }

    private struct KeychainError: LocalizedError {
        let status: OSStatus

        var errorDescription: String? {
            SecCopyErrorMessageString(status, nil) as String?
        }
    }

    private let service = "local.paper-copilot"

    func read(_ account: Account) throws -> String {
        try read(account.rawValue)
    }

    func readModelKey(_ modelID: UUID) throws -> String {
        try read(modelAccount(modelID))
    }

    func saveModelKey(_ value: String, modelID: UUID) throws {
        try save(value, account: modelAccount(modelID))
    }

    func deleteModelKey(_ modelID: UUID) throws {
        try delete(modelAccount(modelID))
    }

    private func read(_ account: String) throws -> String {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound {
            return ""
        }
        guard status == errSecSuccess, let passwordData = item as? Data else {
            throw KeychainError(status: status)
        }
        return String(decoding: passwordData, as: UTF8.self)
    }

    func save(_ value: String, for account: Account) throws {
        try save(value, account: account.rawValue)
    }

    private func save(_ value: String, account: String) throws {
        if value.isEmpty {
            try delete(account)
            return
        }

        let passwordData = Data(value.utf8)
        let query = baseQuery(account)
        let attributes = [kSecValueData as String: passwordData]
        let updateStatus = SecItemUpdate(
            query as CFDictionary,
            attributes as CFDictionary
        )
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw KeychainError(status: updateStatus)
        }

        var newItem = query
        newItem[kSecValueData as String] = passwordData
        newItem[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlocked
        let addStatus = SecItemAdd(newItem as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw KeychainError(status: addStatus)
        }
    }

    private func delete(_ account: String) throws {
        let status = SecItemDelete(baseQuery(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError(status: status)
        }
    }

    private func baseQuery(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private func modelAccount(_ modelID: UUID) -> String {
        "MODEL_API_KEY.\(modelID.uuidString)"
    }
}
