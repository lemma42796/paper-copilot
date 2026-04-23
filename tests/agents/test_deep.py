import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_copilot.agents.deep import _DeepToolInput

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures/deep_transformer_tool_input.json"


def _load_fixture() -> dict[str, object]:
    with _FIXTURE.open() as f:
        return json.load(f)  # type: ignore[no-any-return]


def test_deep_tool_input_fixture_validates() -> None:
    parsed = _DeepToolInput.model_validate(_load_fixture())
    assert len(parsed.contributions) >= 3
    assert len(parsed.methods) >= 2
    assert len(parsed.experiments) >= 2
    assert len(parsed.limitations) >= 1


def test_deep_tool_input_rejects_missing_required() -> None:
    data = _load_fixture()
    data.pop("contributions")
    with pytest.raises(ValidationError) as exc:
        _DeepToolInput.model_validate(data)
    assert any(
        e["type"] == "missing" and e["loc"] == ("contributions",) for e in exc.value.errors()
    )


def test_deep_tool_input_extra_forbidden() -> None:
    data = _load_fixture() | {"unexpected_field": 1}
    with pytest.raises(ValidationError) as exc:
        _DeepToolInput.model_validate(data)
    assert any(
        e["type"] == "extra_forbidden" and e["loc"] == ("unexpected_field",)
        for e in exc.value.errors()
    )
