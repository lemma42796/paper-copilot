import pytest

from paper_copilot.shared.errors import (
    AgentError,
    KnowledgeError,
    PaperCopilotError,
    RetrievalError,
    SchemaValidationError,
    SessionError,
)


def test_base_class_is_exception() -> None:
    assert issubclass(PaperCopilotError, Exception)


@pytest.mark.parametrize(
    "cls",
    [AgentError, SchemaValidationError, RetrievalError, KnowledgeError, SessionError],
)
def test_subclass_inheritance(cls: type[Exception]) -> None:
    assert issubclass(cls, PaperCopilotError)


def test_raise_catch_as_base() -> None:
    with pytest.raises(PaperCopilotError):
        raise AgentError("boom")


def test_raise_preserves_message() -> None:
    with pytest.raises(SchemaValidationError, match="bad output: foo"):
        raise SchemaValidationError("bad output: foo")
