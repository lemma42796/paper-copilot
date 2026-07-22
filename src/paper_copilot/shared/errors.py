"""Project-wide exception hierarchy.

Every exception raised from `paper_copilot.*` modules should inherit from
`PaperCopilotError` so top-level API and agent-loop boundaries can convert
them to user-facing messages without catching unrelated runtime errors.
"""


class PaperCopilotError(Exception):
    pass


class AgentError(PaperCopilotError):
    pass


class ToolLoopError(AgentError):
    pass


class ToolTimeoutError(AgentError):
    pass


class SchemaValidationError(PaperCopilotError):
    pass


class RetrievalError(PaperCopilotError):
    pass


class KnowledgeError(PaperCopilotError):
    pass


class SessionError(PaperCopilotError):
    pass


class PdfError(PaperCopilotError):
    pass


class EvalError(PaperCopilotError):
    pass


class ApiError(PaperCopilotError):
    pass


class JobError(PaperCopilotError):
    pass


class RolloutTimeoutError(JobError):
    pass


class TraceIntegrityError(PaperCopilotError):
    pass
