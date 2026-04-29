from __future__ import annotations

import json
from pathlib import Path

from scripts.refresh_pdf_library_index_paths import refresh_index


def test_refresh_index_populates_document_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    pdf_root = project_root / "knowledge" / "vendor_documents" / "pdf_library" / "ups" / "eaton" / "93pm"
    pdf_root.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_root / "eaton__93pm__brochure.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mock\n")

    index_path = project_root / "knowledge" / "vendor_documents" / "pdf_library_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "record_count": 1,
        "records": [
            {
                "equipment_family": "ups",
                "manufacturer": "Eaton",
                "model": "93PM",
                "document_type": "official_vendor_pdf",
                "source_url": "https://example.com/brochure.pdf",
                "path": "",
                "document_label": "Eaton 93PM brochure",
            }
        ],
    }
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    result = refresh_index(index_path, project_root / "knowledge" / "vendor_documents" / "pdf_library")
    updated = json.loads(index_path.read_text(encoding="utf-8"))

    assert result["updated"] == 1
    assert updated["records"][0]["path"].endswith("knowledge/vendor_documents/pdf_library/ups/eaton/93pm/eaton__93pm__brochure.pdf")
    assert updated["records"][0]["document_path"] == updated["records"][0]["path"]
