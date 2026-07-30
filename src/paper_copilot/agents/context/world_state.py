from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from paper_copilot.session.types import SessionEntry, WorldState

WorldStateSnapshot = dict[str, Any]


@dataclass(frozen=True, slots=True)
class WorldStateUpdate:
    mode: Literal["full", "patch"]
    state: WorldStateSnapshot
    snapshot: WorldStateSnapshot
    rendered: str


class WorldStateEngine:
    def __init__(self, baseline: WorldStateSnapshot | None = None) -> None:
        self._baseline = deepcopy(baseline)

    @property
    def baseline(self) -> WorldStateSnapshot | None:
        return deepcopy(self._baseline)

    def update(self, snapshot: WorldStateSnapshot) -> WorldStateUpdate | None:
        current = _without_null_object_fields(snapshot)
        if self._baseline is None:
            update = WorldStateUpdate(
                mode="full",
                state=deepcopy(current),
                snapshot=deepcopy(current),
                rendered=_render("full", current),
            )
            self._baseline = deepcopy(current)
            return update
        patch = create_merge_patch(self._baseline, current)
        if patch is None:
            return None
        if not isinstance(patch, dict):
            raise TypeError("world-state root merge patch must be an object")
        update = WorldStateUpdate(
            mode="patch",
            state=patch,
            snapshot=deepcopy(current),
            rendered=_render("patch", patch),
        )
        self._baseline = deepcopy(current)
        return update

    def replace_baseline(self, snapshot: WorldStateSnapshot) -> WorldStateUpdate:
        current = _without_null_object_fields(snapshot)
        self._baseline = deepcopy(current)
        return WorldStateUpdate(
            mode="full",
            state=deepcopy(current),
            snapshot=deepcopy(current),
            rendered=_render("full", current),
        )

    def render_full(self, snapshot: WorldStateSnapshot) -> str:
        return _render("full", _without_null_object_fields(snapshot))


def reconstruct_world_state(
    entries: list[SessionEntry],
) -> WorldStateSnapshot | None:
    baseline: WorldStateSnapshot | None = None
    for entry in entries:
        if not isinstance(entry, WorldState):
            continue
        if entry.mode == "full":
            baseline = deepcopy(entry.state)
        elif baseline is not None:
            baseline = apply_merge_patch(baseline, entry.state)
    return baseline


def create_merge_patch(previous: Any, current: Any) -> Any | None:
    if previous == current:
        return None
    if not isinstance(current, dict):
        return deepcopy(current)
    previous_object = previous if isinstance(previous, dict) else {}
    patch: dict[str, Any] = {}
    for key in previous_object:
        if key not in current:
            patch[key] = None
    for key, current_value in current.items():
        if key not in previous_object:
            patch[key] = deepcopy(current_value)
            continue
        value_patch = create_merge_patch(previous_object[key], current_value)
        if value_patch is not None:
            patch[key] = value_patch
    return patch


def apply_merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return deepcopy(patch)
    merged = deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = apply_merge_patch(merged.get(key), value)
    return merged


def _without_null_object_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_null_object_fields(child)
            for key, child in value.items()
            if child is not None
        }
    if isinstance(value, list):
        return [_without_null_object_fields(child) for child in value]
    return deepcopy(value)


def _render(mode: Literal["full", "patch"], state: WorldStateSnapshot) -> str:
    return (
        f'<world_state mode="{mode}">\n'
        f"{json.dumps(state, ensure_ascii=False, separators=(',', ':'))}\n"
        "</world_state>"
    )
