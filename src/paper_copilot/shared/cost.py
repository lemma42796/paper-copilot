"""Token-usage and CNY cost tracking for qwen3.6-flash via Dashscope.

Consumes the ``usage`` object returned by the Anthropic-compatible API
(either a real ``anthropic.types.Usage`` instance or a plain ``dict``).
This module must not import the ``anthropic`` SDK — ``shared/`` is below
the SDK boundary. The ``UsageLike`` alias describes the shape
structurally.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Protocol

from paper_copilot.shared.logging import get_logger


@dataclass(frozen=True, slots=True)
class QwenFlashPricing:
    """Dashscope qwen3.6-flash tiered pricing, CNY per million tokens.

    source: https://help.aliyun.com/zh/model-studio/models (qwen3.6-flash 产品页)
    accessed: 2026-04-19
    note: Batch mode and tool-call pricing are out of scope for M2; we only
    model the four line items below.
    """

    INPUT_PER_MTOK_CNY: float = 1.2
    CACHE_CREATE_PER_MTOK_CNY: float = 1.5
    CACHE_HIT_PER_MTOK_CNY: float = 0.12
    OUTPUT_PER_MTOK_CNY: float = 7.2


@dataclass(frozen=True, slots=True)
class CostSnapshot:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_cny: float


class _UsageObject(Protocol):
    input_tokens: int
    output_tokens: int
    # cache_creation_input_tokens / cache_read_input_tokens are intentionally
    # absent from the Protocol — Dashscope's Anthropic-compat endpoint does
    # not always return them, so we read with getattr(..., 0) at runtime.


type UsageLike = _UsageObject | Mapping[str, int | None]


def _read(usage: UsageLike, name: str) -> int:
    value = usage.get(name, 0) if isinstance(usage, Mapping) else getattr(usage, name, 0)
    return value or 0


class CostTracker:
    def __init__(self, pricing: QwenFlashPricing | None = None) -> None:
        self._pricing = pricing if pricing is not None else QwenFlashPricing()
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_creation_tokens = 0
        self._cost_cny = 0.0

    def record(self, usage: UsageLike) -> None:
        # TODO(M5): 首次调 Dashscope 时验证 usage 是否仍是 disjoint 语义,
        # 若为 OTel 风格的 overlapping 语义需调整计费公式。
        input_tok = _read(usage, "input_tokens")
        output_tok = _read(usage, "output_tokens")
        cache_create_tok = _read(usage, "cache_creation_input_tokens")
        cache_read_tok = _read(usage, "cache_read_input_tokens")

        self._input_tokens += input_tok
        self._output_tokens += output_tok
        self._cache_creation_tokens += cache_create_tok
        self._cache_read_tokens += cache_read_tok

        p = self._pricing
        cost = (
            input_tok * p.INPUT_PER_MTOK_CNY
            + output_tok * p.OUTPUT_PER_MTOK_CNY
            + cache_create_tok * p.CACHE_CREATE_PER_MTOK_CNY
            + cache_read_tok * p.CACHE_HIT_PER_MTOK_CNY
        ) / 1_000_000
        self._cost_cny += cost

    @property
    def total_input_tokens(self) -> int:
        return self._input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._output_tokens

    @property
    def total_cache_read_tokens(self) -> int:
        return self._cache_read_tokens

    @property
    def total_cache_creation_tokens(self) -> int:
        return self._cache_creation_tokens

    @property
    def total_cost_cny(self) -> float:
        return self._cost_cny

    def snapshot(self) -> CostSnapshot:
        return CostSnapshot(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_read_tokens=self._cache_read_tokens,
            cache_creation_tokens=self._cache_creation_tokens,
            cost_cny=self._cost_cny,
        )

    def __enter__(self) -> CostTracker:
        return self

    def __exit__(self, *args: object) -> None:
        get_logger(__name__).info("cost.summary", **asdict(self.snapshot()))
