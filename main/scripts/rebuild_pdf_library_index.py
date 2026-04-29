#!/usr/bin/env python
from __future__ import annotations
import argparse, json, os, re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MANUFACTURER_ALIASES = {
    'mtu rolls royce': 'mtu_rolls_royce',
    'mtu': 'mtu_rolls_royce',
    'rolls royce': 'mtu_rolls_royce',
    'rolls-royce': 'mtu_rolls_royce',
    'mitsubishi': 'mitsubishi_electric',
    'schneider': 'schneider_electric',
}
DISPLAY_MANUFACTURER = {
    'mtu_rolls_royce': 'mtu rolls royce',
    'mitsubishi_electric': 'mitsubishi electric',
    'schneider_electric': 'schneider electric',
}


def norm(value: Any) -> str:
    text = '' if value is None else str(value)
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text


def canonical_manufacturer(value: Any) -> str:
    token = norm(value)
    return MANUFACTURER_ALIASES.get(token, token)


def load_index(index_path: Path) -> dict[str, Any]:
    with index_path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def scan_pdfs(pdf_root: Path) -> list[dict[str, str]]:
    pdfs: list[dict[str, str]] = []
    for pdf in sorted(pdf_root.rglob('*.pdf')):
        rel = pdf.relative_to(pdf_root.parent).as_posix()
        parts = rel.split('/')
        if len(parts) < 5:
            continue
        pdfs.append({
            'rel': rel,
            'family': parts[1],
            'manufacturer': parts[2],
            'model': parts[3],
            'filename': parts[-1],
        })
    return pdfs


def choose_best(record: dict[str, Any], candidates: list[dict[str, str]]) -> dict[str, str] | None:
    if not candidates:
        return None
    model_aliases = [norm(record.get('model'))] + [norm(x) for x in (record.get('model_aliases') or [])]
    model_aliases = [x for x in model_aliases if x]

    def score(pdf: dict[str, str]) -> tuple[float, str]:
        filename = pdf['filename']
        text = norm(filename + ' ' + pdf['model'])
        score_value = 0.0
        if pdf['model'] in model_aliases:
            score_value += 50
        if 'spec_main' in filename:
            score_value += 40
        if 'spec_alt_1' in filename:
            score_value += 30
        if 'brochure' in text:
            score_value += 10
        if 'guide' in text:
            score_value += 8
        if 'manual' in text:
            score_value += 5
        if record.get('document_type') == 'vendor_pdf_pointer' and ('spec_main' in filename or 'brochure' in text):
            score_value += 5
        score_value -= len(filename) / 1000.0
        return (-score_value, filename)

    return sorted(candidates, key=score)[0]


def refresh_index(knowledge_root: Path, write: bool = False) -> dict[str, Any]:
    vendor_root = knowledge_root / 'vendor_documents'
    pdf_root = vendor_root / 'pdf_library'
    index_path = vendor_root / 'pdf_library_index.json'
    index = load_index(index_path)
    records = list(index.get('records', []))
    all_pdfs = scan_pdfs(pdf_root)

    by_fam_man: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_fam_man_model: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    pdf_set = set()
    for pdf in all_pdfs:
        pdf_set.add(pdf['rel'])
        by_fam_man[(pdf['family'], pdf['manufacturer'])].append(pdf)
        by_fam_man_model[(pdf['family'], pdf['manufacturer'], pdf['model'])].append(pdf)

    used_paths: set[str] = set()
    for record in records:
        raw_path = (record.get('document_path') or record.get('path') or '').replace('\\', '/')
        if raw_path.startswith('knowledge/vendor_documents/'):
            raw_path = raw_path[len('knowledge/vendor_documents/'):]
        if raw_path in pdf_set:
            record['document_path'] = raw_path
            used_paths.add(raw_path)
            continue

        family = norm(record.get('equipment_family'))
        manufacturer = canonical_manufacturer(record.get('manufacturer'))
        manufacturer_aliases = [manufacturer] + [canonical_manufacturer(x) for x in (record.get('manufacturer_aliases') or [])]
        manufacturer_aliases = [x for x in dict.fromkeys(manufacturer_aliases) if x]
        model_aliases = [norm(record.get('model'))] + [norm(x) for x in (record.get('model_aliases') or [])]
        model_aliases = [x for x in dict.fromkeys(model_aliases) if x]

        if norm(record.get('manufacturer')) == 'switchgear':
            manufacturer_aliases = [canonical_manufacturer(record.get('model'))] + manufacturer_aliases
            manufacturer_aliases = [x for x in dict.fromkeys(manufacturer_aliases) if x]
            model_aliases = []

        candidates: list[dict[str, str]] = []
        seen: set[str] = set()
        for manufacturer_alias in manufacturer_aliases:
            for model_alias in model_aliases:
                for pdf in by_fam_man_model.get((family, manufacturer_alias, model_alias), []):
                    if pdf['rel'] not in seen:
                        candidates.append(pdf)
                        seen.add(pdf['rel'])
            for pdf in by_fam_man.get((family, manufacturer_alias), []):
                text = norm(pdf['filename'] + ' ' + pdf['model'])
                if any(model_alias and (model_alias in text or text in model_alias) for model_alias in model_aliases):
                    if pdf['rel'] not in seen:
                        candidates.append(pdf)
                        seen.add(pdf['rel'])

        if not candidates and record.get('document_type') == 'vendor_pdf_pointer':
            for manufacturer_alias in manufacturer_aliases:
                for pdf in by_fam_man.get((family, manufacturer_alias), []):
                    if pdf['rel'] not in seen:
                        candidates.append(pdf)
                        seen.add(pdf['rel'])

        best = choose_best(record, candidates)
        record['document_path'] = best['rel'] if best else ''
        if best:
            used_paths.add(best['rel'])

    existing_keys = {
        (norm(r.get('equipment_family')), canonical_manufacturer(r.get('manufacturer')), norm(r.get('model')), (r.get('document_path') or '').replace('\\', '/'))
        for r in records
    }
    for pdf in all_pdfs:
        if pdf['rel'] in used_paths:
            continue
        key = (pdf['family'], pdf['manufacturer'], pdf['model'], pdf['rel'])
        if key in existing_keys:
            continue
        display_manufacturer = DISPLAY_MANUFACTURER.get(pdf['manufacturer'], pdf['manufacturer'])
        records.append({
            'equipment_family': pdf['family'],
            'manufacturer': display_manufacturer,
            'model': pdf['model'],
            'document_type': 'vendor_pdf',
            'source_url': '',
            'path': pdf['rel'],
            'document_path': pdf['rel'],
            'retrieval_priority': 'secondary',
            'manufacturer_aliases': [display_manufacturer, pdf['manufacturer']],
            'model_aliases': [pdf['model']],
            'document_label': Path(pdf['filename']).stem.replace('_', ' '),
            'document_keywords': [pdf['family'], display_manufacturer, pdf['model'], Path(pdf['filename']).stem],
            'source_domain': '',
            'source_kind': 'vendor_pdf_library',
            'evidence_tier': 'secondary',
            'trust_level': 'medium',
        })
        used_paths.add(pdf['rel'])

    index['records'] = records
    index['record_count'] = len(records)

    missing = 0
    resolved_paths = []
    for record in records:
        path = (record.get('document_path') or '').replace('\\', '/')
        if path in pdf_set:
            resolved_paths.append(path)
        else:
            missing += 1

    counter = Counter(resolved_paths)
    summary = {
        'record_count': len(records),
        'pdf_count': len(all_pdfs),
        'resolved_record_count': len(resolved_paths),
        'missing_record_count': missing,
        'unique_referenced_pdf_count': len(counter),
        'duplicate_referenced_pdf_count': sum(1 for value in counter.values() if value > 1),
        'unreferenced_pdf_count': len(pdf_set - set(counter)),
    }

    if write:
        with index_path.open('w', encoding='utf-8') as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False)
        audit_path = vendor_root / 'pdf_library_alignment_audit.json'
        with audit_path.open('w', encoding='utf-8') as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Refresh pdf_library_index.json against the canonical vendor PDF tree.')
    parser.add_argument('--knowledge-root', default='knowledge', help='Path to knowledge root directory.')
    parser.add_argument('--write', action='store_true', help='Write refreshed index and audit summary back to disk.')
    args = parser.parse_args()
    summary = refresh_index(Path(args.knowledge_root), write=args.write)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
