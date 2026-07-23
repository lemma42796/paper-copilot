import Foundation

@MainActor
final class LibraryBookmarkStore {
    private enum StoreError: LocalizedError {
        case bookmarkUnavailable

        var errorDescription: String? {
            switch self {
            case .bookmarkUnavailable:
                return "无法恢复论文目录授权，请重新选择目录。"
            }
        }
    }

    private let defaults: UserDefaults
    private let bookmarkKey = "paperLibraryBookmark"
    private var activeURL: URL?
    private var hasSecurityScopedAccess = false

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    deinit {
        if hasSecurityScopedAccess {
            activeURL?.stopAccessingSecurityScopedResource()
        }
    }

    func restore() throws -> URL? {
        guard let bookmark = defaults.data(forKey: bookmarkKey) else {
            return nil
        }
        var isStale = false
        let url = try URL(
            resolvingBookmarkData: bookmark,
            options: [.withSecurityScope],
            relativeTo: nil,
            bookmarkDataIsStale: &isStale
        )
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw StoreError.bookmarkUnavailable
        }
        if isStale {
            try saveBookmark(for: url)
        }
        activate(url)
        return url
    }

    func select(_ url: URL) throws {
        try saveBookmark(for: url)
        activate(url)
    }

    private func saveBookmark(for url: URL) throws {
        let bookmark = try url.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        defaults.set(bookmark, forKey: bookmarkKey)
    }

    private func activate(_ url: URL) {
        if hasSecurityScopedAccess {
            activeURL?.stopAccessingSecurityScopedResource()
        }
        activeURL = url
        hasSecurityScopedAccess = url.startAccessingSecurityScopedResource()
    }
}
