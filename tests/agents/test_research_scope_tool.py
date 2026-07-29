from __future__ import annotations

from pathlib import Path

import pytest

from paper_copilot.agents.research_evidence import (
    ActivePaperSnapshot,
    PageEvidenceFact,
    extract_research_citations,
    render_research_citation_links,
)
from paper_copilot.agents.research_scope_tool import (
    ResearchScopeExclusion,
    UpdateResearchScopeInput,
    load_research_scope_exclusions,
    research_scope_context_fragment,
    run_update_research_scope,
)
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import KnowledgeError

PDF_SHA256 = "a" * 64
OTHER_PDF_SHA256 = "b" * 64
EXTRACTOR_SHA256 = "c" * 64
ARTIFACT_SHA256 = "d" * 64


def test_scope_update_persists_observed_exclusion(tmp_path: Path) -> None:
    store = _store(tmp_path, "scope-update")
    active_paper = _active_paper(PDF_SHA256)
    exclusion = _exclusion(PDF_SHA256)
    existing_exclusions: dict[str, ResearchScopeExclusion] = {}

    output = run_update_research_scope(
        UpdateResearchScopeInput(exclusions=[exclusion]),
        store=store,
        active_papers={PDF_SHA256: active_paper},
        evidence_facts=(_page_evidence(PDF_SHA256),),
        existing_exclusions=existing_exclusions,
    )

    assert output["newly_excluded_paper_ids"] == [PDF_SHA256]
    assert output["persistent_excluded_paper_ids"] == [PDF_SHA256]
    assert existing_exclusions == {PDF_SHA256: exclusion}
    assert load_research_scope_exclusions(store) == (exclusion,)


def test_scope_update_rejects_unobserved_exclusion(tmp_path: Path) -> None:
    store = _store(tmp_path, "scope-unobserved")
    active_paper = _active_paper(PDF_SHA256)

    with pytest.raises(KnowledgeError, match="was not observed in this turn"):
        run_update_research_scope(
            UpdateResearchScopeInput(exclusions=[_exclusion(PDF_SHA256)]),
            store=store,
            active_papers={PDF_SHA256: active_paper},
            evidence_facts=(),
            existing_exclusions={},
        )

    assert load_research_scope_exclusions(store) == ()


def test_scope_exclusions_recover_from_source_session(tmp_path: Path) -> None:
    source = _store(tmp_path, "scope-source")
    exclusion = _exclusion(PDF_SHA256)
    run_update_research_scope(
        UpdateResearchScopeInput(exclusions=[exclusion]),
        store=source,
        active_papers={PDF_SHA256: _active_paper(PDF_SHA256)},
        evidence_facts=(_page_evidence(PDF_SHA256),),
        existing_exclusions={},
    )
    resumed = _store(tmp_path, "scope-resumed")
    resumed.append_recovery_base(
        source_session_path=str(source.path),
        history=[],
        runtime_state=None,
        compaction_summary=None,
    )

    assert load_research_scope_exclusions(resumed) == (exclusion,)


def test_scope_context_exposes_identity_but_not_model_reason() -> None:
    exclusion = _exclusion(PDF_SHA256)

    fragment = research_scope_context_fragment(
        (exclusion,),
        (_active_paper(PDF_SHA256),),
    )

    assert fragment is not None
    assert PDF_SHA256 in fragment
    assert "library/paper.pdf" in fragment
    assert exclusion.reason not in fragment


def test_citation_resolution_does_not_require_all_paper_coverage() -> None:
    active_papers = (
        _active_paper(PDF_SHA256),
        _active_paper(OTHER_PDF_SHA256),
    )
    report = f"结论 [{PDF_SHA256}:page[4]]"

    citations = extract_research_citations(
        report,
        active_papers=active_papers,
    )

    assert len(citations) == 1
    assert citations[0].pdf_sha256 == PDF_SHA256
    assert citations[0].page == 4
    assert citations[0].href.startswith("paper-copilot://open?")


def test_citation_rendering_replaces_known_ref_but_does_not_block_unknown_ref() -> None:
    known_ref = f"[{PDF_SHA256}:page[4]]"
    unknown_ref = f"[{OTHER_PDF_SHA256}:page[4]]"
    report = f"已知 {known_ref}；未知 {unknown_ref}"
    citations = extract_research_citations(
        report,
        active_papers=(_active_paper(PDF_SHA256),),
    )

    rendered = render_research_citation_links(report, citations=citations)

    assert "《paper》第 4 页" in rendered
    assert "paper-copilot://open?" in rendered
    assert unknown_ref in rendered


def _store(root: Path, session_id: str) -> SessionStore:
    return SessionStore.create(
        session_id,
        model="test-model",
        agent="PaperCopilot",
        root=root,
    )


def _active_paper(pdf_sha256: str) -> ActivePaperSnapshot:
    return ActivePaperSnapshot(
        source_locator="paper.pdf",
        pdf_sha256=pdf_sha256,
        page_count=10,
        extractor_fingerprint=EXTRACTOR_SHA256,
        cache_revision_id="revision-1",
        artifact_sha256=ARTIFACT_SHA256,
    )


def _page_evidence(pdf_sha256: str) -> PageEvidenceFact:
    return PageEvidenceFact(
        source_tool_call_id=f"read-{pdf_sha256[:4]}",
        source_kind="cached_text_page",
        pdf_sha256=pdf_sha256,
        page=4,
        artifact_sha256=ARTIFACT_SHA256,
        extractor_fingerprint=EXTRACTOR_SHA256,
        cache_revision_id="revision-1",
    )


def _exclusion(pdf_sha256: str) -> ResearchScopeExclusion:
    return ResearchScopeExclusion(
        pdf_sha256=pdf_sha256,
        reason="用户要求后续排除主要无监督论文",
        evidence_refs=(f"[{pdf_sha256}:page[4]]",),
    )
