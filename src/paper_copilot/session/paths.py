import hashlib
import os
from pathlib import Path

from paper_copilot.shared.env import load_env

_ENV_VAR = "PAPER_COPILOT_HOME"
_PDF_DIR_ENV_VAR = "PAPER_COPILOT_PDF_DIR"
_LOCAL_DEFAULT_PDF_DIR = Path("/Users/a123/paper-copilot-test-pdfs")


def default_root() -> Path:
    load_env()
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".paper-copilot"


def embedding_cache_file(root: Path | None = None) -> Path:
    base = root if root is not None else default_root()
    return base / "embedding_cache.sqlite"


def default_pdf_dir() -> Path | None:
    load_env()
    override = os.environ.get(_PDF_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if _LOCAL_DEFAULT_PDF_DIR.exists():
        return _LOCAL_DEFAULT_PDF_DIR
    return None


def paper_dir(paper_id: str, root: Path | None = None) -> Path:
    base = root if root is not None else default_root()
    return base / "papers" / paper_id


def session_file(paper_id: str, root: Path | None = None) -> Path:
    return paper_dir(paper_id, root) / "session.jsonl"


def compute_paper_id(pdf_path: Path) -> str:
    h = hashlib.sha1()
    with pdf_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]
