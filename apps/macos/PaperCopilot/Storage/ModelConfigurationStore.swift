import Foundation

struct ModelConfigurationStore {
    private let defaults = UserDefaults.standard
    private let configurationsKey = "modelConfigurations"
    private let selectedConfigurationKey = "selectedModelConfigurationID"

    func load() throws -> [ModelConfiguration] {
        guard let encoded = defaults.data(forKey: configurationsKey) else {
            return []
        }
        return try JSONDecoder().decode(
            [ModelConfiguration].self,
            from: encoded
        )
    }

    func save(_ configurations: [ModelConfiguration]) throws {
        defaults.set(
            try JSONEncoder().encode(configurations),
            forKey: configurationsKey
        )
    }

    func selectedID() -> UUID? {
        defaults.string(forKey: selectedConfigurationKey)
            .flatMap(UUID.init(uuidString:))
    }

    func saveSelectedID(_ id: UUID?) {
        defaults.set(id?.uuidString, forKey: selectedConfigurationKey)
    }
}
