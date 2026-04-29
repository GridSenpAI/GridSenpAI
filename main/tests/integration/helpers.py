from __future__ import annotations

import shutil
from pathlib import Path


ROOT_ONLY_IGNORES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "exports",
    "models",
    "node_modules",
    "runs",
    "sample_documents_for_test_runs",
    "other_sample_data",
}

ANYWHERE_IGNORES = {
    "__pycache__",
    ".gridsenpai_ocr_tmp",
}


def prepare_writable_workspace(tmp_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in ANYWHERE_IGNORES}

        if Path(directory).resolve() == source_root.resolve():
            ignored.update(name for name in names if name in ROOT_ONLY_IGNORES)

        return ignored

    shutil.copytree(source_root, workspace, ignore=_ignore)
    return workspace
