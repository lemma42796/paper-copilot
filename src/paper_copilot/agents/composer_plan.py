from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal

from paper_copilot.agents.composer_library import ComposerPool

ComposerRole = Literal["baseline", "module"]
ComposerDecisionAction = Literal[
    "select_baseline",
    "accept_module",
    "reject_module",
    "close_module_pool",
]

MODULE_POOL_ORDER: tuple[ComposerPool, ...] = ("ccf_a", "ccf_b", "other")
TARGET_MODULE_COUNT = 3


@dataclass(frozen=True, slots=True)
class ComposerSearchRecord:
    role: ComposerRole
    pool: ComposerPool
    query: str
    status: str
    paper_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "pool": self.pool,
            "query": self.query,
            "status": self.status,
            "paper_ids": list(self.paper_ids),
        }


@dataclass(frozen=True, slots=True)
class ComposerDecision:
    action: ComposerDecisionAction
    paper_id: str
    pool: ComposerPool
    rationale: str
    evidence_refs: tuple[str, ...]
    attachment_point: str | None = None
    compatibility_notes: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "paper_id": self.paper_id,
            "pool": self.pool,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "attachment_point": self.attachment_point,
            "compatibility_notes": self.compatibility_notes,
        }


@dataclass(frozen=True, slots=True)
class ComposerPoolClosure:
    pool: ComposerPool
    rationale: str
    rejected_module_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "rationale": self.rationale,
            "rejected_module_ids": list(self.rejected_module_ids),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(slots=True)
class ComposerPlanState:
    library_listed: bool = False
    baseline_searches: list[ComposerSearchRecord] = dataclass_field(default_factory=list)
    module_searches: dict[ComposerPool, list[ComposerSearchRecord]] = dataclass_field(
        default_factory=lambda: {pool: [] for pool in MODULE_POOL_ORDER}
    )
    inspected_paper_ids: set[str] = dataclass_field(default_factory=set)
    baseline: ComposerDecision | None = None
    accepted_modules: list[ComposerDecision] = dataclass_field(default_factory=list)
    rejected_modules: dict[ComposerPool, list[ComposerDecision]] = dataclass_field(
        default_factory=lambda: {pool: [] for pool in MODULE_POOL_ORDER}
    )
    closed_module_pools: dict[ComposerPool, ComposerPoolClosure] = dataclass_field(
        default_factory=dict
    )

    def mark_library_listed(self) -> None:
        self.library_listed = True

    def mark_search(
        self,
        *,
        role: ComposerRole,
        pool: ComposerPool,
        query: str,
        status: str,
        paper_ids: list[str],
    ) -> None:
        record = ComposerSearchRecord(
            role=role,
            pool=pool,
            query=query,
            status=status,
            paper_ids=tuple(paper_ids),
        )
        if role == "baseline":
            self.baseline_searches.append(record)
        else:
            self.module_searches[pool].append(record)

    def mark_inspected(self, paper_id: str) -> None:
        self.inspected_paper_ids.add(paper_id)

    def require_search_allowed(self, *, role: ComposerRole, pool: ComposerPool) -> None:
        if not self.library_listed:
            raise ValueError(
                "call list_composer_library before search_composer_candidates"
            )
        if role == "baseline":
            if pool != "ccf_a":
                raise ValueError("baseline candidates must come from ccf_a")
            return
        if self.baseline is None:
            raise ValueError("select a CCF A baseline before module search")
        if pool == "ccf_a":
            return
        if pool == "ccf_b" and "ccf_a" in self.closed_module_pools:
            return
        if (
            pool == "other"
            and "ccf_a" in self.closed_module_pools
            and "ccf_b" in self.closed_module_pools
        ):
            return
        if pool == "ccf_b":
            raise ValueError(
                "close ccf_a with rejected modules and a rejection reason "
                "before searching ccf_b"
            )
        raise ValueError(
            "close ccf_a and ccf_b with rejection reasons before searching other"
        )

    def select_baseline(
        self,
        *,
        paper_id: str,
        rationale: str,
        evidence_refs: list[str],
    ) -> ComposerDecision:
        if self.baseline is not None:
            raise ValueError("baseline is already selected")
        if paper_id not in self._searched_ids(role="baseline", pool="ccf_a"):
            raise ValueError("baseline must be selected from ccf_a search results")
        if paper_id not in self.inspected_paper_ids:
            raise ValueError("inspect the baseline paper before selecting it")
        self._require_evidence_refs(evidence_refs)
        decision = ComposerDecision(
            action="select_baseline",
            paper_id=paper_id,
            pool="ccf_a",
            rationale=rationale,
            evidence_refs=tuple(evidence_refs),
        )
        self.baseline = decision
        return decision

    def accept_module(
        self,
        *,
        paper_id: str,
        pool: ComposerPool,
        rationale: str,
        evidence_refs: list[str],
        attachment_point: str | None,
        compatibility_notes: str | None,
    ) -> ComposerDecision:
        self._require_module_candidate(pool=pool, paper_id=paper_id)
        if paper_id in {decision.paper_id for decision in self.accepted_modules}:
            raise ValueError("each module paper can contribute at most one module")
        if paper_id not in self.inspected_paper_ids:
            raise ValueError("inspect a module paper before accepting it")
        if attachment_point is None or compatibility_notes is None:
            raise ValueError(
                "accept_module requires attachment_point and compatibility_notes"
            )
        self._require_evidence_refs(evidence_refs)
        decision = ComposerDecision(
            action="accept_module",
            paper_id=paper_id,
            pool=pool,
            rationale=rationale,
            evidence_refs=tuple(evidence_refs),
            attachment_point=attachment_point,
            compatibility_notes=compatibility_notes,
        )
        self.accepted_modules.append(decision)
        return decision

    def reject_module(
        self,
        *,
        paper_id: str,
        pool: ComposerPool,
        rationale: str,
        evidence_refs: list[str],
    ) -> ComposerDecision:
        self._require_module_candidate(pool=pool, paper_id=paper_id)
        self._require_evidence_refs(evidence_refs)
        decision = ComposerDecision(
            action="reject_module",
            paper_id=paper_id,
            pool=pool,
            rationale=rationale,
            evidence_refs=tuple(evidence_refs),
        )
        self.rejected_modules[pool].append(decision)
        return decision

    def close_module_pool(
        self,
        *,
        pool: ComposerPool,
        rationale: str,
        rejected_module_ids: list[str],
        evidence_refs: list[str],
    ) -> ComposerPoolClosure:
        if self.baseline is None:
            raise ValueError("select a baseline before closing module pools")
        if pool == "other":
            raise ValueError("other is the last fallback pool and cannot unlock another pool")
        searches = self.module_searches[pool]
        if not searches:
            raise ValueError(f"search {pool} modules before closing the pool")
        searched_ids = self._searched_ids(role="module", pool=pool)
        if searched_ids and not rejected_module_ids:
            raise ValueError(
                f"close_module_pool for {pool} requires rejected_module_ids"
            )
        rejected = {decision.paper_id for decision in self.rejected_modules[pool]}
        unknown = sorted(set(rejected_module_ids) - rejected)
        if unknown:
            raise ValueError(
                "rejected_module_ids must be recorded with reject_module first: "
                + ", ".join(unknown)
            )
        if rejected_module_ids:
            self._require_evidence_refs(evidence_refs)
        closure = ComposerPoolClosure(
            pool=pool,
            rationale=rationale,
            rejected_module_ids=tuple(rejected_module_ids),
            evidence_refs=tuple(evidence_refs),
        )
        self.closed_module_pools[pool] = closure
        return closure

    def to_payload(self) -> dict[str, Any]:
        return {
            "workflow": (
                "list library -> ccf_a baseline -> inspect/select baseline -> "
                "ccf_a module search -> suitability check -> optional ccf_b/other "
                "fallback -> structured proposal"
            ),
            "current_step": self.current_step(),
            "allowed_next_tools": self.allowed_next_tools(),
            "report_ready": self.report_ready(),
            "library_listed": self.library_listed,
            "baseline": self.baseline.to_payload() if self.baseline else None,
            "accepted_modules": [
                decision.to_payload() for decision in self.accepted_modules
            ],
            "rejected_modules": {
                pool: [decision.to_payload() for decision in decisions]
                for pool, decisions in self.rejected_modules.items()
            },
            "closed_module_pools": {
                pool: closure.to_payload()
                for pool, closure in self.closed_module_pools.items()
            },
            "baseline_searches": [
                record.to_payload() for record in self.baseline_searches
            ],
            "module_searches": {
                pool: [record.to_payload() for record in records]
                for pool, records in self.module_searches.items()
            },
            "inspected_paper_ids": sorted(self.inspected_paper_ids),
            "final_report_contract": {
                "sections": [
                    "问题定义",
                    "强基线",
                    "候选模块",
                    "兼容性",
                    "组合方案",
                    "实验方案",
                    "风险与缺口",
                    "证据",
                ],
                "must_include": [
                    "Chinese-language final report with Chinese section headings",
                    "baseline paper_id and pool",
                    "baseline performance strength",
                    "baseline improvement opening or story-worthy weakness",
                    "exactly 3 selected module paper_ids and pools",
                    "each accepted module comes from a distinct paper_id",
                    "attachment point for each accepted module",
                    "source paper_id in every compatibility row or bullet",
                    "fallback reason for any module below ccf_a",
                    "citation refs for concrete claims",
                    (
                        "implementation specifics such as new loss combinations, "
                        "framework names, metric gains, training hyperparameters, "
                        "or complexity changes must be cited or explicitly marked "
                        "as hypotheses/gaps"
                    ),
                ],
            },
        }

    def current_step(self) -> str:
        if not self.library_listed:
            return "list_composer_library"
        if not self.baseline_searches:
            return "search_ccf_a_baseline"
        if self.baseline is None:
            return "inspect_and_select_baseline"
        if not self.module_searches["ccf_a"]:
            return "search_ccf_a_modules"
        if len(self.accepted_modules) >= TARGET_MODULE_COUNT:
            return "write_structured_proposal"
        if "ccf_a" not in self.closed_module_pools:
            return "check_or_close_ccf_a_modules"
        if not self.module_searches["ccf_b"]:
            return "search_ccf_b_modules"
        if "ccf_b" not in self.closed_module_pools:
            return "check_or_close_ccf_b_modules"
        if not self.module_searches["other"]:
            return "search_other_modules"
        return "write_structured_proposal_with_gaps"

    def allowed_next_tools(self) -> list[str]:
        step = self.current_step()
        match step:
            case "list_composer_library":
                return ["list_composer_library"]
            case "search_ccf_a_baseline":
                return ["search_composer_candidates(role=baseline,pool=ccf_a)"]
            case "inspect_and_select_baseline":
                return ["inspect_paper", "update_composer_plan(action=select_baseline)"]
            case "search_ccf_a_modules":
                return ["search_composer_candidates(role=module,pool=ccf_a)"]
            case "check_or_close_ccf_a_modules":
                return [
                    "inspect_paper",
                    "update_composer_plan(action=accept_module)",
                    "update_composer_plan(action=reject_module)",
                    "update_composer_plan(action=close_module_pool,pool=ccf_a)",
                ]
            case "search_ccf_b_modules":
                return ["search_composer_candidates(role=module,pool=ccf_b)"]
            case "check_or_close_ccf_b_modules":
                return [
                    "inspect_paper",
                    "update_composer_plan(action=accept_module)",
                    "update_composer_plan(action=reject_module)",
                    "update_composer_plan(action=close_module_pool,pool=ccf_b)",
                ]
            case "search_other_modules":
                return ["search_composer_candidates(role=module,pool=other)"]
            case _:
                return ["write_final_proposal"]

    def report_ready(self) -> bool:
        return self.baseline is not None and (
            len(self.accepted_modules) >= TARGET_MODULE_COUNT
            or bool(self.module_searches["other"])
        )

    def _require_module_candidate(self, *, pool: ComposerPool, paper_id: str) -> None:
        if self.baseline is None:
            raise ValueError("select a baseline before checking modules")
        if paper_id not in self._searched_ids(role="module", pool=pool):
            raise ValueError(f"module must come from {pool} search results")

    def _require_evidence_refs(self, evidence_refs: list[str]) -> None:
        if not evidence_refs:
            raise ValueError("composer plan decisions require at least one evidence_ref")

    def _searched_ids(self, *, role: ComposerRole, pool: ComposerPool) -> set[str]:
        records = (
            self.baseline_searches
            if role == "baseline"
            else self.module_searches[pool]
        )
        return {
            paper_id
            for record in records
            if record.pool == pool
            for paper_id in record.paper_ids
        }
