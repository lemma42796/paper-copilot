from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast


REPO = Path("/Users/a123/code/paper-copilot")
EVAL_ROOT = Path("/Users/a123/paper-copilot-eval-private/multi-thesis-v1")
PDF_DIR = Path("/Users/a123/paper-copilot-test-pdfs/硕士学位论文")
QUERY_FILE = EVAL_ROOT / "queries.md"
PRIVATE_CONFIG = Path("/Users/a123/.codex-deepseek/config.toml")
CODEX_C_ROLLOUT = Path(
    "/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/"
    "codex-v4flash-responses-library-c-query1/"
    "20260801T161359Z-lane-c-671ee6bf-e2a7-4d2b-b9c2-829b7869a598/"
    "codex-home/sessions/2026/08/02/"
    "rollout-2026-08-02T00-14-01-019fbe1a-954c-7b81-8f78-a32cc6b50845.jsonl"
)

Lane = Literal["p0", "p1", "p2", "p3"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", choices=("p0", "p1", "p2", "p3"), required=True)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _frozen_query_one() -> str:
    text = QUERY_FILE.read_text(encoding="utf-8")
    start = text.index("## Query 1") + len("## Query 1")
    end = text.index("## Query 2", start)
    return text[start:end].strip()


def _wait_for_terminal(registry: object, job_id: str, timeout: float) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = registry.get(job_id)  # type: ignore[attr-defined]
        if record.status in {"completed", "failed", "interrupted"}:
            return record
        time.sleep(0.25)
    raise TimeoutError(f"local runner timed out waiting for {job_id}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _configure_provider() -> None:
    config = tomllib.loads(PRIVATE_CONFIG.read_text(encoding="utf-8"))
    provider = config["model_providers"]["deepseek"]
    api_key = provider.get("experimental_bearer_token", "")
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError("DeepSeek bearer token is missing from private config")
    os.environ["LLM_API_KEY"] = api_key
    os.environ["LLM_BASE_URL"] = str(provider["base_url"]).rstrip("/")
    os.environ["LLM_MODEL"] = "deepseek-v4-flash"
    os.environ["LLM_REASONING_EFFORT"] = "max"
    os.environ["LLM_THINKING_PROTOCOL"] = "deepseek"
    os.environ["LLM_INPUT_MODALITIES"] = "text"


def _codex_base_instructions() -> str:
    with CODEX_C_ROLLOUT.open(encoding="utf-8") as handle:
        first = json.loads(handle.readline())
    text = first["payload"]["base_instructions"]["text"]
    if not isinstance(text, str) or not text:
        raise RuntimeError("frozen Codex base instructions are unavailable")
    return text


def _apply_lane(lane: Lane) -> dict[str, object]:
    from paper_copilot.agents import paper_copilot as agent
    from paper_copilot.agents.context.world_state import WorldStateEngine
    from paper_copilot.agents.research_skill import load_research_skill

    details: dict[str, object] = {"lane": lane}
    if lane == "p0":
        details["override"] = "none"
        return details

    if lane == "p1":
        skill = load_research_skill()
        original_tools = agent.paper_copilot_tools
        original_prompt = agent._BASE_SYSTEM_PROMPT
        load_instruction = (
            "When local PDF research is needed, call load_skill before using the "
            "research tools; the returned version is fixed for this conversation. "
        )
        injected_instruction = (
            "The bundled research Skill below is already loaded and fixed for this "
            "conversation; follow it when local PDF research is needed. "
        )
        if load_instruction not in original_prompt:
            raise RuntimeError("Paper Copilot load_skill instruction changed")

        def tools_without_load_skill(
            exposure: object | None = None,
        ) -> list[dict[str, Any]]:
            schemas = original_tools(cast(Any, exposure))
            return [schema for schema in schemas if schema["name"] != "load_skill"]

        agent.paper_copilot_tools = tools_without_load_skill
        agent._BASE_SYSTEM_PROMPT = (
            original_prompt.replace(load_instruction, injected_instruction)
            + "\n\n"
            + skill.context_fragment()
        )
        details.update(
            {
                "override": "static_skill_injection_without_load_skill",
                "skill_sha256": skill.sha256,
                "system_prompt_sha256": hashlib.sha256(
                    agent._BASE_SYSTEM_PROMPT.encode("utf-8")
                ).hexdigest(),
            }
        )
        return details

    if lane == "p2":

        class SuppressedWorldStateEngine(WorldStateEngine):
            def update(self, snapshot: dict[str, Any]) -> None:
                del snapshot
                return None

            def render_full(self, snapshot: dict[str, Any]) -> str:
                del snapshot
                return ""

        agent.WorldStateEngine = SuppressedWorldStateEngine
        details["override"] = "suppress_model_visible_world_state"
        return details

    codex_prompt = _codex_base_instructions()
    agent._BASE_SYSTEM_PROMPT = codex_prompt
    details.update(
        {
            "override": "codex_base_instructions",
            "system_prompt_length": len(codex_prompt),
            "system_prompt_sha256": hashlib.sha256(
                codex_prompt.encode("utf-8")
            ).hexdigest(),
        }
    )
    return details


def main() -> None:
    args = _parse_args()
    lane = cast(Lane, args.lane)
    batch_root = args.batch_root.expanduser().resolve()
    batch_root.mkdir(parents=True, exist_ok=True)
    _configure_provider()
    lane_details = _apply_lane(lane)

    from paper_copilot.chat.jobs import ChatJobSpec, job_registry

    mode = "smoke" if args.smoke else "formal"
    run_dir = batch_root / f"{lane}-{mode}-{_utc_stamp()}"
    runtime_root = run_dir / "runtime-root"
    run_dir.mkdir(parents=True)
    request = "你好" if args.smoke else _frozen_query_one()
    (run_dir / "request.md").write_text(request + "\n", encoding="utf-8")

    registry = job_registry(runtime_root)
    started_at = datetime.now(UTC)
    created = registry.create(
        ChatJobSpec(
            request=request,
            pdf_dir=str(PDF_DIR),
            budget_cny=0.1 if args.smoke else 1.0,
            max_papers=14,
            record_quality=False,
            update_report=False,
            rollout_timeout_seconds=300 if args.smoke else 1200,
            approval_mode="auto_review",
        )
    )
    print(f"RUN_DIR={run_dir}", flush=True)
    print(f"LANE={lane}", flush=True)
    print(f"JOB_ID={created.id}", flush=True)
    record = _wait_for_terminal(
        registry,
        created.id,
        360 if args.smoke else 1260,
    )
    finished_at = datetime.now(UTC)
    serialized = record.model_dump(mode="json")  # type: ignore[attr-defined]
    _write_json(run_dir / "result.json", serialized)
    result = record.result  # type: ignore[attr-defined]
    if result is not None:
        (run_dir / "answer.md").write_text(
            result.report_markdown.rstrip() + "\n",
            encoding="utf-8",
        )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    metadata = {
        "lane": lane,
        "mode": mode,
        "lane_details": lane_details,
        "created_at": started_at.isoformat(),
        "updated_at": finished_at.isoformat(),
        "code_commit": commit,
        "corpus_version": "multi-thesis-v1",
        "model": "deepseek-v4-flash",
        "reasoning_effort": "max",
        "input_modalities": ["text"],
        "conversation_id": created.spec.conversation_id,
        "job_id": created.id,
        "status": record.status,  # type: ignore[attr-defined]
        "error": record.error,  # type: ignore[attr-defined]
        "termination_reason": (
            result.termination_reason if result is not None else None
        ),
        "cost_cny": result.cost_cny if result is not None else None,
        "session_path": result.session_path if result is not None else None,
        "credential": "read from private config; not persisted in artifacts",
    }
    _write_json(run_dir / "run_metadata.json", metadata)
    print(f"STATUS={record.status}", flush=True)  # type: ignore[attr-defined]
    if result is not None:
        print(f"COST_CNY={result.cost_cny}", flush=True)
    if record.status != "completed":  # type: ignore[attr-defined]
        raise RuntimeError(record.error or "lane did not complete")  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
