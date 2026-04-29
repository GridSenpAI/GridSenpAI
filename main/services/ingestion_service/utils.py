from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any, Iterable

from shared.schemas.domain_registry import load_planner_document_specs


SUPPORTED_SUFFIXES: set[str] = {
    ".pdf",
    ".doc",
    ".docx",
    ".txt",
    ".json",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
}


CLASSIFICATION_RULES: list[tuple[str, set[str], list[str]]] = [
    (
        "poi_interconnection_documentation",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "interconnection study report",
            "interconnection study",
            "interconnection facilities report",
            "interconnection documentation",
            "poi documentation",
            "point of interconnection",
        ],
    ),
    (
        "large_load_request_form",
        {".pdf", ".doc", ".docx", ".txt", ".json"},
        [
            "large load request",
            "large-load request",
            "interconnection request",
            "load request form",
            "application request",
            "service request form",
            "facility intake",
        ],
    ),
    (
        "construction_phasing_plan",
        {".pdf", ".doc", ".docx", ".txt", ".csv"},
        [
            "construction phasing",
            "phasing plan",
            "energization schedule",
            "energization plan",
            "energization",
            "milestone schedule",
            "construction schedule",
            "load commissioning plan",
            "commissioning plan",
            "backfeed plan",
            "phased energization",
            "phase plan",
            "phasing",
            "buildout plan",
        ],
    ),
    (
        "metering_scada_telemetry",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "metering",
            "scada",
            "telemetry",
            "nomcr",
            "revenue meter",
            "rtu",
        ],
    ),
    (
        "protection_controls",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "protection controls",
            "protection and controls",
            "relay settings",
            "control settings",
            "protection package",
        ],
    ),
    (
        "facilities_study_memo",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "facilities study",
            "facility study",
            "study memo",
            "interconnection study",
        ],
    ),
    (
        "project_summary_load_schedule",
        {".pdf", ".doc", ".docx", ".txt", ".csv"},
        [
            "project summary",
            "load summary",
            "load ramp",
            "demand schedule",
            "load buildout",
            "capacity schedule",
        ],
    ),
    (
        "site_control_package",
        {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".txt"},
        [
            "site control",
            "parcel exhibit",
            "ownership exhibit",
            "land control",
            "lease exhibit",
            "property boundary",
            "parcel",
            "easement",
        ],
    ),
    (
        "site_civil_plan",
        {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".txt"},
        [
            "civil plan",
            "civil electrical site plan",
            "electrical site plan",
            "site civil",
            "grading plan",
            "site exhibit",
            "location map",
            "vicinity map",
            "parcel map",
            "electrical site plan",
            "civil electrical site plan",
            "site plan",
            "site layout",
        ],
    ),
    (
        "one_line_diagram",
        {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".txt"},
        [
            "one-line",
            "oneline",
            "single line",
            "single-line",
            "interconnection single-line",
            "sld",
        ],
    ),
    (
        "equipment_schedule",
        {".pdf", ".docx", ".csv", ".txt"},
        [
            "equipment schedule",
            "schedule",
            "equipment list",
            "load schedule",
            "motor schedule",
        ],
    ),
    (
        "ups_documentation",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "ups",
            "battery",
            "bms",
            "static switch",
            "ups technical package",
        ],
    ),
    (
        "generator_specification",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "generator",
            "genset",
            "gen-set",
            "engine generator",
            "backup power",
        ],
    ),
    (
        "protection_summary",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "protection",
            "relay",
            "trip curve",
            "uv",
            "uf",
            "ov",
            "of",
            "settings",
            "controls package",
        ],
    ),
    (
        "commissioning_notes",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "commissioning",
            "startup",
            "energization",
            "operations",
            "ops note",
            "procedure",
            "load commissioning plan",
        ],
    ),
    (
        "cooling_documentation",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "cooling",
            "hvac",
            "chiller",
            "crac",
            "crah",
            "cooling plant",
            "motor schedule",
        ],
    ),
    (
        "poi_interconnection_documentation",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "poi",
            "point of interconnection",
            "interconnection",
            "substation",
            "switchyard",
            "telemetry",
            "metering",
            "operations model",
            "nomcr",
        ],
    ),
    (
        "load_information_form",
        {".pdf", ".doc", ".docx", ".txt", ".json"},
        [
            "lif",
            "load information form",
            "ercot load information form",
            "utility load information form",
            "iso load information form",
        ],
    ),
    (
        "load_study",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "load study",
            "demand forecast",
            "electrical load study",
            "load forecast",
        ],
    ),
    (
        "site_plan",
        {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".txt"},
        [
            "site plan",
            "plot plan",
            "site layout",
            "layout drawing",
            "location map",
        ],
    ),
    (
        "transformer_datasheet",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "transformer datasheet",
            "transformer data",
            "transformer factory test",
            "saturation report",
        ],
    ),
    (
        "reactive_harmonic_package",
        {".pdf", ".doc", ".docx", ".txt"},
        [
            "reactive compensation",
            "harmonic mitigation",
            "statcom",
            "svc",
            "filter",
            "capacitor",
            "reactor",
        ],
    ),
]


DOCUMENT_NAME_TO_REQUIREMENT_ID: dict[str, str] = {
    "Completed utility/ISO load information form": "completed_utility_iso_load_information_form",
    "Site Location and POI Selection Package": "site_location_and_poi_selection_package",
    "Customer One-Line Diagram / Interconnection Single-Line Diagram": "customer_one_line_diagram_interconnection_single_line_diagram",
    "Electrical Load Study and Demand Forecast": "electrical_load_study_and_demand_forecast",
    "Transformer Datasheets": "transformer_datasheets",
    "Transformer Factory Test / Saturation Report": "transformer_factory_test_saturation_report",
    "Reactive Compensation and Harmonic Mitigation Package": "reactive_compensation_and_harmonic_mitigation_package",
    "UPS Technical Package": "ups_technical_package",
    "Cooling System and Motor Schedule": "cooling_system_and_motor_schedule",
    "PSS/E Network and Dynamic Model Package": "psse_network_and_dynamic_model_package",
    "PSCAD / Detailed Electromagnetic Model Package": "pscad_detailed_electromagnetic_model_package",
    "Power Supply / Large Electronic Load Technical Package": "power_supply_large_electronic_load_technical_package",
    "Backup Power and Operating Sequence Package": "backup_power_and_operating_sequence_package",
    "Protection and Controls Package": "protection_and_controls_package",
    "Telemetry, NOMCR, and Operations Model Package": "telemetry_nomcr_and_operations_model_package",
    "Standalone Large Load Energization Request Package": "standalone_large_load_energization_request_package",
}

DOCUMENT_NAME_TO_CLASSIFICATIONS: dict[str, list[str]] = {
    "Completed utility/ISO load information form": ["load_information_form", "large_load_request_form"],
    "Site Location and POI Selection Package": ["site_plan", "site_civil_plan", "site_control_package", "poi_interconnection_documentation"],
    "Customer One-Line Diagram / Interconnection Single-Line Diagram": ["one_line_diagram"],
    "Electrical Load Study and Demand Forecast": ["load_study", "project_summary_load_schedule", "equipment_schedule"],
    "Transformer Datasheets": ["transformer_datasheet", "equipment_schedule"],
    "Transformer Factory Test / Saturation Report": ["transformer_datasheet"],
    "Reactive Compensation and Harmonic Mitigation Package": ["reactive_harmonic_package"],
    "UPS Technical Package": ["ups_documentation"],
    "Cooling System and Motor Schedule": ["cooling_documentation", "equipment_schedule"],
    "PSS/E Network and Dynamic Model Package": ["poi_interconnection_documentation"],
    "PSCAD / Detailed Electromagnetic Model Package": ["poi_interconnection_documentation"],
    "Power Supply / Large Electronic Load Technical Package": ["ups_documentation"],
    "Backup Power and Operating Sequence Package": ["generator_specification", "commissioning_notes"],
    "Protection and Controls Package": ["protection_summary", "protection_controls"],
    "Telemetry, NOMCR, and Operations Model Package": ["poi_interconnection_documentation", "metering_scada_telemetry"],
    "Standalone Large Load Energization Request Package": ["poi_interconnection_documentation", "large_load_request_form", "construction_phasing_plan", "commissioning_notes"],
}


CLASSIFICATION_REQUIREMENT_FALLBACKS: dict[str, list[str]] = {
    "site_control_package": ["site_location_and_poi_selection_package"],
    "site_civil_plan": ["site_location_and_poi_selection_package"],
    "site_plan": ["site_location_and_poi_selection_package"],
    "construction_phasing_plan": ["standalone_large_load_energization_request_package"],
    "commissioning_notes": ["standalone_large_load_energization_request_package", "backup_power_and_operating_sequence_package"],
}

FILENAME_REQUIREMENT_ALIASES: list[tuple[tuple[str, ...], list[str], str]] = [
    (("site", "control"), ["site_location_and_poi_selection_package"], "site_control_package"),
    (("parcel", "exhibit"), ["site_location_and_poi_selection_package"], "site_control_package"),
    (("civil", "electrical", "site", "plan"), ["site_location_and_poi_selection_package"], "site_civil_plan"),
    (("electrical", "site", "plan"), ["site_location_and_poi_selection_package"], "site_civil_plan"),
    (("location", "map"), ["site_location_and_poi_selection_package"], "site_plan"),
    (("site", "plan"), ["site_location_and_poi_selection_package"], "site_plan"),
    (("construction", "phasing"), ["standalone_large_load_energization_request_package"], "construction_phasing_plan"),
    (("energization", "plan"), ["standalone_large_load_energization_request_package"], "construction_phasing_plan"),
    (("commissioning", "plan"), ["standalone_large_load_energization_request_package", "backup_power_and_operating_sequence_package"], "commissioning_notes"),
]


def is_supported_artifact(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES


def iter_supported_artifacts(input_dir: Path) -> Iterable[Path]:
    for path in sorted(input_dir.rglob("*")):
        if is_supported_artifact(path):
            yield path


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    sha256 = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def guess_mime_type(file_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return mime_type or "application/octet-stream"


def _filename_alias_matches(file_path: Path) -> tuple[str, list[str]]:
    raw_name = file_path.name.lower()
    normalized_name = re.sub(r"[^a-z0-9]+", " ", raw_name).strip()
    tokens = set(normalized_name.split())
    for required_tokens, requirement_ids, classification in FILENAME_REQUIREMENT_ALIASES:
        if all(token in tokens or token in normalized_name for token in required_tokens):
            return classification, list(requirement_ids)
    return "", []


def classify_artifact(file_path: Path) -> str:
    raw_name = file_path.name.lower()
    normalized_name = re.sub(r"[_\-]+", " ", raw_name)
    suffix = file_path.suffix.lower()

    alias_classification, _ = _filename_alias_matches(file_path)
    if alias_classification:
        return alias_classification

    for classification, allowed_suffixes, keywords in CLASSIFICATION_RULES:
        if suffix not in allowed_suffixes:
            continue
        if any(keyword in raw_name or keyword in normalized_name for keyword in keywords):
            return classification

    return "unknown"


def derive_tags(classification: str, file_path: Path) -> list[str]:
    tags: list[str] = []

    if classification != "unknown":
        tags.append(classification)
        tags.append(f"source_role:{classification}")

    suffix = file_path.suffix.lower().lstrip(".")
    if suffix:
        tags.append(f"ext:{suffix}")

    return tags


def relative_to_root(file_path: Path, root_dir: Path) -> str:
    return str(file_path.relative_to(root_dir))


def build_artifact_id(index: int) -> str:
    return f"artifact_{index:03d}"


def estimate_page_count(file_path: Path) -> int | None:
    return None


def slugify_project_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "default_project"


def build_intake_session_id(project_id: str) -> str:
    return f"intake_{slugify_project_name(project_id)}"


def intake_sessions_root(project_root: Path) -> Path:
    return project_root / "runs" / "intake_sessions"


def intake_session_path(project_root: Path, project_id: str) -> Path:
    return intake_sessions_root(project_root) / f"{slugify_project_name(project_id)}_intake_session.json"


def _default_requirement_id(document_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", document_name.strip().lower()).strip("_")
    return normalized or "unnamed_requirement"


def _default_requirement_label(document_name: str) -> str:
    return document_name.strip() or "Unnamed Requirement"


def _default_requirement_description(document_name: str, used_for: tuple[str, ...]) -> str:
    if used_for:
        return f"Planner document used for: {', '.join(used_for)}."
    return f"Planner document requirement for {document_name}."


def _default_requirement_guidance(document_name: str, data_fields: tuple[str, ...]) -> str:
    if data_fields:
        return (
            f"Upload {document_name} if available. It should support fields such as: "
            f"{', '.join(data_fields[:8])}."
        )
    return f"Upload {document_name} if available for intake coverage."


def _is_required_stage(stage_name: str) -> bool:
    normalized = stage_name.strip().lower()
    return normalized.startswith("initial application") or normalized.startswith("initial engineering submittal")


def build_requirement_catalog() -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []

    for spec in load_planner_document_specs():
        requirement_id = DOCUMENT_NAME_TO_REQUIREMENT_ID.get(
            spec.document_name,
            _default_requirement_id(spec.document_name),
        )
        accepted_classifications = DOCUMENT_NAME_TO_CLASSIFICATIONS.get(spec.document_name, [])

        requirements.append(
            {
                "requirement_id": requirement_id,
                "label": _default_requirement_label(spec.document_name),
                "description": spec.description or _default_requirement_description(spec.document_name, spec.used_for),
                "guidance": _default_requirement_guidance(spec.document_name, spec.data_fields_provided),
                "required": _is_required_stage(spec.required_stage),
                "accepted_classifications": accepted_classifications,
                "document_name": spec.document_name,
                "used_for": list(spec.used_for),
                "study_tools": list(spec.study_tools),
                "data_fields_provided": list(spec.data_fields_provided),
                "required_stage": spec.required_stage,
            }
        )

    return requirements


def requirement_ids_for_file(file_path: Path, classification: str) -> list[str]:
    matches = requirement_ids_for_classification(classification)
    _, alias_requirement_ids = _filename_alias_matches(file_path)
    for requirement_id in alias_requirement_ids:
        if requirement_id not in matches:
            matches.append(requirement_id)
    return matches


def requirement_ids_for_classification(classification: str) -> list[str]:
    if not classification or classification == "unknown":
        return []

    matches: list[str] = []
    for requirement in build_requirement_catalog():
        accepted = requirement.get("accepted_classifications", [])
        if classification in accepted:
            matches.append(str(requirement["requirement_id"]))

    for requirement_id in CLASSIFICATION_REQUIREMENT_FALLBACKS.get(classification, []):
        if requirement_id not in matches:
            matches.append(requirement_id)

    return matches
