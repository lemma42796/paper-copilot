from __future__ import annotations

from paper_copilot.agents.composer_plan import ComposerPlanState
from paper_copilot.agents.composer_proposal import (
    append_composer_check_section,
    check_composer_proposal,
    strip_leading_process_chatter,
)


def test_composer_proposal_checker_accepts_grounded_chinese_report() -> None:
    plan = _ready_plan()
    report = """
## 问题定义

VI-ReID 需要在跨模态噪声下保持身份判别。

## 强基线

选择 base1 作为 CCF A 强基线，因为它有高起点性能，
同时仍存在跨模态噪声瓶颈 [base1:methods[0]]。
在 SYSU-MM01 上达到 Rank-1 80.0%，mAP 75.0% [base1:experiments[0]]。

## 候选模块

- mod1: 将 HSL 接入 baseline encoder，增强局部结构 [mod1:methods[0]]。
- mod2: 将 SFTS 接入特征聚合层，改善时序/空间线索 [mod2:methods[0]]。
- mod3: 将 CIM 接入跨模态交互层，补充实例级对齐 [mod3:methods[0]]。

## 兼容性

三个模块都围绕特征层接入，和 baseline encoder 兼容；
冲突风险主要在训练稳定性。

## 组合方案

保留 base1 主干，只做局部结构、特征聚合和跨模态交互三处小改动。

## 实验方案

预期观察 Rank-1 可能 +1~2%，需要用 ablation 验证，不能直接写成事实结论。

## 风险与缺口

训练设置作为待验证风险，不给出具体数值。

## 证据

- baseline pool: ccf_a; module pools: ccf_a/ccf_a/ccf_a。
""".strip()

    check = check_composer_proposal(report, plan)

    assert check.passed is True
    assert check.issues == ()
    assert append_composer_check_section(report, check) == report


def test_composer_proposal_checker_flags_known_report_failures() -> None:
    plan = _ready_plan()
    raw_report = """
报告已准备好。

## Problem

Use base1 with mod1, mod2, and mod3.

## Baseline

base1 is reproducible [base1:methods[0]].

## Candidate Modules

- mod1: attach HSL [mod1:methods[0]].
- mod2: attach SFTS [mod2:methods[0]].
- mod3: attach CIM [mod3:methods[0]].

## Proposed Composition

Use MRIC-like联合优化 and reduce CIM complexity from O(n²) to linear. Expected +2~4% Rank-1.
AdamW lr=3e-4 batch size 64 for 120 epochs.
""".strip()

    report, removed = strip_leading_process_chatter(raw_report)
    check = check_composer_proposal(
        report,
        plan,
        removed_process_chatter=removed,
    )
    issue_codes = {issue.code for issue in check.issues}

    assert removed == ("报告已准备好。",)
    assert check.passed is False
    assert "english_section_headings" in issue_codes
    assert "baseline_opening_missing" in issue_codes
    assert "unsupported_implementation_specific" in issue_codes
    assert "## 质量检查" in append_composer_check_section(report, check)


def test_composer_proposal_checker_accepts_spaced_citations_and_strips_chatter() -> None:
    plan = _ready_plan()
    raw_report = """
报告已准备就绪，现在撰写最终中文提案。

---

## 问题定义

VI-ReID 需要在跨模态噪声下保持身份判别。

## 强基线

base1 是性能强的高起点，但仍存在跨模态噪声瓶颈 [ base1:methods[0] ]。

## 候选模块

- mod1: 接入 baseline encoder [ mod1:methods[0] ]。
- mod2: 接入特征聚合层 [ mod2:methods[0] ]。
- mod3: 接入跨模态交互层 [ mod3:methods[0] ]。

## 兼容性

三个模块都围绕特征层接入，和 baseline encoder 兼容。

## 组合方案

保留 base1 主干，只做局部结构、特征聚合和跨模态交互三处小改动。

## 实验方案

预期观察 Rank-1 可能 +1~2%，需要用 ablation 验证。

## 风险与缺口

训练设置作为待验证风险，不给出具体数值。

## 证据

- baseline pool: ccf_a; module pools: ccf_a/ccf_a/ccf_a。
""".strip()

    report, removed = strip_leading_process_chatter(raw_report)
    check = check_composer_proposal(report, plan)

    assert removed == ("报告已准备就绪，现在撰写最终中文提案。", "---")
    assert report.startswith("## 问题定义")
    assert check.passed is True


def test_composer_proposal_checker_maps_attachment_table_rows_by_module_label() -> None:
    plan = _ready_plan()
    report = _valid_report_with_extra(
        "训练设置作为待验证风险，不给出具体数值。"
    )
    report = report.replace(
        "三个模块都围绕特征层接入，和 baseline encoder 兼容。",
        "| 模块 | 附着点 | 潜在冲突 |\n"
        "| --- | --- | --- |\n"
        "| HSL | 接入 baseline encoder | 计算开销增加 |\n"
        "| SFTS | 替换特征聚合层 | 需要验证稳定性 |\n"
        "| CIM | 附加到跨模态交互层 | 可能和原交互分支冗余 |",
    )

    check = check_composer_proposal(report, plan)

    assert check.passed is True


def test_composer_proposal_checker_allows_uncited_specifics_only_as_hypotheses() -> None:
    plan = _ready_plan()
    report = _valid_report_with_extra(
        "融合 MRIC 损失与 3M 损失作为联合优化目标，增强跨模态中心分离。"
    )
    hypothesis_report = _valid_report_with_extra(
        "待验证假设：探索是否额外引入距离约束；当前本地证据不足，"
        "不把 MRIC 损失与 3M 损失组合写成主方案承诺。"
    )

    failing = check_composer_proposal(report, plan)
    passing = check_composer_proposal(hypothesis_report, plan)

    assert failing.passed is False
    assert any(
        issue.code == "unsupported_implementation_specific"
        for issue in failing.issues
    )
    assert passing.passed is True


def _ready_plan() -> ComposerPlanState:
    plan = ComposerPlanState()
    plan.mark_library_listed()
    plan.mark_search(
        role="baseline",
        pool="ccf_a",
        query="strong baseline",
        status="ok",
        paper_ids=["base1"],
    )
    plan.mark_inspected("base1")
    plan.select_baseline(
        paper_id="base1",
        rationale="性能强的高起点 baseline，但跨模态噪声仍有改进空间。",
        evidence_refs=["[base1:methods[0]]"],
    )
    plan.mark_search(
        role="module",
        pool="ccf_a",
        query="compatible modules",
        status="ok",
        paper_ids=["mod1", "mod2", "mod3"],
    )
    for paper_id, attachment in (
        ("mod1", "HSL baseline encoder"),
        ("mod2", "SFTS feature aggregation"),
        ("mod3", "CIM cross-modal interaction"),
    ):
        plan.mark_inspected(paper_id)
        plan.accept_module(
            paper_id=paper_id,
            pool="ccf_a",
            rationale=f"{paper_id} can attach to {attachment}.",
            evidence_refs=[f"[{paper_id}:methods[0]]"],
            attachment_point=attachment,
            compatibility_notes="Compatible at the feature level.",
        )
    return plan


def _valid_report_with_extra(extra: str) -> str:
    return f"""
## 问题定义

VI-ReID 需要在跨模态噪声下保持身份判别。

## 强基线

选择 base1 作为 CCF A 强基线，因为它有高起点性能，
同时仍存在跨模态噪声瓶颈 [base1:methods[0]]。

## 候选模块

- mod1: 将 HSL 接入 baseline encoder，增强局部结构 [mod1:methods[0]]。
- mod2: 将 SFTS 接入特征聚合层，改善时序/空间线索 [mod2:methods[0]]。
- mod3: 将 CIM 接入跨模态交互层，补充实例级对齐 [mod3:methods[0]]。

## 兼容性

三个模块都围绕特征层接入，和 baseline encoder 兼容。

## 组合方案

保留 base1 主干，只做局部结构、特征聚合和跨模态交互三处小改动。

## 实验方案

预期观察 Rank-1 可能 +1~2%，需要用 ablation 验证。

## 风险与缺口

{extra}

## 证据

- baseline pool: ccf_a; module pools: ccf_a/ccf_a/ccf_a。
""".strip()
