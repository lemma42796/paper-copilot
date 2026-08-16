import Foundation

enum AppLanguage: String, CaseIterable, Identifiable {
    case simplifiedChinese = "zh-Hans"
    case english = "en"

    var id: String {
        rawValue
    }

    var displayName: String {
        switch self {
        case .simplifiedChinese:
            return "中文"
        case .english:
            return "English"
        }
    }

    var locale: Locale {
        Locale(identifier: rawValue)
    }
}

func appLocalized(_ key: String) -> String {
    guard AppLanguage.current == .english else {
        return key
    }
    guard
        let path = Bundle.main.path(forResource: "en", ofType: "lproj"),
        let bundle = Bundle(path: path)
    else {
        return key
    }
    return bundle.localizedString(forKey: key, value: key, table: nil)
}

extension AppLanguage {
    private static let defaultsKey = "appLanguage"

    static var current: AppLanguage {
        AppLanguage(
            rawValue: UserDefaults.standard.string(forKey: defaultsKey) ?? ""
        ) ?? .simplifiedChinese
    }

    static func save(_ language: AppLanguage) {
        UserDefaults.standard.set(language.rawValue, forKey: defaultsKey)
    }
}
