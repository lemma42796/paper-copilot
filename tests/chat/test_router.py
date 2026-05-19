from __future__ import annotations

from paper_copilot.chat.router import route_chat_request


def test_route_chat_request_detects_framework_composer_intent() -> None:
    route = route_chat_request("基于 diffusion model 和医学图像分割, 帮我找一个可做的创新点")

    assert route.kind == "framework_composer"
    assert route.output_profile == "framework_composer"
    assert route.task_profile == "framework_composer"


def test_route_chat_request_detects_baseline_module_intent() -> None:
    route = route_chat_request("先找一个 baseline, 再找几个可接入模块")

    assert route.kind == "framework_composer"
    assert route.output_profile == "framework_composer"
    assert route.task_profile == "framework_composer"


def test_route_chat_request_defaults_to_knowledge_qa() -> None:
    route = route_chat_request("比较 sparse attention 和 full attention 的差异")

    assert route.kind == "knowledge_qa"
    assert route.output_profile == "knowledge_qa"
    assert route.task_profile == "fixed_set_compare"


def test_route_chat_request_detects_single_paper_focus() -> None:
    route = route_chat_request("解释 ViT 论文的核心方法和主要贡献")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "single_paper_focus"


def test_route_chat_request_detects_evidence_lookup() -> None:
    route = route_chat_request("有没有论文提到 sparse attention 的证据")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "evidence_lookup"


def test_route_chat_request_detects_claim_check() -> None:
    route = route_chat_request("判断这个说法是否成立: ViT 完全不需要 CNN inductive bias")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "claim_check"


def test_route_chat_request_detects_experiment_extraction() -> None:
    route = route_chat_request("抽取 ResNet 的数据集、指标、训练技巧和消融设置")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "experiment_extraction"


def test_route_chat_request_detects_timeline_synthesis() -> None:
    route = route_chat_request("总结图像识别架构从 AlexNet 到 ViT 的演化脉络")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "timeline_synthesis"


def test_route_chat_request_detects_gap_analysis() -> None:
    route = route_chat_request("总结这批论文的局限、不足和未来工作")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "gap_analysis"


def test_route_chat_request_uses_topic_survey_as_fallback() -> None:
    route = route_chat_request("总结行人重识别有哪些代表方法")

    assert route.kind == "knowledge_qa"
    assert route.task_profile == "topic_survey"
