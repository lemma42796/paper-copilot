"""Project-wide exception hierarchy.

Every exception raised from `paper_copilot.*` modules should inherit from
`PaperCopilotError` so top-level entry points (CLI, agent loop) can convert
them to user-facing messages without catching unrelated runtime errors.
"""


class PaperCopilotError(Exception):
    pass


class AgentError(PaperCopilotError):
    pass


class SchemaValidationError(PaperCopilotError):
    pass


class RetrievalError(PaperCopilotError):
    pass


class KnowledgeError(PaperCopilotError):
    pass


class SessionError(PaperCopilotError):
    pass
