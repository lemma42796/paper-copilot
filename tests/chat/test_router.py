from __future__ import annotations

from paper_copilot.chat.router import route_chat_request


def test_route_chat_request_detects_idea_composer_intent() -> None:
    route = route_chat_request("基于 diffusion model 和医学图像分割, 帮我找一个可做的创新点")

    assert route.kind == "idea_composer"
    assert route.output_profile == "idea_composer"


def test_route_chat_request_detects_baseline_module_intent() -> None:
    route = route_chat_request("先找一个 baseline, 再找几个可接入模块")

    assert route.kind == "idea_composer"
    assert route.output_profile == "idea_composer"


def test_route_chat_request_defaults_to_research() -> None:
    route = route_chat_request("比较 sparse attention 和 full attention 的差异")

    assert route.kind == "research"
    assert route.output_profile == "research_report"
