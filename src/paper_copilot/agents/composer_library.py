from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import compute_paper_id

ComposerPool = Literal["ccf_a", "ccf_b", "other"]

POOL_ORDER: tuple[ComposerPool, ...] = ("ccf_a", "ccf_b", "other")


@dataclass(frozen=True, slots=True)
class ComposerPaper:
    pool: ComposerPool
    paper_id: str
    path: Path
    indexed: bool
    title: str
    year: int | None
    venue: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "paper_id": self.paper_id,
            "path": str(self.path),
            "indexed": self.indexed,
            "title": self.title,
            "year": self.year,
            "venue": self.venue,
        }


@dataclass(frozen=True, slots=True)
class ComposerLibrary:
    root: Path
    pools: dict[ComposerPool, tuple[ComposerPaper, ...]]
    missing_pools: tuple[ComposerPool, ...]
    flat_root_as_ccf_a: bool

    def indexed_paper_ids(self, pool: ComposerPool) -> list[str]:
        return [paper.paper_id for paper in self.pools.get(pool, ()) if paper.indexed]

    def unindexed_payload(self, pool: ComposerPool) -> list[dict[str, Any]]:
        return [
            paper.to_payload()
            for paper in self.pools.get(pool, ())
            if not paper.indexed
        ]

    def to_payload(self, *, limit: int) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "required_layout": ["ccf_a or root-level PDFs"],
            "optional_layout": ["ccf_b", "other"],
            "flat_root_as_ccf_a": self.flat_root_as_ccf_a,
            "baseline_pool": "ccf_a",
            "module_pool_order": ["ccf_a", "ccf_b", "other"],
            "fallback_rule": (
                "Search ccf_a for modules first; use ccf_b only after ccf_a "
                "modules are rejected; use other only after ccf_a and ccf_b "
                "are both insufficient."
            ),
            "missing_pools": list(self.missing_pools),
            "pools": {
                pool: _pool_payload(self.pools.get(pool, ()), limit=limit)
                for pool in POOL_ORDER
            },
        }


def load_composer_library(root: Path, fields_store: FieldsStore) -> ComposerLibrary:
    resolved_root = root.expanduser().resolve()
    pools: dict[ComposerPool, tuple[ComposerPaper, ...]] = {}
    missing: list[ComposerPool] = []
    flat_root_pdfs = _root_pdfs(resolved_root)
    for pool in POOL_ORDER:
        pool_dir = resolved_root / pool
        if not pool_dir.is_dir():
            if pool == "ccf_a" and flat_root_pdfs:
                pools[pool] = _papers_from_pdfs(pool, flat_root_pdfs, fields_store)
            else:
                missing.append(pool)
                pools[pool] = ()
            continue
        pdfs = _pool_pdfs(pool_dir)
        if pool == "ccf_a":
            pdfs = [*pdfs, *flat_root_pdfs]
        pools[pool] = _papers_from_pdfs(pool, pdfs, fields_store)
    return ComposerLibrary(
        root=resolved_root,
        pools=pools,
        missing_pools=tuple(missing),
        flat_root_as_ccf_a=bool(flat_root_pdfs),
    )


def _papers_from_pdfs(
    pool: ComposerPool,
    pdf_paths: list[Path],
    fields_store: FieldsStore,
) -> tuple[ComposerPaper, ...]:
    by_id: dict[str, ComposerPaper] = {}
    for pdf_path in pdf_paths:
        paper = _paper_from_pdf(pool, pdf_path, fields_store)
        by_id.setdefault(paper.paper_id, paper)
    return tuple(by_id.values())


def _paper_from_pdf(
    pool: ComposerPool,
    pdf_path: Path,
    fields_store: FieldsStore,
) -> ComposerPaper:
    paper_id = compute_paper_id(pdf_path)
    row = fields_store.get(paper_id)
    meta = row.data.get("meta", {}) if row is not None else {}
    return ComposerPaper(
        pool=pool,
        paper_id=paper_id,
        path=pdf_path.resolve(),
        indexed=row is not None,
        title=_meta_text(meta, "title"),
        year=_meta_year(meta),
        venue=_meta_text(meta, "venue") or None,
    )


def _pool_payload(papers: tuple[ComposerPaper, ...], *, limit: int) -> dict[str, Any]:
    indexed = [paper for paper in papers if paper.indexed]
    unindexed = [paper for paper in papers if not paper.indexed]
    return {
        "count": len(papers),
        "indexed_count": len(indexed),
        "unindexed_count": len(unindexed),
        "papers": [paper.to_payload() for paper in papers[:limit]],
        "unindexed_pdfs": [paper.to_payload() for paper in unindexed[:limit]],
    }


def _pool_pdfs(pool_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in pool_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def _root_pdfs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def _meta_text(meta: dict[str, Any], key: str) -> str:
    value = meta.get(key)
    return value if isinstance(value, str) else ""


def _meta_year(meta: dict[str, Any]) -> int | None:
    value = meta.get("year")
    return value if isinstance(value, int) else None
