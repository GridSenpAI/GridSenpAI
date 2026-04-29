from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / 'knowledge'
PROJECT_ROOT = KNOWLEDGE_ROOT.parent

CANONICAL_KNOWLEDGE_FAMILIES: tuple[str, ...] = (
    'equipment_catalog',
    'vendor_documents',
    'modeling_references',
    'interconnection_guidance',
)

# Legacy corpus names are accepted only as compatibility aliases. Runtime routing
# should converge on the canonical family names above.
KNOWLEDGE_FAMILY_ALIASES: dict[str, str] = {
    'equipment_catalog': 'equipment_catalog',
    'equipment_references': 'equipment_catalog',
    'vendor_specs': 'equipment_catalog',
    'vendor_reference': 'equipment_catalog',
    'vendor_documents': 'vendor_documents',
    'modeling_references': 'modeling_references',
    'modeling_refs': 'modeling_references',
    'interconnection_guidance': 'interconnection_guidance',
}

# Canonical knowledge-family locations.
CANONICAL_CORPUS_SOURCE_DIRS: dict[str, tuple[str, ...]] = {
    'equipment_catalog': (
        'equipment_catalog',
    ),
    'vendor_documents': (
        'vendor_documents',
    ),
    'modeling_references': (
        'modeling_references',
    ),
    'interconnection_guidance': (
        'interconnection_guidance',
    ),
}

# Only the minimal legacy physical locations that still actively back canonical
# families remain here. Historical helper files stay on disk if needed, but they
# are no longer advertised as active corpus sources.
LEGACY_COMPATIBILITY_SOURCE_DIRS: dict[str, tuple[str, ...]] = {
    'equipment_catalog': (),
    'vendor_documents': (),
    'modeling_references': (),
    'interconnection_guidance': (),
}

# Legacy files that still exist on disk but are not treated as active corpus
# sources anymore. These are tracked only for audit / cleanup visibility.
LEGACY_AUDIT_ONLY_PATHS: tuple[str, ...] = (
    'vendor_reference/agent4_master_source_index.json',
    'vendor_reference/equipment_families_switchgear.json',
    'vendor_reference/equipment_families_transformers.json',
    'vendor_reference/equipment_families_ups.json',
    'vendor_reference/specification_fields_switchgear.json',
    'vendor_reference/specification_fields_transformers.json',
    'vendor_reference/specification_fields_ups.json',
    'vendor_reference/ups_behavior.txt',
)

# Canonical preferred route targets.
CANONICAL_ROUTE_CANDIDATES: dict[str, tuple[str, ...]] = {
    'equipment_catalog_index': (
        'equipment_catalog/catalog_index.json',
    ),
    'official_source_index': (
        'vendor_documents/official_source_index.json',
    ),
    'pdf_library_index': (
        'vendor_documents/pdf_library_index.json',
    ),
    'pdf_roots': (
        'vendor_documents/pdf_library',
        'vendor_documents/pdf_repository',
    ),
    'legacy_spec_roots': (),
}

# Legacy fallback route targets that still support the canonical routes today.
LEGACY_ROUTE_CANDIDATES: dict[str, tuple[str, ...]] = {
    'equipment_catalog_index': (),
    'official_source_index': (),
    'pdf_library_index': (),
    'pdf_roots': (),
    'legacy_spec_roots': (),
}


def canonical_knowledge_family(value: Any) -> str:
    normalized = str(value or '').strip()
    return KNOWLEDGE_FAMILY_ALIASES.get(normalized, normalized)


def canonical_family_route(values: list[str] | tuple[str, ...] | None) -> list[str]:
    route: list[str] = []
    for item in values or []:
        canonical = canonical_knowledge_family(item)
        if canonical in CANONICAL_KNOWLEDGE_FAMILIES and canonical not in route:
            route.append(canonical)
    return route


def preferred_corpora(values: list[str] | tuple[str, ...] | None) -> list[str]:
    route = canonical_family_route(values)
    if route:
        return route
    return list(CANONICAL_KNOWLEDGE_FAMILIES)


def _paths_from_relative_set(relative_paths: tuple[str, ...]) -> list[Path]:
    return [KNOWLEDGE_ROOT / relative for relative in relative_paths]


def corpus_source_paths(corpus_name: str, *, include_legacy: bool = True) -> list[Path]:
    canonical = canonical_knowledge_family(corpus_name)
    relative_paths: list[str] = list(CANONICAL_CORPUS_SOURCE_DIRS.get(canonical, ()))
    if include_legacy:
        for item in LEGACY_COMPATIBILITY_SOURCE_DIRS.get(canonical, ()): 
            if item not in relative_paths:
                relative_paths.append(item)
    return _paths_from_relative_set(tuple(relative_paths))


def runtime_corpus_source_paths(corpus_name: str) -> list[Path]:
    canonical = canonical_knowledge_family(corpus_name)
    canonical_paths = _paths_from_relative_set(CANONICAL_CORPUS_SOURCE_DIRS.get(canonical, ()))
    existing_canonical = [path for path in canonical_paths if path.exists()]
    if existing_canonical:
        return canonical_paths

    legacy_paths = _paths_from_relative_set(LEGACY_COMPATIBILITY_SOURCE_DIRS.get(canonical, ()))
    existing_legacy = [path for path in legacy_paths if path.exists()]
    if existing_legacy:
        return legacy_paths

    return canonical_paths or legacy_paths


def route_candidate_paths(route_name: str, *, include_legacy: bool = True) -> list[Path]:
    relative_paths: list[str] = list(CANONICAL_ROUTE_CANDIDATES.get(route_name, ()))
    if include_legacy:
        for item in LEGACY_ROUTE_CANDIDATES.get(route_name, ()): 
            if item not in relative_paths:
                relative_paths.append(item)
    return _paths_from_relative_set(tuple(relative_paths))


def _first_existing_path(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def preferred_route_path(route_name: str) -> Path:
    candidates = route_candidate_paths(route_name)
    existing = _first_existing_path(candidates)
    if existing is not None:
        return existing
    return candidates[0] if candidates else KNOWLEDGE_ROOT


def existing_route_paths(route_name: str) -> list[Path]:
    return [path for path in route_candidate_paths(route_name) if path.exists()]


def preferred_equipment_catalog_index() -> Path:
    return preferred_route_path('equipment_catalog_index')


def preferred_official_source_index() -> Path:
    return preferred_route_path('official_source_index')


def preferred_pdf_library_index() -> Path:
    return preferred_route_path('pdf_library_index')


def preferred_pdf_roots() -> list[Path]:
    existing = existing_route_paths('pdf_roots')
    return existing or route_candidate_paths('pdf_roots')


def legacy_spec_roots() -> list[Path]:
    existing = existing_route_paths('legacy_spec_roots')
    return existing or route_candidate_paths('legacy_spec_roots')


def resolve_knowledge_path(path_value: Any, *, extra_roots: Iterable[Path] | None = None) -> Path | None:
    normalized = str(path_value or '').strip()
    if not normalized:
        return None

    raw_path = Path(normalized)
    if raw_path.is_absolute() and raw_path.exists():
        return raw_path

    candidate_roots: list[Path] = [
        PROJECT_ROOT,
        KNOWLEDGE_ROOT.parent,
        KNOWLEDGE_ROOT,
    ]
    if extra_roots:
        for root in extra_roots:
            if root not in candidate_roots:
                candidate_roots.append(root)

    for root in candidate_roots:
        candidate = root / normalized
        if candidate.exists():
            return candidate

    return None


def _relative_display(path: Path) -> str:
    if path.is_relative_to(KNOWLEDGE_ROOT):
        return str(path.relative_to(KNOWLEDGE_ROOT))
    return str(path)


def active_legacy_compatibility() -> dict[str, Any]:
    corpora: dict[str, list[str]] = {}
    for corpus_name, relatives in LEGACY_COMPATIBILITY_SOURCE_DIRS.items():
        active = [str((KNOWLEDGE_ROOT / relative).relative_to(KNOWLEDGE_ROOT)) for relative in relatives if (KNOWLEDGE_ROOT / relative).exists()]
        if active:
            corpora[corpus_name] = active

    routes: dict[str, list[str]] = {}
    for route_name, relatives in LEGACY_ROUTE_CANDIDATES.items():
        active = [str((KNOWLEDGE_ROOT / relative).relative_to(KNOWLEDGE_ROOT)) for relative in relatives if (KNOWLEDGE_ROOT / relative).exists()]
        if active:
            routes[route_name] = active

    audit_only = [
        str((KNOWLEDGE_ROOT / relative).relative_to(KNOWLEDGE_ROOT))
        for relative in LEGACY_AUDIT_ONLY_PATHS
        if (KNOWLEDGE_ROOT / relative).exists()
    ]

    return {
        'corpora': corpora,
        'routes': routes,
        'audit_only': audit_only,
    }


def knowledge_route_status() -> dict[str, Any]:
    corpora: dict[str, Any] = {}
    for corpus_name in CANONICAL_KNOWLEDGE_FAMILIES:
        canonical_sources = _paths_from_relative_set(CANONICAL_CORPUS_SOURCE_DIRS.get(corpus_name, ()))
        legacy_sources = _paths_from_relative_set(LEGACY_COMPATIBILITY_SOURCE_DIRS.get(corpus_name, ()))
        all_sources = corpus_source_paths(corpus_name)
        existing = [_relative_display(path) for path in all_sources if path.exists()]
        missing = [_relative_display(path) for path in all_sources if not path.exists()]
        corpora[corpus_name] = {
            'source_paths': [_relative_display(path) for path in all_sources],
            'canonical_source_paths': [_relative_display(path) for path in canonical_sources],
            'legacy_source_paths': [_relative_display(path) for path in legacy_sources],
            'existing_source_paths': existing,
            'missing_source_paths': missing,
        }

    route_preferences: dict[str, Any] = {}
    for route_name in CANONICAL_ROUTE_CANDIDATES:
        canonical_candidates = _paths_from_relative_set(CANONICAL_ROUTE_CANDIDATES.get(route_name, ()))
        legacy_candidates = _paths_from_relative_set(LEGACY_ROUTE_CANDIDATES.get(route_name, ()))
        candidates = route_candidate_paths(route_name)
        preferred = preferred_route_path(route_name)
        route_preferences[route_name] = {
            'candidate_paths': [_relative_display(path) for path in candidates],
            'canonical_candidate_paths': [_relative_display(path) for path in canonical_candidates],
            'legacy_candidate_paths': [_relative_display(path) for path in legacy_candidates],
            'existing_paths': [_relative_display(path) for path in candidates if path.exists()],
            'preferred_path': _relative_display(preferred),
            'preferred_exists': preferred.exists(),
        }

    return {
        'canonical_families': list(CANONICAL_KNOWLEDGE_FAMILIES),
        'aliases': dict(KNOWLEDGE_FAMILY_ALIASES),
        'corpora': corpora,
        'route_preferences': route_preferences,
        'legacy_compatibility': active_legacy_compatibility(),
    }
