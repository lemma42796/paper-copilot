import hashlib
import os
from pathlib import Path

_ENV_VAR = "PAPER_COPILOT_HOME"


def default_root() -> Path:
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".paper-copilot"


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
