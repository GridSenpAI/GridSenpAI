from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(make_json_safe(payload), file, indent=2, ensure_ascii=False, default=str)


def relative_to_run_dir(path: Path, run_dir: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def slugify_label(label: str) -> str:
    cleaned = []
    for char in label.strip().lower():
        if char.isalnum():
            cleaned.append(char)
        else:
            cleaned.append("_")
    slug = "".join(cleaned)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "snapshot"


def count_persisted_stage_files(run_dir: Path) -> int:
    stage_dir = run_dir / "stages"
    if not stage_dir.exists():
        return 0
    return len(list(stage_dir.glob("*.json")))


def derive_canonical_state_stats(canonical_state: dict[str, Any]) -> dict[str, Any]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    return {
        "state_version": str(state.get("state_version", "unknown")),
        "governance_version": str(state.get("governance_version", "unknown")),
        "field_record_count": len(state.get("field_records", []) or []),
        "conflict_count": len(state.get("conflict_records", []) or []),
        "review_flag_count": len(state.get("review_flags", []) or []),
        "stage_status": dict(state.get("stage_status", {}) or {}),
    }


def load_parent_lineage(parent_run_dir: Path) -> dict[str, Any] | None:
    lineage_path = parent_run_dir / "lineage.json"
    payload = read_json(lineage_path, default=None)
    return payload if isinstance(payload, dict) else None