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
    private struct RemoteArtifact: Decodable {
        let archiveURL: URL
        let archiveSHA256: String
        let archiveBytes: Int64
        let installedBytes: Int64
        let treeSHA256: String
        let rootDirectory: String

        enum CodingKeys: String, CodingKey {
            case archiveURL = "archive_url"
            case archiveSHA256 = "archive_sha256"
            case archiveBytes = "archive_bytes"
            case installedBytes = "installed_bytes"
            case treeSHA256 = "tree_sha256"
            case rootDirectory = "root_directory"
        }
    }

    private struct RemoteManifest: Decodable {
        let schemaVersion: Int
        let component: String
        let version: String
        let runtime: RemoteArtifact
        let model: RemoteArtifact
        let helperRelativePath: String
        let modelRelativePath: String

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case component
            case version
            case runtime
            case model
            case helperRelativePath = "helper_relative_path"
            case modelRelativePath = "model_relative_path"
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

    private static let componentSchemaVersion = 2
    private static let helperRootDirectory = "FormulaOCRHelper"
    private static let modelRootDirectory = "PP-FormulaNet_plus-S"
    private static let helperRelativePath = "FormulaOCRHelper/FormulaOCRHelper"
    private static let modelRelativePath =
        "FormulaOCRHelper/models/PP-FormulaNet_plus-S"
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
            active.schemaVersion == Self.componentSchemaVersion,
            let helperURL = validatedFileURL(
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
            try await install(manifest: manifest)
            await statusChanged(.installed(version: manifest.version))
        } catch {
            await statusChanged(.failed(error.localizedDescription))
        }
    }

    private func validate(_ manifest: RemoteManifest) throws {
        guard
            manifest.schemaVersion == Self.componentSchemaVersion,
            manifest.component == "formula-ocr",
            !manifest.version.isEmpty,
            manifest.helperRelativePath == Self.helperRelativePath,
            manifest.modelRelativePath == Self.modelRelativePath,
            manifest.runtime.rootDirectory == Self.helperRootDirectory,
            manifest.model.rootDirectory == Self.modelRootDirectory
        else {
            throw InstallError.invalidManifest
        }
        try validate(manifest.runtime)
        try validate(manifest.model)
    }

    private func validate(_ artifact: RemoteArtifact) throws {
        guard
            artifact.archiveURL.scheme == "https",
            Self.isSHA256(artifact.archiveSHA256),
            Self.isSHA256(artifact.treeSHA256),
            artifact.archiveBytes > 0,
            artifact.installedBytes > 0,
            !artifact.rootDirectory.isEmpty,
            !artifact.rootDirectory.contains("/")
        else {
            throw InstallError.invalidManifest
        }
    }

    private func install(manifest: RemoteManifest) async throws {
        let root = try componentRoot()
        try fileManager.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        if try activateExistingVersion(manifest: manifest, root: root) {
            return
        }

        let runtimeSource = try await runtimeSource(manifest: manifest, root: root)
        let modelSource = try await modelSource(manifest: manifest, root: root)
        let stagingURL = root.appendingPathComponent(
            ".staging-\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: stagingURL,
            withIntermediateDirectories: false
        )
        defer { try? fileManager.removeItem(at: stagingURL) }

        let stagedRuntime = stagingURL.appendingPathComponent(
            Self.helperRootDirectory,
            isDirectory: true
        )
        try fileManager.copyItem(at: runtimeSource, to: stagedRuntime)
        let stagedModels = stagedRuntime.appendingPathComponent(
            "models",
            isDirectory: true
        )
        if fileManager.fileExists(atPath: stagedModels.path) {
            try fileManager.removeItem(at: stagedModels)
        }
        try fileManager.createDirectory(
            at: stagedModels,
            withIntermediateDirectories: true
        )
        try fileManager.copyItem(
            at: modelSource,
            to: stagedModels.appendingPathComponent(
                Self.modelRootDirectory,
                isDirectory: true
            )
        )
        try validateInstalledVersion(stagingURL, manifest: manifest)

        let versionsURL = root.appendingPathComponent("versions", isDirectory: true)
        try fileManager.createDirectory(
            at: versionsURL,
            withIntermediateDirectories: true
        )
        let versionURL = versionsURL.appendingPathComponent(
            manifest.version,
            isDirectory: true
        )
        if fileManager.fileExists(atPath: versionURL.path) {
            try fileManager.removeItem(at: versionURL)
        }
        try fileManager.moveItem(at: stagingURL, to: versionURL)
        try writeActiveManifest(manifest, root: root)
    }

    private func activateExistingVersion(
        manifest: RemoteManifest,
        root: URL
    ) throws -> Bool {
        let versionURL = root
            .appendingPathComponent("versions", isDirectory: true)
            .appendingPathComponent(manifest.version, isDirectory: true)
        guard fileManager.fileExists(atPath: versionURL.path) else {
            return false
        }
        do {
            try validateInstalledVersion(versionURL, manifest: manifest)
            try writeActiveManifest(manifest, root: root)
            return true
        } catch {
            return false
        }
    }

    private func runtimeSource(
        manifest: RemoteManifest,
        root: URL
    ) async throws -> URL {
        if let installed = try reusableInstalledDirectory(
            root: root,
            relativePath: Self.helperRootDirectory,
            expectedTreeSHA256: manifest.runtime.treeSHA256,
            excludingTopLevelDirectory: "models",
            requireCodeSignature: true
        ) {
            return installed
        }
        return try await extractedArtifact(
            manifest.runtime,
            kind: "runtime",
            root: root,
            excludingTopLevelDirectory: nil,
            requireCodeSignature: true
        )
    }

    private func modelSource(
        manifest: RemoteManifest,
        root: URL
    ) async throws -> URL {
        if let installed = try reusableInstalledDirectory(
            root: root,
            relativePath: Self.modelRelativePath,
            expectedTreeSHA256: manifest.model.treeSHA256,
            excludingTopLevelDirectory: nil,
            requireCodeSignature: false
        ) {
            return installed
        }
        if let localPaddleXModel = localPaddleXModel(),
           try Self.treeSHA256(of: localPaddleXModel)
            == manifest.model.treeSHA256 {
            return localPaddleXModel
        }
        return try await extractedArtifact(
            manifest.model,
            kind: "model",
            root: root,
            excludingTopLevelDirectory: nil,
            requireCodeSignature: false
        )
    }

    private func reusableInstalledDirectory(
        root: URL,
        relativePath: String,
        expectedTreeSHA256: String,
        excludingTopLevelDirectory: String?,
        requireCodeSignature: Bool
    ) throws -> URL? {
        let versionsURL = root.appendingPathComponent("versions", isDirectory: true)
        guard let versions = try? fileManager.contentsOfDirectory(
            at: versionsURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return nil
        }
        for version in versions.sorted(by: { $0.path < $1.path }) {
            guard let candidate = validatedFileURL(
                relativePath: relativePath,
                root: version
            ), fileManager.fileExists(atPath: candidate.path) else {
                continue
            }
            guard try Self.treeSHA256(
                of: candidate,
                excludingTopLevelDirectory: excludingTopLevelDirectory
            ) == expectedTreeSHA256 else {
                continue
            }
            if requireCodeSignature {
                let helper = candidate.appendingPathComponent("FormulaOCRHelper")
                guard (try? Self.verifyCodeSignature(helper)) != nil else {
                    continue
                }
            }
            return candidate
        }
        return nil
    }

    private func extractedArtifact(
        _ artifact: RemoteArtifact,
        kind: String,
        root: URL,
        excludingTopLevelDirectory: String?,
        requireCodeSignature: Bool
    ) async throws -> URL {
        let artifactParent = root
            .appendingPathComponent("artifacts", isDirectory: true)
            .appendingPathComponent(kind, isDirectory: true)
            .appendingPathComponent(artifact.treeSHA256, isDirectory: true)
        let artifactURL = artifactParent.appendingPathComponent(
            artifact.rootDirectory,
            isDirectory: true
        )
        if fileManager.fileExists(atPath: artifactURL.path),
           try Self.treeSHA256(
               of: artifactURL,
               excludingTopLevelDirectory: excludingTopLevelDirectory
           ) == artifact.treeSHA256 {
            if requireCodeSignature {
                try Self.verifyCodeSignature(
                    artifactURL.appendingPathComponent("FormulaOCRHelper")
                )
            }
            return artifactURL
        }

        let archiveURL = try await cachedArchive(artifact, root: root)
        let stagingURL = root.appendingPathComponent(
            ".artifact-staging-\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.createDirectory(
            at: stagingURL,
            withIntermediateDirectories: false
        )
        defer { try? fileManager.removeItem(at: stagingURL) }
        try Self.run(
            executable: URL(fileURLWithPath: "/usr/bin/ditto"),
            arguments: ["-x", "-k", archiveURL.path, stagingURL.path]
        )
        let extractedURL = stagingURL.appendingPathComponent(
            artifact.rootDirectory,
            isDirectory: true
        )
        guard fileManager.fileExists(atPath: extractedURL.path),
              try Self.treeSHA256(
                  of: extractedURL,
                  excludingTopLevelDirectory: excludingTopLevelDirectory
              ) == artifact.treeSHA256 else {
            throw InstallError.invalidArchiveContents
        }
        if requireCodeSignature {
            try Self.verifyCodeSignature(
                extractedURL.appendingPathComponent("FormulaOCRHelper")
            )
        }
        if fileManager.fileExists(atPath: artifactParent.path) {
            try fileManager.removeItem(at: artifactParent)
        }
        try fileManager.createDirectory(
            at: artifactParent.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try fileManager.moveItem(at: stagingURL, to: artifactParent)
        return artifactURL
    }

    private func cachedArchive(
        _ artifact: RemoteArtifact,
        root: URL
    ) async throws -> URL {
        let downloadsURL = root.appendingPathComponent("downloads", isDirectory: true)
        try fileManager.createDirectory(
            at: downloadsURL,
            withIntermediateDirectories: true
        )
        let cachedURL = downloadsURL.appendingPathComponent(
            "\(artifact.archiveSHA256).zip"
        )
        if try archiveIsValid(cachedURL, artifact: artifact) {
            return cachedURL
        }
        if fileManager.fileExists(atPath: cachedURL.path) {
            try fileManager.removeItem(at: cachedURL)
        }
        let (temporaryURL, response) = try await URLSession.shared.download(
            from: artifact.archiveURL
        )
        try Self.requireSuccessfulHTTPResponse(response)
        guard try archiveIsValid(temporaryURL, artifact: artifact) else {
            throw InstallError.invalidArchiveHash
        }
        let partialURL = downloadsURL.appendingPathComponent(
            ".partial-\(UUID().uuidString)"
        )
        defer { try? fileManager.removeItem(at: partialURL) }
        try fileManager.copyItem(at: temporaryURL, to: partialURL)
        try fileManager.moveItem(at: partialURL, to: cachedURL)
        return cachedURL
    }

    private func archiveIsValid(
        _ url: URL,
        artifact: RemoteArtifact
    ) throws -> Bool {
        guard fileManager.fileExists(atPath: url.path) else {
            return false
        }
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard Int64(values.fileSize ?? -1) == artifact.archiveBytes else {
            return false
        }
        return try Self.sha256(of: url) == artifact.archiveSHA256
    }

    private func validateInstalledVersion(
        _ versionURL: URL,
        manifest: RemoteManifest
    ) throws {
        guard
            let helper = validatedFileURL(
                relativePath: manifest.helperRelativePath,
                root: versionURL
            ),
            let runtime = validatedFileURL(
                relativePath: Self.helperRootDirectory,
                root: versionURL
            ),
            let model = validatedFileURL(
                relativePath: manifest.modelRelativePath,
                root: versionURL
            ),
            fileManager.isExecutableFile(atPath: helper.path),
            fileManager.fileExists(atPath: model.path),
            try Self.treeSHA256(
                of: runtime,
                excludingTopLevelDirectory: "models"
            ) == manifest.runtime.treeSHA256,
            try Self.treeSHA256(of: model) == manifest.model.treeSHA256
        else {
            throw InstallError.invalidArchiveContents
        }
        try Self.verifyCodeSignature(helper)
    }

    private func writeActiveManifest(
        _ manifest: RemoteManifest,
        root: URL
    ) throws {
        let active = ActiveManifest(
            schemaVersion: Self.componentSchemaVersion,
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

    private func localPaddleXModel() -> URL? {
        let candidate = fileManager.homeDirectoryForCurrentUser
            .appendingPathComponent(".paddlex", isDirectory: true)
            .appendingPathComponent("official_models", isDirectory: true)
            .appendingPathComponent(Self.modelRootDirectory, isDirectory: true)
        return fileManager.fileExists(atPath: candidate.path) ? candidate : nil
    }

    private func validatedFileURL(
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
        let candidate = root
            .appendingPathComponent(relativePath)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        let rootPath = root
            .standardizedFileURL
            .resolvingSymlinksInPath()
            .path + "/"
        return candidate.path.hasPrefix(rootPath) ? candidate : nil
    }

    private static func verifyCodeSignature(_ helper: URL) throws {
        do {
            try run(
                executable: URL(fileURLWithPath: "/usr/bin/codesign"),
                arguments: ["--verify", "--deep", "--strict", helper.path]
            )
        } catch {
            throw InstallError.invalidCodeSignature
        }
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

    private static func isSHA256(_ value: String) -> Bool {
        value.range(
            of: "^[0-9a-f]{64}$",
            options: .regularExpression
        ) != nil
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

    private static func treeSHA256(
        of root: URL,
        excludingTopLevelDirectory excluded: String? = nil
    ) throws -> String {
        let keys: [URLResourceKey] = [
            .isDirectoryKey,
            .isRegularFileKey,
            .isSymbolicLinkKey,
        ]
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: keys,
            options: []
        ) else {
            throw InstallError.invalidArchiveContents
        }
        let rootPath = root.standardizedFileURL.path + "/"
        var entries: [(relativePath: String, url: URL, isSymbolicLink: Bool)] = []
        while let url = enumerator.nextObject() as? URL {
            let path = url.standardizedFileURL.path
            guard path.hasPrefix(rootPath) else {
                throw InstallError.invalidArchiveContents
            }
            let relativePath = String(path.dropFirst(rootPath.count))
            let values = try url.resourceValues(forKeys: Set(keys))
            if let excluded,
               relativePath == excluded || relativePath.hasPrefix("\(excluded)/") {
                if values.isDirectory == true {
                    enumerator.skipDescendants()
                }
                continue
            }
            if values.isSymbolicLink == true {
                entries.append((relativePath, url, true))
            } else if values.isRegularFile == true {
                entries.append((relativePath, url, false))
            } else if values.isDirectory != true {
                throw InstallError.invalidArchiveContents
            }
        }
        var hasher = SHA256()
        for entry in entries.sorted(by: { $0.relativePath < $1.relativePath }) {
            let record: String
            if entry.isSymbolicLink {
                let destination = try FileManager.default.destinationOfSymbolicLink(
                    atPath: entry.url.path
                )
                record = "L\0\(entry.relativePath)\0\(destination)\n"
            } else {
                record = "F\0\(entry.relativePath)\0\(try sha256(of: entry.url))\n"
            }
            guard let data = record.data(using: .utf8) else {
                throw InstallError.invalidArchiveContents
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
