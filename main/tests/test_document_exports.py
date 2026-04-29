from __future__ import annotations

import builtins

from services.export_service.document_exports import build_docx_bytes


def test_build_docx_bytes_falls_back_when_python_docx_is_unavailable(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docx" or name.startswith("docx."):
            raise ModuleNotFoundError("docx not available")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    payload = build_docx_bytes(
        "# Title\n\n- Bullet",
        run_id="run_test_001",
        generated_at="2026-04-21T00:00:00Z",
        title_text="GridSenpAI Planner TLDR Summary",
    )

    assert isinstance(payload, bytes)
    assert payload[:2] == b"PK"
    assert len(payload) > 200
