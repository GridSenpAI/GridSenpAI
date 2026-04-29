from __future__ import annotations

import re
from pathlib import Path
from typing import Any


DOCUMENT_TYPE_RULES: dict[str, dict[str, Any]] = {
    "LARGE_LOAD_REQUEST_FORM": {
        "signals": [
            "large load request",
            "large load interconnection request",
            "load interconnection request",
            "project identification",
            "electrical characteristics",
            "primary contacts",
            "requested in-service",
            "requested in service",
            "nominal service voltage",
            "transmission provider",
            "applicant",
            "owner",
        ],
        "retrieval_domains": ["applicant", "poi_voltage", "load_schedule", "energization", "contacts"],
        "likely_fields": [
            "facility.project_name",
            "facility.poi_voltage_kv",
            "facility.energization.initial_energization_date",
            "facility.load_schedule.phase_1_mw",
        ],
        "document_role": "application_request_form",
        "document_family": "application",
        "worker_bias": ["table_worker", "retrieval_worker"],
    },
    "LOAD_SCHEDULE": {
        "signals": [
            "load schedule",
            "mw",
            "phase 1",
            "phase 2",
            "phase 3",
            "buildout",
            "expansion",
            "ramp",
        ],
        "retrieval_domains": ["load_schedule", "ramping"],
        "likely_fields": [
            "facility.load_schedule.phase_1_mw",
            "facility.load_schedule.phase_2_mw",
            "facility.load_schedule.phase_3_mw",
        ],
        "document_role": "load_schedule",
        "document_family": "schedule",
        "worker_bias": ["table_worker", "retrieval_worker"],
    },
    "PROJECT_SUMMARY_LOAD_SCHEDULE": {
        "signals": [
            "project summary",
            "load schedule",
            "campus load breakdown",
            "phased development summary",
            "phasing summary",
            "demand mw",
            "critical it load",
            "phase 1",
            "phase 2",
            "phase 3",
            "buildout",
            "ramp",
        ],
        "retrieval_domains": ["load_schedule", "ramping", "project_scope"],
        "likely_fields": [
            "facility.load_schedule.phase_1_mw",
            "facility.load_schedule.phase_2_mw",
            "facility.load_schedule.phase_3_mw",
            "facility.dynamic_behavior.max_ramp_up_mw_per_min",
        ],
        "document_role": "project_summary_load_schedule",
        "document_family": "schedule",
        "worker_bias": ["table_worker", "retrieval_worker"],
    },
    "EQUIPMENT_SCHEDULE": {
        "signals": [
            "major equipment schedule",
            "technical particulars",
            "equipment schedule",
            "planning item",
            "assumed value",
            "main power transformers",
            "standby generation platform",
            "ups platform",
            "campus quantity",
            "units total",
            "nameplate",
            "rating",
            "panel schedule",
            "ups schedule",
            "generator schedule",
            "switchgear schedule",
        ],
        "retrieval_domains": ["ups_topology", "generator", "transformer", "switchgear"],
        "likely_fields": [
            "facility.ups.count",
            "facility.generators.count",
            "facility.transformers.count",
            "facility.transformers.ratings_mva",
        ],
        "document_role": "equipment_schedule",
        "document_family": "schedule",
        "worker_bias": ["table_worker", "spec_worker"],
    },
    "ONE_LINE_DIAGRAM": {
        "signals": [
            "one-line diagram",
            "one line diagram",
            "single-line diagram",
            "single line diagram",
            "sld",
            "device 52",
            "device 89",
            "ct",
            "pt",
            "bus",
            "breaker",
            "transformer",
            "switchyard",
            "substation",
            "feeder",
            "relay",
            "poi",
            "point of interconnection",
        ],
        "retrieval_domains": ["poi_voltage", "topology", "transformer", "switchgear", "protection"],
        "likely_fields": [
            "facility.poi_voltage_kv",
            "facility.transformers.count",
            "facility.transformers.ratings_mva",
            "facility.substation.configuration",
        ],
        "document_role": "one_line",
        "document_family": "drawing",
        "worker_bias": ["drawing_worker"],
    },
    "CIVIL_ELECTRICAL_SITE_PLAN": {
        "signals": [
            "site plan",
            "civil electrical site plan",
            "parcel exhibit",
            "site control",
            "property boundary",
            "easement",
            "laydown",
            "access road",
            "fence line",
            "yard location",
            "substation pad",
        ],
        "retrieval_domains": ["site_control", "location", "topology"],
        "likely_fields": ["facility.site_control.present", "facility.location", "facility.substation.configuration"],
        "document_role": "site_plan",
        "document_family": "drawing",
        "worker_bias": ["drawing_worker", "retrieval_worker"],
    },
    "PROTECTION_CONTROLS": {
        "signals": [
            "protection and controls",
            "protection controls",
            "relay application",
            "sel relay",
            "sel relays",
            "relay settings",
            "50/51",
            "50bf",
            "51n",
            "21",
            "67",
            "87t",
            "transfer trip",
            "protection communications",
            "breaker failure",
        ],
        "retrieval_domains": ["protection", "relay_settings", "communications"],
        "likely_fields": ["facility.protection.present", "facility.relay_settings"],
        "document_role": "protection_controls",
        "document_family": "protection",
        "worker_bias": ["table_worker", "drawing_worker", "retrieval_worker"],
    },
    "METERING_SCADA_TELEMETRY": {
        "signals": [
            "metering scada",
            "scada telemetry",
            "metering and telemetry",
            "revenue meter",
            "rtu",
            "gateway",
            "telemetry",
            "scada point list",
            "control center",
            "revenue metering",
            "metering cabinet",
        ],
        "retrieval_domains": ["metering", "scada", "telemetry"],
        "likely_fields": ["facility.metering.present", "facility.scada.present"],
        "document_role": "metering_scada",
        "document_family": "controls",
        "worker_bias": ["table_worker", "retrieval_worker"],
    },
    "PHASING_ENERGIZATION_PLAN": {
        "signals": [
            "construction phasing",
            "energization plan",
            "energization basis",
            "target date",
            "commissioning deliverables",
            "milestone",
            "backfeed",
            "initial energization",
            "commercial operation",
            "in-service date",
            "in service date",
        ],
        "retrieval_domains": ["energization", "phasing", "ramping"],
        "likely_fields": [
            "facility.energization.initial_energization_date",
            "facility.load_schedule.phase_1_mw",
        ],
        "document_role": "phasing_energization_plan",
        "document_family": "schedule",
        "worker_bias": ["table_worker", "retrieval_worker"],
    },
    "FACILITIES_INTERCONNECTION_MEMO": {
        "signals": [
            "facilities study",
            "facilities memorandum",
            "interconnection memorandum",
            "point of interconnection",
            "customer interconnection facilities",
            "transmission owner",
            "to review",
            "tp review",
            "network upgrades",
            "interconnection facilities",
        ],
        "retrieval_domains": ["poi_voltage", "interconnection", "topology", "network_upgrades"],
        "likely_fields": [
            "facility.poi_voltage_kv",
            "facility.substation.configuration",
            "facility.interconnection_facilities.summary",
        ],
        "document_role": "facilities_interconnection_memo",
        "document_family": "interconnection_study",
        "worker_bias": ["retrieval_worker", "table_worker"],
    },
    "TRANSMITTAL_COVER_LETTER": {
        "signals": [
            "transmittal",
            "cover letter",
            "submitted to",
            "enclosed",
            "application package",
            "project contact",
            "subject:",
        ],
        "retrieval_domains": ["project_scope", "contacts"],
        "likely_fields": ["facility.project_name", "facility.applicant.name"],
        "document_role": "transmittal_cover_letter",
        "document_family": "administrative",
        "worker_bias": ["retrieval_worker"],
    },
    "UPS_SPECIFICATION": {
        "signals": [
            "ups",
            "uninterruptible power supply",
            "double conversion",
            "battery",
            "bypass",
            "static switch",
            "rectifier",
            "inverter",
        ],
        "retrieval_domains": ["ups_topology", "zip_behavior"],
        "likely_fields": ["facility.ups.topology", "facility.ups.count"],
        "document_role": "spec_sheet",
        "document_family": "specification",
        "worker_bias": ["spec_worker", "retrieval_worker"],
    },
    "GENERATOR_SPECIFICATION": {
        "signals": [
            "generator",
            "genset",
            "standby generator",
            "diesel",
            "engine generator",
        ],
        "retrieval_domains": ["generator"],
        "likely_fields": ["facility.generators.present", "facility.generators.count"],
        "document_role": "spec_sheet",
        "document_family": "specification",
        "worker_bias": ["spec_worker", "retrieval_worker"],
    },
}

ROLE_TO_WORKER_BIAS: dict[str, list[str]] = {
    "application_request_form": ["table_worker", "retrieval_worker"],
    "project_summary_load_schedule": ["table_worker", "retrieval_worker"],
    "one_line": ["drawing_worker"],
    "riser": ["drawing_worker"],
    "site_plan": ["drawing_worker", "retrieval_worker"],
    "equipment_schedule": ["table_worker", "spec_worker"],
    "load_schedule": ["table_worker", "retrieval_worker"],
    "spec_sheet": ["spec_worker", "retrieval_worker"],
    "cutsheet": ["spec_worker", "retrieval_worker"],
    "utility_document": ["retrieval_worker", "spec_worker"],
    "protection_diagram": ["table_worker", "drawing_worker", "retrieval_worker"],
    "protection_controls": ["table_worker", "drawing_worker", "retrieval_worker"],
    "metering_scada": ["table_worker", "retrieval_worker"],
    "phasing_energization_plan": ["table_worker", "retrieval_worker"],
    "facilities_interconnection_memo": ["retrieval_worker", "table_worker"],
    "transmittal_cover_letter": ["retrieval_worker"],
    "narrative": ["retrieval_worker"],
    "unclassified": [],
}

_ROLE_SOURCE_AUTHORITY: dict[str, str] = {
    "application_request_form": "applicant_direct_document",
    "project_summary_load_schedule": "applicant_direct_document",
    "equipment_schedule": "applicant_direct_document",
    "phasing_energization_plan": "applicant_direct_document",
    "facilities_interconnection_memo": "official_interconnection_source",
    "one_line": "applicant_direct_drawing",
    "site_plan": "applicant_direct_drawing",
    "protection_controls": "applicant_direct_engineering_document",
    "metering_scada": "applicant_direct_engineering_document",
    "transmittal_cover_letter": "applicant_direct_document",
    "spec_sheet": "manufacturer_family_spec",
}


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def classify_confidence(score: int) -> str:
    if score >= 9:
        return "HIGH"
    if score >= 3:
        return "MODERATE"
    return "LOW"


def build_text_for_classification(artifact: dict[str, Any], text_content: str | None = None) -> str:
    parts = [
        str(artifact.get("file_name", "")),
        str(artifact.get("classification", "")),
        str(artifact.get("artifact_type", "")),
        str(artifact.get("document_role", "")),
        str(artifact.get("document_family", "")),
        str(artifact.get("file_suffix", "")),
    ]
    if text_content:
        parts.append(text_content[:12000])
    return normalize_text(" ".join(parts))


def artifact_suffix(artifact: dict[str, Any]) -> str:
    suffix = str(artifact.get("file_suffix", "")).strip()
    if suffix:
        return suffix.lower()
    file_name = str(artifact.get("file_name", "")).strip()
    return Path(file_name).suffix.lower()


def unique_str_list(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)

    return ordered


def worker_bias_for_rule(rule: dict[str, Any] | None) -> list[str]:
    if not isinstance(rule, dict):
        return []
    configured = rule.get("worker_bias", [])
    if isinstance(configured, list) and configured:
        return unique_str_list(configured)
    role = str(rule.get("document_role", "unclassified")).strip().lower() or "unclassified"
    return list(ROLE_TO_WORKER_BIAS.get(role, []))


def source_authority_for_role(document_role: str) -> str:
    role = str(document_role or "").strip().lower()
    return _ROLE_SOURCE_AUTHORITY.get(role, "applicant_inferred_document")


def _phrase_match_score(phrase: str, text: str, file_text: str) -> int:
    normalized = normalize_text(phrase)
    if not normalized:
        return 0
    score = 0
    if normalized in text:
        score += 2
        if " " in normalized or "/" in normalized or "-" in normalized:
            score += 2
    if normalized in file_text:
        score += 3
        if " " in normalized or "/" in normalized or "-" in normalized:
            score += 2
    return score


def score_document_rule(*, rule: dict[str, Any], classification_text: str, file_text: str) -> tuple[int, list[str]]:
    signals = rule.get("signals", [])
    if not isinstance(signals, list):
        return 0, []

    score = 0
    matched: list[str] = []
    for signal in signals:
        signal_text = str(signal).strip()
        signal_score = _phrase_match_score(signal_text, classification_text, file_text)
        if signal_score <= 0:
            continue
        score += signal_score
        matched.append(signal_text)

    # Prevent broad single-token engineering words from overpowering a more specific role.
    if matched and all(" " not in item and "/" not in item and "-" not in item for item in matched):
        score = max(1, score - 2)

    return score, unique_str_list(matched)
