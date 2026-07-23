import Foundation

final class PaperCopilotAPI {
    private struct ErrorEnvelope: Decodable {
        struct APIError: Decodable {
            let message: String
        }

        let error: APIError
    }

    private enum ClientError: LocalizedError {
        case invalidURL
        case invalidResponse
        case requestFailed(Int, String)

        var errorDescription: String? {
            switch self {
            case .invalidURL:
                return "无法构造本地 Runtime URL。"
            case .invalidResponse:
                return "本地 Runtime 返回了无效响应。"
            case .requestFailed(let status, let message):
                return "本地 Runtime 请求失败（\(status)）：\(message)"
            }
        }
    }

    private let baseURL: URL
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func listJobs() async throws -> [ChatJobRecord] {
        let request = URLRequest(url: try url(path: ["jobs"]))
        let response: ChatJobsResponse = try await send(request)
        return response.jobs
    }

    func job(_ jobID: String) async throws -> ChatJobRecord {
        let request = URLRequest(url: try url(path: ["jobs", jobID]))
        return try await send(request)
    }

    func createJob(
        message: String,
        pdfDir: String,
        conversationID: String?
    ) async throws -> ChatJobRecord {
        var request = URLRequest(url: try url(path: ["jobs"]))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(
            ChatJobCreateRequest(
                message: message,
                pdfDir: pdfDir,
                conversationID: conversationID
            )
        )
        return try await send(request)
    }

    func interrupt(_ jobID: String) async throws -> ChatJobRecord {
        var request = URLRequest(
            url: try url(path: ["jobs", jobID, "interrupt"])
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        return try await send(request)
    }

    func events(
        for jobID: String,
        after: Int
    ) async throws -> ChatJobEventsResponse {
        let request = URLRequest(
            url: try url(
                path: ["jobs", jobID, "events"],
                queryItems: [
                    URLQueryItem(name: "after", value: String(after)),
                    URLQueryItem(name: "limit", value: "1000"),
                ]
            )
        )
        return try await send(request)
    }

    func diagnostics(
        for jobID: String,
        attempt: Int
    ) async throws -> RolloutDiagnostics {
        let request = URLRequest(
            url: try url(
                path: ["jobs", jobID, "diagnostics"],
                queryItems: [
                    URLQueryItem(name: "attempt", value: String(attempt))
                ]
            )
        )
        return try await send(request)
    }

    func stream(
        jobID: String,
        after: Int
    ) throws -> AsyncThrowingStream<ChatJobStreamPayload, Error> {
        let request = URLRequest(
            url: try url(
                path: ["jobs", jobID, "stream"],
                queryItems: [URLQueryItem(name: "after", value: String(after))]
            )
        )
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: request)
                    try validate(response)
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else {
                            continue
                        }
                        let json = line.dropFirst(5).trimmingCharacters(
                            in: .whitespaces
                        )
                        let payload = try decoder.decode(
                            ChatJobStreamPayload.self,
                            from: Data(json.utf8)
                        )
                        continuation.yield(payload)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    private func send<Response: Decodable>(
        _ request: URLRequest
    ) async throws -> Response {
        let (body, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw ClientError.invalidResponse
        }
        guard 200..<300 ~= httpResponse.statusCode else {
            let message = (
                try? decoder.decode(ErrorEnvelope.self, from: body)
            )?.error.message ?? HTTPURLResponse.localizedString(
                forStatusCode: httpResponse.statusCode
            )
            throw ClientError.requestFailed(httpResponse.statusCode, message)
        }
        return try decoder.decode(Response.self, from: body)
    }

    private func validate(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw ClientError.invalidResponse
        }
        guard 200..<300 ~= httpResponse.statusCode else {
            throw ClientError.requestFailed(
                httpResponse.statusCode,
                HTTPURLResponse.localizedString(
                    forStatusCode: httpResponse.statusCode
                )
            )
        }
    }

    private func url(
        path: [String],
        queryItems: [URLQueryItem] = []
    ) throws -> URL {
        var endpoint = baseURL
        for component in path {
            endpoint.appendPathComponent(component)
        }
        guard var components = URLComponents(
            url: endpoint,
            resolvingAgainstBaseURL: false
        ) else {
            throw ClientError.invalidURL
        }
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        guard let resolvedURL = components.url else {
            throw ClientError.invalidURL
        }
        return resolvedURL
    }
}
