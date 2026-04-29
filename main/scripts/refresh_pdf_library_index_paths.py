from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = PROJECT_ROOT / "knowledge" / "vendor_documents" / "pdf_library"
INDEX_PATH = PROJECT_ROOT / "knowledge" / "vendor_documents" / "pdf_library_index.json"

MANUFACTURER_ALIASES = {
    "rollsroycemtu": "mtu",
    "mturollsroyce": "mtu",
    "schneiderelectric": "schneider_electric",
    "mitsubishi": "mitsubishi_electric",
    "mitsubishielectric": "mitsubishi_electric",
}


def normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def canonical_manufacturer_slug(family: str, manufacturer: str) -> str:
    family_slug = slugify(family)
    manufacturer_slug = slugify(manufacturer)
    if family_slug == "generators" and manufacturer_slug == "mtu":
        return "mtu_rolls_royce"
    return manufacturer_slug


def manufacturer_key(value: Any) -> str:
    normalized = normalize_token(value)
    return normalize_token(MANUFACTURER_ALIASES.get(normalized, value))


def build_pdf_catalog(pdf_root: Path, *, project_root: Path) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    catalog: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for pdf_path in sorted(pdf_root.rglob("*.pdf")):
        rel = pdf_path.relative_to(project_root).as_posix()
        parts = rel.split("/")
        if len(parts) < 6:
            continue
        family = normalize_token(parts[3])
        manufacturer = manufacturer_key(parts[4])
        model = normalize_token(parts[5])
        catalog.setdefault((family, manufacturer, model), []).append({
            "relative_path": rel,
            "file_name": pdf_path.name,
            "stem_key": normalize_token(pdf_path.stem),
        })
    return catalog


def choose_candidate(candidates: list[dict[str, str]], record: dict[str, Any]) -> str:
    if not candidates:
        return ""
    source_url = str(record.get("source_url", "")).strip()
    source_name = Path(source_url).name
    source_key = normalize_token(Path(source_name).stem)
    if source_key:
        for candidate in candidates:
            if candidate["stem_key"] == source_key or source_key in candidate["stem_key"] or candidate["stem_key"] in source_key:
                return candidate["relative_path"]
    current_path = str(record.get("path") or record.get("document_path") or "").strip()
    current_key = normalize_token(Path(current_path).stem)
    if current_key:
        for candidate in candidates:
            if candidate["stem_key"] == current_key or current_key in candidate["stem_key"] or candidate["stem_key"] in current_key:
                return candidate["relative_path"]
    if len(candidates) == 1:
        return candidates[0]["relative_path"]
    label_key = normalize_token(record.get("document_label", ""))
    best_score = None
    best_path = candidates[0]["relative_path"]
    for candidate in candidates:
        score = 0
        if candidate["stem_key"] and candidate["stem_key"] in label_key:
            score += 5
        score -= abs(len(candidate["stem_key"]) - len(normalize_token(record.get("model", ""))))
        if best_score is None or score > best_score:
            best_score = score
            best_path = candidate["relative_path"]
    return best_path


def refresh_index(index_path: Path, pdf_root: Path) -> dict[str, int]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    project_root = index_path.resolve().parents[2]
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError("pdf_library_index.json does not contain a records list")

    catalog = build_pdf_catalog(pdf_root, project_root=project_root)
    updated = 0
    unresolved = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        family = normalize_token(record.get("equipment_family", record.get("family", "")))
        manufacturer = manufacturer_key(record.get("manufacturer", ""))
        model = normalize_token(record.get("model", record.get("model_or_product_line", "")))
        candidates = list(catalog.get((family, manufacturer, model), []))
        if not candidates:
            # fallback for representative/brochure records that share a family + manufacturer bucket
            for (cand_family, cand_manufacturer, cand_model), values in catalog.items():
                if cand_family == family and cand_manufacturer == manufacturer and (cand_model.startswith(model) or model.startswith(cand_model) or model in cand_model or cand_model in model):
                    candidates.extend(values)
        chosen = choose_candidate(candidates, record)
        if chosen:
            record["path"] = chosen
            record["document_path"] = chosen
            updated += 1
        else:
            unresolved += 1
    payload["record_count"] = len(records)
    index_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"updated": updated, "unresolved": unresolved, "record_count": len(records)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate pdf_library_index.json paths from the canonical pdf library tree.")
    parser.add_argument("--index", default=str(INDEX_PATH))
    parser.add_argument("--pdf-root", default=str(PDF_ROOT))
    args = parser.parse_args()
    result = refresh_index(Path(args.index), Path(args.pdf_root))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
