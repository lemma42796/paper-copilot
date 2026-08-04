import CryptoKit
import Foundation

enum FormulaOCRInstallStatus: Equatable {
    case notInstalled
    case downloading
    case installed(version: String)
    case failed(String)

    var isInstalled: Bool {
        if case .installed = self {
            return true
        }
        return false
    }
}

final class FormulaOCRManager: @unchecked Sendable {
    private struct RemoteManifest: Decodable {
        let schemaVersion: Int
        let component: String
        let version: String
        let archiveURL: URL
        let archiveSHA256: String
        let archiveBytes: Int64
        let installedBytes: Int64
        let helperRelativePath: String

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case component
            case version
            case archiveURL = "archive_url"
            case archiveSHA256 = "archive_sha256"
            case archiveBytes = "archive_bytes"
            case installedBytes = "installed_bytes"
            case helperRelativePath = "helper_relative_path"
        }
    }

    private struct ActiveManifest: Codable {
        let schemaVersion: Int
        let version: String
        let helperRelativePath: String

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case version
            case helperRelativePath = "helper_relative_path"
        }
    }

    private enum InstallError: LocalizedError {
        case invalidManifest
        case invalidArchiveHash
        case invalidArchiveContents
        case invalidCodeSignature

        var errorDescription: String? {
            switch self {
            case .invalidManifest:
                return "公式 OCR 下载清单无效。"
            case .invalidArchiveHash:
                return "公式 OCR 下载文件校验失败。"
            case .invalidArchiveContents:
                return "公式 OCR 下载包内容不完整。"
            case .invalidCodeSignature:
                return "公式 OCR Helper 签名校验失败。"
            }
        }
    }

    private static let manifestURL = URL(
        string:
            "https://github.com/lemma42796/paper-copilot/releases/download/formula-ocr-v1/formula-ocr-macos-arm64-manifest.json"
    )!
    private let fileManager = FileManager.default
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    func localStatus() -> FormulaOCRInstallStatus {
        guard
            let root = try? componentRoot(),
            let data = try? Data(contentsOf: root.appendingPathComponent("active.json")),
            let active = try? decoder.decode(ActiveManifest.self, from: data),
            active.schemaVersion == 1,
            let helperURL = validatedHelperURL(
                relativePath: active.helperRelativePath,
                root: root
            ),
            fileManager.isExecutableFile(atPath: helperURL.path)
        else {
            return .notInstalled
        }
        return .installed(version: active.version)
    }

    func downloadAndInstall(
        statusChanged: @escaping @MainActor (FormulaOCRInstallStatus) -> Void
    ) async {
        await statusChanged(.downloading)
        do {
            let (manifestData, manifestResponse) = try await URLSession.shared.data(
                from: Self.manifestURL
            )
            try Self.requireSuccessfulHTTPResponse(manifestResponse)
            let manifest = try decoder.decode(RemoteManifest.self, from: manifestData)
            try validate(manifest)
            let (archiveURL, archiveResponse) = try await URLSession.shared.download(
                from: manifest.archiveURL
            )
            try Self.requireSuccessfulHTTPResponse(archiveResponse)
            let archiveValues = try archiveURL.resourceValues(
                forKeys: [.fileSizeKey]
            )
            guard Int64(archiveValues.fileSize ?? -1) == manifest.archiveBytes else {
                throw InstallError.invalidArchiveHash
            }
            guard try Self.sha256(of: archiveURL) == manifest.archiveSHA256 else {
                throw InstallError.invalidArchiveHash
            }
            try install(archiveURL: archiveURL, manifest: manifest)
            await statusChanged(.installed(version: manifest.version))
        } catch {
            await statusChanged(.failed(error.localizedDescription))
        }
    }

    private func validate(_ manifest: RemoteManifest) throws {
        guard
            manifest.schemaVersion == 1,
            manifest.component == "formula-ocr",
            !manifest.version.isEmpty,
            manifest.archiveURL.scheme == "https",
            manifest.archiveSHA256.range(
                of: "^[0-9a-f]{64}$",
                options: .regularExpression
            ) != nil,
            manifest.archiveBytes > 0,
            manifest.installedBytes > 0,
            manifest.helperRelativePath == "FormulaOCRHelper/FormulaOCRHelper"
        else {
            throw InstallError.invalidManifest
        }
    }

    private func install(
        archiveURL: URL,
        manifest: RemoteManifest
    ) throws {
        let root = try componentRoot()
        let versionsURL = root.appendingPathComponent("versions", isDirectory: true)
        try fileManager.createDirectory(
            at: versionsURL,
            withIntermediateDirectories: true
        )
        let stagingURL = root.appendingPathComponent(
            ".staging-\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: stagingURL,
            withIntermediateDirectories: false
        )
        defer {
            try? fileManager.removeItem(at: stagingURL)
        }
        try Self.run(
            executable: URL(fileURLWithPath: "/usr/bin/ditto"),
            arguments: ["-x", "-k", archiveURL.path, stagingURL.path]
        )
        guard
            let stagedHelper = validatedHelperURL(
                relativePath: manifest.helperRelativePath,
                root: stagingURL
            ),
            fileManager.isExecutableFile(atPath: stagedHelper.path)
        else {
            throw InstallError.invalidArchiveContents
        }
        do {
            try Self.run(
                executable: URL(fileURLWithPath: "/usr/bin/codesign"),
                arguments: ["--verify", "--deep", "--strict", stagedHelper.path]
            )
        } catch {
            throw InstallError.invalidCodeSignature
        }
        let versionURL = versionsURL.appendingPathComponent(
            manifest.version,
            isDirectory: true
        )
        if fileManager.fileExists(atPath: versionURL.path) {
            try fileManager.removeItem(at: versionURL)
        }
        try fileManager.moveItem(at: stagingURL, to: versionURL)
        let active = ActiveManifest(
            schemaVersion: 1,
            version: manifest.version,
            helperRelativePath:
                "versions/\(manifest.version)/\(manifest.helperRelativePath)"
        )
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let activeData = try encoder.encode(active)
        try activeData.write(
            to: root.appendingPathComponent("active.json"),
            options: .atomic
        )
    }

    private func componentRoot() throws -> URL {
        guard let applicationSupport = fileManager.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else {
            throw CocoaError(.fileNoSuchFile)
        }
        return applicationSupport
            .appendingPathComponent("Paper Copilot", isDirectory: true)
            .appendingPathComponent("optional-components", isDirectory: true)
            .appendingPathComponent("formula-ocr", isDirectory: true)
    }

    private func validatedHelperURL(
        relativePath: String,
        root: URL
    ) -> URL? {
        let components = NSString(string: relativePath).pathComponents
        guard
            !relativePath.hasPrefix("/"),
            !components.contains("..")
        else {
            return nil
        }
        let candidate = root.appendingPathComponent(relativePath).standardizedFileURL
        let rootPath = root.standardizedFileURL.path + "/"
        return candidate.path.hasPrefix(rootPath) ? candidate : nil
    }

    private static func requireSuccessfulHTTPResponse(
        _ response: URLResponse
    ) throws {
        guard
            let httpResponse = response as? HTTPURLResponse,
            200..<300 ~= httpResponse.statusCode
        else {
            throw URLError(.badServerResponse)
        }
    }

    private static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
            if data.isEmpty {
                break
            }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func run(executable: URL, arguments: [String]) throws {
        let process = Process()
        let standardError = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = Pipe()
        process.standardError = standardError
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let message = String(
                data: standardError.fileHandleForReading.readDataToEndOfFile(),
                encoding: .utf8
            ) ?? ""
            throw NSError(
                domain: "FormulaOCRManager",
                code: Int(process.terminationStatus),
                userInfo: [NSLocalizedDescriptionKey: message]
            )
        }
    }
}
