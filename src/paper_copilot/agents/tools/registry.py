from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from paper_copilot.agents.loop import ToolResultData
from paper_copilot.agents.tool_security import ToolDefinition
from paper_copilot.shared.errors import AgentError

ToolHandler = Callable[[BaseModel, Any], Awaitable[ToolResultData]]
ToolExposure = Callable[["ToolExposureContext"], bool]
ToolSchemaBuilder = Callable[[str, str, type[BaseModel]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolExposureContext:
    library_available: bool
    persistent_exec_available: bool
    image_input_available: bool
    formula_ocr_available: bool


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler
    exposed_when: ToolExposure


class ToolRegistry:
    def __init__(self, tools: tuple[RegisteredTool, ...]) -> None:
        by_name = {tool.definition.name: tool for tool in tools}
        if len(by_name) != len(tools):
            raise AgentError("tool registry contains duplicate names")
        self._tools = by_name

    def definitions(
        self,
        exposure: ToolExposureContext,
    ) -> tuple[ToolDefinition, ...]:
        return tuple(
            registered.definition
            for registered in self._tools.values()
            if registered.exposed_when(exposure)
        )

    def schemas(
        self,
        exposure: ToolExposureContext,
        *,
        build_schema: ToolSchemaBuilder,
    ) -> list[dict[str, Any]]:
        return [
            build_schema(
                definition.name,
                definition.description,
                definition.input_model,
            )
            for definition in self.definitions(exposure)
        ]

    def resolve(
        self,
        name: str,
        exposure: ToolExposureContext,
    ) -> RegisteredTool | None:
        registered = self._tools.get(name)
        if registered is None or not registered.exposed_when(exposure):
            return None
        return registered

    async def dispatch(
        self,
        name: str,
        parsed_input: BaseModel,
        exposure: ToolExposureContext,
        execution_context: Any,
    ) -> ToolResultData:
        registered = self.resolve(name, exposure)
        if registered is None:
            raise AgentError(f"tool is not exposed to the agent: {name}")
        return await registered.handler(parsed_input, execution_context)
