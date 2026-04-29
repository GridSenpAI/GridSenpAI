from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from shared.field_value_policies import (
    context_adjustment as field_context_adjustment,
    source_role_from_candidate,
)
from shared.planner_candidate_bridge import candidate_ledger_records_for_lookup_keys
from shared.planner_registry import (
    field_label,
    field_resolution_policy_for_family,
    field_resolution_scoring_profile,
    field_resolution_source_stream_profile,
    planner_packet_fields,
    planner_packet_section_label,
    planner_packet_sections,
    registry_field_id_for_path,
    registry_lookup_keys,
    resolve_registry_field,
)

from services.agent_runtime_service.service import run_agent
from services.agent_runtime_service.models import AgentRequest
from services.field_resolution_service.models import (
    FieldResolutionCandidate,
    FieldResolutionLedgerEntry,
)
from services.field_resolution_service.adjudication_packets import build_adjudication_packet_plan

SOURCE_PRIORITY: dict[str, int] = {
    "planner_candidate_ledger": 110,
    "planner_candidate_ledger_accepted_value": 115,
    "schema_field_candidate": 50,
    "normalized_input": 80,
    "interview_answer": 98,
    "engineer_interview": 98,
    "human_input": 98,
    "translation_output": 40,
    "calibration_dataset": 70,
    "equipment_reference_candidate": 65,
}

STAGE_PRIORITY: dict[str, int] = {
    "interview": 80,
    "normalization": 70,
    "validation": 60,
    "retrieval": 50,
    "extraction": 45,
    "translation": 35,
    "canonical_state": 30,
}

SOURCE_HIERARCHY_PRIORITY: dict[str, int] = {
    "applicant_direct_document": 120,
    "applicant_inferred_document": 105,
    "applicant_confirmed_answer": 112,
    "manufacturer_model_specific_spec": 95,
    "manufacturer_family_spec": 85,
    "official_interconnection_source": 80,
    "vendor_pdf": 70,
    "official_website": 60,
    "secondary_web": 40,
    "llm_uncited": 10,
}


SPECIFICITY_PRIORITY: dict[str, int] = {
    "exact_model_match": 40,
    "exact_instance_match": 38,
    "direct_field_match": 34,
    "family_match": 22,
    "category_match": 12,
    "context_inferred": 0,
}

EVIDENCE_PRIORITY: dict[str, int] = {
    "STRONG": 24,
    "MODERATE": 12,
    "WEAK": 2,
    "UNKNOWN": 0,
}

STATUS_SORT_ORDER: dict[str, int] = {
    "conflicting": 0,
    "review_required": 1,
    "missing": 2,
    "unresolved": 3,
    "resolved": 4,
}


_STATUS_SEVERITY: dict[str, int] = {
    "conflicting": 0,
    "review_required": 1,
    "missing": 2,
    "unresolved": 3,
    "resolved": 4,
}


def _more_restrictive_status(current_status: str, policy_status: str) -> str:
    current = str(current_status).strip().lower() or "unresolved"
    proposed = str(policy_status).strip().lower() or current
    return proposed if _STATUS_SEVERITY.get(proposed, 99) < _STATUS_SEVERITY.get(current, 99) else current


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canonical_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return tuple(_canonical_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _canonical_value(val)) for key, val in value.items()))
    return value


def _field_family(field_id: str, field_path: str, section_id: str) -> str:
    parts = [field_id.strip().lower(), field_path.strip().lower(), section_id.strip().lower()]
    blob = " ".join(parts)
    if "generator" in blob:
        return "generator"
    if "transformer" in blob:
        return "transformer"
    if "ups" in blob or "battery" in blob:
        return "ups"
    if "relay" in blob or "protection" in blob:
        return "relay"
    if any(token in blob for token in {"interconnection", "poi", "substation", "utility"}):
        return "interconnection"
    if any(token in blob for token in {"meter", "scada", "telemetry"}):
        return "metering"
    if "ramp" in blob:
        return "ramping"
    if any(token in blob for token in {"load", "motor", "cooling", "chiller"}):
        return "load"
    return section_id.strip().lower() or "general"


def _field_policy_profile(
    *,
    field_id: str,
    field_path: str,
    field_family: str,
    planner_critical: bool,
    requiredness: str,
) -> dict[str, Any]:
    field_id_norm = field_id.strip().lower()
    field_path_norm = field_path.strip().lower()
    family_norm = field_family.strip().lower()
    blob = " ".join([field_id_norm, field_path_norm, family_norm])
    required_norm = str(requiredness).strip().lower() or "optional"
    tokens = {token for token in re.split(r"[^a-z0-9]+", blob) if token}

    electrical_tokens = {
        "voltage", "kv", "kva", "kw", "mw", "amp", "amps", "impedance", "ratio", "tap", "frequency", "pf", "power", "factor",
    }
    topology_tokens = {
        "count", "quantity", "redundancy", "topology", "configuration", "breaker", "transfer", "bus", "collector", "tie", "scheme",
    }
    descriptive_tokens = {"manufacturer", "model", "name", "vendor", "description", "notes", "address", "county", "parish"}

    if tokens & topology_tokens:
        materiality_class = "topology_configuration"
    elif tokens & electrical_tokens:
        materiality_class = "electrical_numeric"
    elif tokens & descriptive_tokens:
        materiality_class = "descriptive_identity"
    else:
        materiality_class = "supporting_context"

    if planner_critical:
        field_class = "planner_critical"
    elif required_norm == "required" or family_norm in {"generator", "transformer", "ups", "relay", "interconnection", "metering", "load"}:
        field_class = "planner_relevant"
    else:
        field_class = "supporting"

    base_threshold = 0.80 if planner_critical else 0.62
    threshold_adjust = 0.0
    minimum_independent_sources = 1
    medium_conflict_blocks = False
    narrow_single_source_is_provisional = True

    if materiality_class == "electrical_numeric":
        threshold_adjust += 0.05 if planner_critical else 0.03
        minimum_independent_sources = 2 if planner_critical else 1
        medium_conflict_blocks = planner_critical
    elif materiality_class == "topology_configuration":
        threshold_adjust += 0.07 if planner_critical else 0.04
        minimum_independent_sources = 2 if field_class in {"planner_critical", "planner_relevant"} else 1
        medium_conflict_blocks = field_class in {"planner_critical", "planner_relevant"}
    elif materiality_class == "descriptive_identity":
        threshold_adjust -= 0.02
        narrow_single_source_is_provisional = planner_critical
    else:
        threshold_adjust += 0.02 if planner_critical else 0.0

    if required_norm == "required" and field_class != "supporting":
        threshold_adjust += 0.01

    confidence_threshold = min(0.95, max(0.50, base_threshold + threshold_adjust))
    return {
        "field_class": field_class,
        "materiality_class": materiality_class,
        "confidence_threshold": confidence_threshold,
        "minimum_independent_sources": minimum_independent_sources,
        "medium_conflict_blocks": medium_conflict_blocks,
        "narrow_single_source_is_provisional": narrow_single_source_is_provisional,
    }


def _infer_source_hierarchy(record: dict[str, Any], field_family: str) -> str:
    source_type = str(record.get("source_type", "")).strip().lower()
    source_stage = str(record.get("source_stage", "")).strip().lower()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_priority_hint = str(record.get("source_priority", metadata.get("source_priority", ""))).strip().lower()
    match_reason_hint = str(record.get("match_reason", metadata.get("match_reason", ""))).strip().lower()
    if any(token in f"{source_priority_hint} {match_reason_hint}" for token in {"exact_model", "model_specific", "exact model"}):
        return "manufacturer_model_specific_spec"
    if "family" in f"{source_priority_hint} {match_reason_hint}":
        return "manufacturer_family_spec"
    if source_priority_hint in {"vendor_documents", "vendor_document", "vendor_pdf"}:
        # A vendor PDF pointer without model/family specificity is contextual vendor evidence,
        # not a governed manufacturer-family specification.
        return "vendor_pdf"
    preferred_hierarchy = str(metadata.get("best_source_hierarchy", record.get("best_source_hierarchy", ""))).strip().lower()
    if preferred_hierarchy:
        return preferred_hierarchy
    source_method = str(metadata.get("source_method", "")).strip().lower()
    source_type_detail = str(metadata.get("source_type_detail", "")).strip().lower()
    source_lookup_strategy = str(metadata.get("source_lookup_strategy", "")).strip().lower()
    source_priority = str(metadata.get("source_priority", record.get("source_priority", ""))).strip().lower()
    source_kind = str(metadata.get("source_kind", record.get("source_kind", ""))).strip().lower()
    document_type = str(metadata.get("document_type", record.get("document_type", ""))).strip().lower()
    evidence_tier = str(metadata.get("evidence_tier", record.get("evidence_tier", ""))).strip().lower()
    preferred = " ".join(
        str(item).strip().lower() for item in (record.get("source_ref") or []) if str(item).strip()
    )
    blob = " ".join([source_type, source_stage, source_method, source_type_detail, source_lookup_strategy, source_priority, source_kind, document_type, evidence_tier, preferred])

    if source_type in {"interview_answer", "engineer_interview", "human_input"} or source_stage == "interview":
        return "applicant_confirmed_answer"
    if source_type == "schema_field_candidate":
        return "applicant_direct_document"
    if source_type == "normalized_input":
        return "applicant_inferred_document"
    if any(token in blob for token in {"manufacturer_model_specific_spec", "exact_model", "model_specific", "datasheet", "exact model"}):
        return "manufacturer_model_specific_spec"
    if any(token in blob for token in {"manufacturer", "product line", "family"}):
        return "manufacturer_family_spec"
    if any(token in blob for token in {"utility", "iso", "ercot", "interconnection", "planning guide", "nprr"}):
        return "official_interconnection_source"
    if any(token in blob for token in {"vendor", "spec_sheet", "catalog", "brochure", "pdf", "repository"}):
        return "vendor_pdf"
    if any(token in blob for token in {"website", "web", "html"}):
        return "official_website"
    if any(token in blob for token in {"forum", "blog", "secondary"}):
        return "secondary_web"
    if "llm" in blob:
        return "llm_uncited"
    return "applicant_inferred_document"


def _infer_source_stream(record: dict[str, Any]) -> str:
    source_stage = str(record.get("source_stage", "")).strip().lower()
    source_type = str(record.get("source_type", "")).strip().lower()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    detail = " ".join(
        str(metadata.get(key, "")).strip().lower()
        for key in ("source_type_detail", "source_method", "lookup_strategy", "source_kind", "document_type")
    )
    blob = " ".join([source_stage, source_type, detail])
    if source_stage == "extraction" or source_type == "schema_field_candidate":
        return "ocr_extraction"
    if source_stage == "interview" or source_type in {"interview_answer", "engineer_interview", "human_input"}:
        return "applicant_interview"
    if any(token in blob for token in {"vendor_pdf", "pdf_repository", "vendor_document"}):
        return "vendor_pdf"
    if any(token in blob for token in {"official_web", "official_source", "ercot", "iso", "utility"}):
        return "official_web"
    if any(token in blob for token in {"knowledge_library", "equipment_catalog", "catalog_match", "library"}):
        return "knowledge_library"
    if source_stage == "normalization":
        return "normalized_record"
    return "record"


def _infer_specificity(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    record_specificity_hint = " ".join(str(record.get(key, metadata.get(key, ""))).strip().lower() for key in ("specificity", "source_specificity", "equipment_match_type", "match_specificity", "match_reason", "source_priority"))
    if "exact_model" in record_specificity_hint or "exact model" in record_specificity_hint or "model_specific" in record_specificity_hint or "manufacturer+model" in record_specificity_hint:
        return "exact_model_match"
    if "exact_instance" in record_specificity_hint or "instance" in record_specificity_hint:
        return "exact_instance_match"
    if "family" in record_specificity_hint:
        return "family_match"
    preferred_specificity = str(metadata.get("best_specificity", record.get("best_specificity", ""))).strip().lower()
    if preferred_specificity:
        return preferred_specificity
    for key in ("specificity", "source_specificity", "equipment_match_type", "match_specificity", "match_reason", "source_priority"):
        value = str(metadata.get(key, record.get(key, ""))).strip().lower()
        if not value:
            continue
        if "exact_model" in value or "exact model" in value or "manufacturer+model" in value:
            return "exact_model_match"
        if "exact_instance" in value or "instance" in value:
            return "exact_instance_match"
        if "direct" in value or "canonical_field" in value:
            return "direct_field_match"
        if "family" in value:
            return "family_match"
        if "category" in value:
            return "category_match"
    if (str(metadata.get("model", record.get("model", ""))).strip() and str(metadata.get("manufacturer", record.get("manufacturer", ""))).strip()):
        return "exact_model_match"
    source_method = str(metadata.get("source_method", "")).strip().lower()
    if "title_block" in source_method or "table" in source_method or "deterministic" in source_method:
        return "direct_field_match"
    return "context_inferred"


def _anchor_from_record(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    page_number = metadata.get("page_number")
    section_label = str(metadata.get("section_label", "")).strip()
    artifact = str(metadata.get("artifact_name", "")).strip() or str(metadata.get("artifact_type", "")).strip()
    bits = [bit for bit in [artifact, f"page {page_number}" if isinstance(page_number, int) else "", section_label] if bit]
    if bits:
        return " / ".join(bits)
    refs = record.get("source_ref")
    if isinstance(refs, list) and refs:
        return str(refs[0]).strip()
    return ""


def _confidence_band(score: float | None, status: str | None = None) -> str:
    if status in {"missing", "unresolved"}:
        return "UNRESOLVED"
    if status == "conflicting":
        return "LOW"
    if score is None:
        return "LOW"
    if score >= 0.85:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    return "LOW"


def _build_family_identity_context(canonical_state: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    field_records = canonical_state.get("field_records")
    if not isinstance(field_records, list):
        return {}
    context: dict[str, dict[str, set[str]]] = {}
    for record in field_records:
        if not isinstance(record, dict):
            continue
        source_stage = str(record.get("source_stage", "")).strip().lower()
        if source_stage not in {"extraction", "normalization", "interview", "validation"}:
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        family = _field_family(
            str(metadata.get("field_id", "")).strip() or str(record.get("field_path", "")).strip(),
            str(record.get("field_path", "")).strip(),
            "",
        )
        bucket = context.setdefault(family, {"manufacturer": set(), "model": set(), "voltage": set()})
        manufacturer = str(metadata.get("manufacturer", "")).strip().lower()
        model = str(metadata.get("model", "")).strip().lower()
        if manufacturer:
            bucket["manufacturer"].add(manufacturer)
        if model:
            bucket["model"].add(model)
        value = record.get("value")
        path = str(record.get("field_path", "")).strip().lower()
        if any(token in path for token in {"voltage", "kv", "v"}):
            fv = _safe_float(value)
            if fv is not None:
                bucket["voltage"].add(f"{fv:.3f}")
    return context


def _numeric_values_for_field_ids(canonical_state: dict[str, Any], field_ids: list[str]) -> list[float]:
    values: list[float] = []
    if not field_ids:
        return values
    lookup: set[str] = set()
    for field_id in field_ids:
        for key in registry_lookup_keys(field_id):
            if key:
                lookup.add(key)
    field_records = canonical_state.get("field_records")
    if not isinstance(field_records, list):
        return values
    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = str(record.get("field_path", "")).strip()
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        record_field_id = str(metadata.get("field_id", "")).strip()
        if field_path not in lookup and record_field_id not in lookup:
            continue
        numeric = _safe_float(record.get("value"))
        if numeric is not None:
            values.append(numeric)
    return values


def _text_values_for_field_ids(canonical_state: dict[str, Any], field_ids: list[str]) -> list[str]:
    values: list[str] = []
    if not field_ids:
        return values
    lookup: set[str] = set()
    for field_id in field_ids:
        for key in registry_lookup_keys(field_id):
            if key:
                lookup.add(key)
    field_records = canonical_state.get("field_records")
    if not isinstance(field_records, list):
        return values
    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = str(record.get("field_path", "")).strip()
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        record_field_id = str(metadata.get("field_id", "")).strip()
        if field_path not in lookup and record_field_id not in lookup:
            continue
        value = record.get("value")
        if isinstance(value, str) and value.strip():
            values.append(value.strip().lower())
    return values


def _context_consistency(
    *,
    canonical_state: dict[str, Any],
    field_id: str,
    field_path: str,
    field_family: str,
    record: dict[str, Any],
    family_context: dict[str, dict[str, set[str]]],
) -> tuple[float, list[str]]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    notes: list[str] = []
    score = 0.0
    bucket = family_context.get(field_family, {})
    policy = field_resolution_policy_for_family(field_family)
    profile = field_resolution_scoring_profile(field_family, field_id, field_path)
    field_type = str(profile.get("field_type", "general")).strip().lower() or "general"

    manufacturer = str(metadata.get("manufacturer", "")).strip().lower()
    model = str(metadata.get("model", "")).strip().lower()
    if manufacturer and manufacturer in bucket.get("manufacturer", set()):
        score += 10.0
        notes.append("Manufacturer aligns with other evidence in this equipment family.")
    elif manufacturer and bucket.get("manufacturer"):
        score -= 6.0
        notes.append("Manufacturer differs from other evidence in this equipment family.")

    if model and model in bucket.get("model", set()):
        score += 12.0
        notes.append("Model aligns with other evidence in this equipment family.")
    elif model and bucket.get("model"):
        score -= 8.0
        notes.append("Model differs from other evidence in this equipment family.")

    value = record.get("value")
    numeric = _safe_float(value)
    path_blob = " ".join([field_id.lower(), field_path.lower()])
    source_hierarchy = _infer_source_hierarchy(record, field_family)
    if numeric is not None and any(token in path_blob for token in {"count", "unit_count"}):
        if numeric <= 0:
            score -= 20.0
            notes.append("Unit count is non-positive and likely invalid.")
        elif numeric >= 1:
            score += 6.0
            notes.append("Unit count is positive and plausible.")

    if numeric is not None and any(token in path_blob for token in {"voltage", "kv", "_v"}):
        known_voltages = bucket.get("voltage", set())
        if known_voltages:
            as_key = f"{numeric:.3f}"
            if as_key in known_voltages:
                score += 10.0
                notes.append("Voltage is consistent with nearby family evidence.")
            else:
                nearest = min((abs(float(item) - numeric) for item in known_voltages), default=None)
                if nearest is not None and nearest > max(5.0, numeric * 0.25):
                    score -= 10.0
                    notes.append("Voltage differs materially from nearby family evidence.")

    value_blob = str(value).strip().lower()
    if "standby" in path_blob and value_blob and "prime" in value_blob:
        score -= 8.0
        notes.append("Value appears to describe prime mode for a standby-oriented field.")
    if "prime" in path_blob and value_blob and "standby" in value_blob:
        score -= 8.0
        notes.append("Value appears to describe standby mode for a prime-oriented field.")

    voltage_reference_fields = policy.get("voltage_reference_fields", []) if isinstance(policy.get("voltage_reference_fields", []), list) else []
    if numeric is not None and voltage_reference_fields and any(token in path_blob for token in {"voltage", "_kv", "_v", "kv_or_v"}):
        comparison_fields = [
            str(item)
            for item in voltage_reference_fields
            if str(item).strip() and str(item).strip() not in {field_id, field_path}
        ]
        ref_values = _numeric_values_for_field_ids(canonical_state, comparison_fields)
        if ref_values:
            nearest = min(abs(item - numeric) for item in ref_values)
            baseline = max(min(ref_values), 1.0)
            if nearest <= max(1.0, baseline * 0.15):
                score += 30.0
                notes.append("Voltage aligns with related interconnection/equipment reference fields.")
            elif nearest >= max(5.0, baseline * 0.40):
                score -= 30.0
                notes.append("Voltage differs materially from related interconnection/equipment reference fields.")

    capacity_fields = policy.get("capacity_fields", []) if isinstance(policy.get("capacity_fields", []), list) else []
    peak_demand_fields = policy.get("peak_demand_fields", []) if isinstance(policy.get("peak_demand_fields", []), list) else []
    if numeric is not None and peak_demand_fields and capacity_fields and ("mva_per_unit" in path_blob or "capacity_kw_per_unit" in path_blob):
        peak_values = _numeric_values_for_field_ids(canonical_state, [str(item) for item in peak_demand_fields])
        count_values = _numeric_values_for_field_ids(canonical_state, [str(item) for item in capacity_fields if str(item).endswith("_unit_count")])
        if peak_values:
            peak = max(peak_values)
            unit_count = max(count_values) if count_values else 1.0
            total_capacity = numeric * max(unit_count, 1.0)
            if "mva_per_unit" in path_blob:
                if total_capacity >= peak * 1.05:
                    score += 18.0
                    notes.append("Transformer capacity is plausibly aligned with peak demand.")
                elif total_capacity < peak * 0.75:
                    score -= 48.0
                    notes.append("Transformer capacity appears undersized relative to peak demand.")
                    if source_hierarchy == "manufacturer_model_specific_spec":
                        score -= 12.0
                        notes.append("Exact-model evidence is down-ranked because the candidate capacity is materially undersized for the project demand.")
            elif "capacity_kw_per_unit" in path_blob:
                if total_capacity >= peak * 1000.0 * 0.80:
                    score += 12.0
                    notes.append("UPS aggregate capacity is plausibly aligned with peak demand.")
                elif total_capacity < peak * 1000.0 * 0.50:
                    score -= 16.0
                    notes.append("UPS aggregate capacity appears low relative to peak demand.")

    runtime_fields = policy.get("runtime_fields", []) if isinstance(policy.get("runtime_fields", []), list) else []
    if numeric is not None and runtime_fields and "runtime" in path_blob:
        if numeric <= 0:
            score -= 15.0
            notes.append("Runtime value is non-positive and likely invalid.")
        elif numeric >= 5:
            score += 6.0
            notes.append("Runtime value is positive and plausible.")

    if field_family == "ramping":
        peak_values = _numeric_values_for_field_ids(canonical_state, ["peak_demand_mw"])
        if numeric is not None and peak_values:
            peak = max(peak_values)
            if numeric <= 0:
                score -= 12.0
                notes.append("Ramp value is non-positive and likely invalid.")
            elif numeric <= peak * 2.0:
                score += 6.0
                notes.append("Ramp value is plausibly scaled relative to peak demand.")
            else:
                score -= 8.0
                notes.append("Ramp value appears unusually high relative to peak demand.")

    rating_basis_values = _text_values_for_field_ids(canonical_state, ["generator_prime_or_standby_rating_basis"])
    rating_basis = str(metadata.get("rating_basis", "")).strip().lower() or value_blob
    if field_family == "generator" and "rated_kw_per_unit" in path_blob and rating_basis_values and rating_basis:
        if any(rating_basis in item or item in rating_basis for item in rating_basis_values):
            score += 8.0
            notes.append("Generator rating basis aligns with related generator operating basis evidence.")
        elif any(item in {"prime", "standby"} for item in rating_basis_values):
            score -= 6.0
            notes.append("Generator rating basis differs from related generator operating basis evidence.")

    policy_adjustment, policy_notes, policy_rejected = field_context_adjustment(field_path or field_id, record)
    if policy_adjustment:
        score += policy_adjustment
    for note in policy_notes:
        if note not in notes:
            notes.append(note)
    if policy_rejected:
        score -= 35.0
        notes.append("Candidate down-ranked because evidence context conflicts with the target planner field definition.")

    if field_family == "interconnection" and field_type == "voltage":
        if source_hierarchy == "official_interconnection_source":
            score += 14.0
            notes.append("Official interconnection evidence is strongly preferred for POI and service voltage fields.")
        elif source_hierarchy in {"manufacturer_model_specific_spec", "vendor_pdf", "secondary_web", "llm_uncited"}:
            score -= 12.0
            notes.append("Equipment/vendor evidence is less authoritative for POI and service voltage fields.")

    if source_hierarchy == "applicant_confirmed_answer":
        score += 8.0
        notes.append("Applicant-confirmed interview evidence receives elevated governed weight over inferred evidence.")

    if field_family == "generator" and field_type == "rating_basis":
        if source_hierarchy == "applicant_confirmed_answer":
            score += 10.0
            notes.append("Applicant confirmation is especially important for generator rating-basis fields.")
        elif source_hierarchy in {"secondary_web", "llm_uncited"}:
            score -= 10.0
            notes.append("Low-authority web evidence is weak support for generator rating-basis fields.")

    if field_family == "ups" and field_type == "runtime":
        if source_hierarchy == "manufacturer_model_specific_spec":
            score += 10.0
            notes.append("Exact model-specific UPS evidence is preferred for runtime claims.")
        elif source_hierarchy in {"official_interconnection_source", "secondary_web", "llm_uncited"}:
            score -= 6.0
            notes.append("Non-equipment evidence is weaker support for UPS runtime claims.")

    if field_family == "transformer" and field_type == "capacity":
        if source_hierarchy == "manufacturer_model_specific_spec":
            score += 8.0
            notes.append("Model-specific transformer evidence is preferred for nameplate capacity fields.")
        elif source_hierarchy == "secondary_web":
            score -= 8.0
            notes.append("Secondary web evidence is weak support for transformer capacity fields.")

    return score, notes




def _source_stream_adjustment(record: dict[str, Any], *, field_family: str, field_id: str, field_path: str) -> float:
    stream = _infer_source_stream(record)
    profile = field_resolution_source_stream_profile(field_family, field_id, field_path)
    adjustment = float(profile.get(stream, 0))
    hierarchy = _infer_source_hierarchy(record, field_family)
    specificity = _infer_specificity(record)
    if stream == "official_web" and hierarchy != "official_interconnection_source":
        adjustment -= 2.0
    if stream == "vendor_pdf" and specificity in {"exact_model_match", "family_match"}:
        adjustment += 2.0
    if stream == "knowledge_library" and specificity in {"exact_model_match", "family_match"}:
        adjustment += 1.0
    role = source_role_from_candidate(record)
    field_adjustment, _notes, rejected = field_context_adjustment(field_path or field_id, record)
    adjustment += field_adjustment * 0.35
    if rejected:
        adjustment -= 12.0
    if stream == "applicant_interview" and hierarchy == "applicant_confirmed_answer":
        adjustment += 6.0
    elif stream == "applicant_interview":
        adjustment -= 3.0
    if role == "application_request_form" and field_family in {"interconnection", "load"}:
        adjustment += 4.0
    if role == "equipment_schedule" and field_family in {"generator", "transformer", "ups"}:
        adjustment += 5.0
    return adjustment


def _promotion_adjustment(record: dict[str, Any], *, field_family: str, field_id: str, field_path: str) -> tuple[float, list[str]]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_method = str(metadata.get("source_method", "")).strip().lower()
    source_priority = str(metadata.get("source_priority", "")).strip().lower()
    source_hierarchy = _infer_source_hierarchy(record, field_family)
    specificity = _infer_specificity(record)
    adjustment = 0.0
    notes: list[str] = []

    if source_method.startswith("interconnection_study."):
        adjustment += 10.0
        notes.append("Promoted interconnection-study fact received explicit adjudication credit.")
        if field_family in {"interconnection", "metering", "relay"}:
            adjustment += 8.0
            notes.append("Promotion aligns with an interconnection-focused field family.")
        if specificity == "direct_field_match":
            adjustment += 4.0
    elif source_method.startswith("regex.") and source_hierarchy == "applicant_direct_document" and specificity == "direct_field_match":
        adjustment += 3.0

    if source_priority == "official_web_executed":
        adjustment += 10.0
        notes.append("Executed official web retrieval added governed provenance support.")
        if field_family in {"interconnection", "metering", "relay"}:
            adjustment += 6.0
            notes.append("Executed official source is highly relevant for this field family.")
    return adjustment, notes
def _candidate_score(record: dict[str, Any], corroboration_count: int, *, field_family: str, field_id: str, field_path: str, context_score: float = 0.0) -> float:
    confidence = _safe_float(record.get("confidence_score"))
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_hierarchy = _infer_source_hierarchy(record, field_family)
    specificity = _infer_specificity(record)
    profile = field_resolution_scoring_profile(field_family, field_id, field_path)
    promotion_adjustment, _ = _promotion_adjustment(record, field_family=field_family, field_id=field_id, field_path=field_path)
    score = 0.0
    score += STAGE_PRIORITY.get(str(record.get("source_stage", "")).strip(), 0)
    score += SOURCE_PRIORITY.get(str(record.get("source_type", "")).strip(), 0)
    score += SOURCE_HIERARCHY_PRIORITY.get(source_hierarchy, 0)
    score += field_resolution_policy_for_family(field_family).get("source_hierarchy_boosts", {}).get(source_hierarchy, 0)
    score += profile.get("source_hierarchy_boosts", {}).get(source_hierarchy, 0)
    score += profile.get("source_hierarchy_penalties", {}).get(source_hierarchy, 0)
    score += SPECIFICITY_PRIORITY.get(specificity, 0)
    field_type = str(profile.get("field_type", "general")).strip().lower() or "general"
    if source_hierarchy == "manufacturer_model_specific_spec" and specificity == "exact_model_match":
        score += -12.0 if field_family == "transformer" and field_type == "capacity" else 70.0
    elif source_hierarchy == "manufacturer_family_spec" or specificity == "family_match":
        score -= 18.0
    score += EVIDENCE_PRIORITY.get(str(record.get("evidence_strength", "UNKNOWN")).strip().upper(), 0)
    if confidence is not None:
        score += confidence * 100.0
    if corroboration_count > 1:
        score += min(corroboration_count, 4) * 8.0
    if metadata.get("is_applicant_document_direct") is True:
        score += 18.0
    if metadata.get("is_official_source") is True:
        score += 10.0
    if metadata.get("is_secondary_web") is True:
        score -= 8.0
    if metadata.get("planner_candidate_primary") is True:
        score += 45.0
    if metadata.get("legacy_candidate_supplement") is True:
        score -= 45.0
    if record.get("value") is None or bool(record.get("is_missing")):
        score -= 250.0
    field_support_strength = str(metadata.get("field_support_strength", "")).strip().upper()
    if field_support_strength == "HIGH":
        score += 10.0
    elif field_support_strength == "MODERATE":
        score += 3.0
    elif field_support_strength == "LOW":
        score -= 4.0
    if bool(metadata.get("weak_support_only")):
        score -= 12.0
    if int(metadata.get("exact_model_support_count", 0) or 0) > 0:
        score += 12.0
    if int(metadata.get("official_source_count", 0) or 0) > 0:
        score += 6.0
    if field_family == "interconnection" and field_type == "voltage":
        if source_hierarchy == "official_interconnection_source":
            score += 90.0
        elif source_hierarchy in {"manufacturer_model_specific_spec", "manufacturer_family_spec", "vendor_pdf", "secondary_web", "llm_uncited"}:
            score -= 90.0
    score += _source_stream_adjustment(record, field_family=field_family, field_id=field_id, field_path=field_path)
    score += promotion_adjustment
    score += context_score
    return score


def _source_candidate_inputs(canonical_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    payload = canonical_state.get("source_candidate_inputs")
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key in ("extraction_candidates", "retrieval_candidates", "interview_candidates", "planner_candidate_rows"):
        value = payload.get(key)
        if isinstance(value, list):
            normalized[key] = [item for item in value if isinstance(item, dict)]
    summary = payload.get("planner_candidate_ledger_summary")
    if isinstance(summary, dict):
        normalized["planner_candidate_ledger_summary"] = [dict(summary)]
    return normalized


def _supporting_source_inputs(canonical_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    payload = canonical_state.get("source_candidate_inputs")
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key in ("knowledge_library_sources", "vendor_pdf_sources", "official_web_sources"):
        value = payload.get(key)
        if isinstance(value, list):
            normalized[key] = [item for item in value if isinstance(item, dict)]
    return normalized



def _evidence_route_record_inputs(canonical_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = canonical_state.get("source_candidate_inputs")
    if not isinstance(payload, dict):
        return {}
    value = payload.get("evidence_route_records")
    if not isinstance(value, list):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        field_path = str(item.get("field_path", "")).strip()
        if field_path:
            payload = dict(item)
            records[field_path] = payload
            field_id = registry_field_id_for_path(field_path)
            if field_id:
                records[field_id] = payload
    return records


def _field_support_summary_inputs(canonical_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = canonical_state.get("source_candidate_inputs")
    if not isinstance(payload, dict):
        return {}
    value = payload.get("field_support_summary")
    if not isinstance(value, dict):
        return {}
    return {
        str(field_path).strip(): dict(summary)
        for field_path, summary in value.items()
        if str(field_path).strip() and isinstance(summary, dict)
    }


def _record_key(record: dict[str, Any]) -> tuple[Any, ...]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return (
        str(record.get("field_path", "")).strip(),
        str(record.get("source_stage", "")).strip(),
        str(record.get("source_type", "")).strip(),
        _canonical_value(record.get("value")),
        tuple(sorted(str(item).strip() for item in (record.get("source_ref") or []) if str(item).strip())) if isinstance(record.get("source_ref"), list) else (),
        str(metadata.get("source_method", "")).strip(),
        str(metadata.get("manufacturer", "")).strip(),
        str(metadata.get("model", "")).strip(),
        str(metadata.get("question_id", "")).strip(),
    )




def _retrieval_evidence_strength(candidate: dict[str, Any]) -> str:
    evidence_tier = str(candidate.get("evidence_tier", "")).strip().lower()
    document_type = str(candidate.get("document_type", "")).strip().lower()
    source_priority = str(candidate.get("source_priority", "")).strip().lower()
    source_type = str(candidate.get("source_type", "")).strip().lower()
    if any(token in source_priority for token in ("model_specific", "direct_document", "official_interconnection")):
        return "STRONG"
    if evidence_tier in {"official_vendor_document", "official_interconnection_source", "structured_catalog"}:
        return "STRONG"
    if "official" in document_type or source_type in {"official_source_index", "knowledge_library_match"}:
        return "STRONG"
    if evidence_tier in {"vendor_document", "modeling_reference", "interconnection_guidance"}:
        return "MODERATE"
    if evidence_tier in {"vendor_document_pointer", "reference"}:
        return "WEAK"
    return "MODERATE" if candidate.get("source_ref") or candidate.get("source_url") else "UNKNOWN"

def _candidate_record_from_extraction_candidate(candidate: dict[str, Any], field_path: str) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_ref = []
    for key in ("source_anchor_ids", "source_ref"):
        value = candidate.get(key)
        if isinstance(value, list):
            source_ref.extend(str(item).strip() for item in value if str(item).strip())
    source_artifact_id = str(candidate.get("source_artifact_id", "")).strip()
    if source_artifact_id:
        source_ref.append(source_artifact_id)
    confidence = _safe_float(candidate.get("confidence"))
    return {
        "field_record_id": f"direct_extract::{field_path}::{len(source_ref)}",
        "field_path": field_path,
        "value": candidate.get("value"),
        "source_stage": "extraction",
        "source_type": "schema_field_candidate",
        "source_ref": list(dict.fromkeys(source_ref)),
        "confidence_score": confidence,
        "confidence_tag": _confidence_band(confidence),
        "evidence_strength": "STRONG" if source_ref else "MODERATE",
        "is_missing": candidate.get("value") is None,
        "metadata": {
            "source_method": candidate.get("source_method"),
            "page_number": candidate.get("page_number"),
            "worker_name": candidate.get("worker_name"),
            "region_type": candidate.get("region_type"),
            "source_anchor_ids": candidate.get("source_anchor_ids"),
            "artifact_name": source_artifact_id,
            "unit": candidate.get("unit"),
            "field_id": registry_field_id_for_path(field_path),
            **metadata,
        },
    }


def _candidate_record_from_retrieval_candidate(candidate: dict[str, Any], field_path: str, support_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    source_ref: list[str] = []
    source_ref_value = candidate.get("source_ref")
    if isinstance(source_ref_value, list):
        source_ref.extend(str(item).strip() for item in source_ref_value if str(item).strip())
    elif isinstance(source_ref_value, str) and source_ref_value.strip():
        source_ref.append(source_ref_value.strip())
    source_url = str(candidate.get("source_url", "")).strip()
    if source_url:
        source_ref.append(source_url)
    confidence = _safe_float(candidate.get("confidence"))
    source_type_detail = str(candidate.get("source_type", "")).strip()
    source_priority = str(candidate.get("source_priority", "")).strip()
    source_kind = str(candidate.get("source_kind", "")).strip()
    document_type = str(candidate.get("document_type", "")).strip()
    evidence_tier = str(candidate.get("evidence_tier", "")).strip()
    match_reason = str(candidate.get("match_reason", "")).strip()
    support_summary = support_summary if isinstance(support_summary, dict) else {}
    return {
        "field_record_id": f"direct_retrieval::{field_path}::{len(source_ref)}",
        "field_path": field_path,
        "value": candidate.get("value"),
        "source_stage": "retrieval",
        "source_type": "equipment_reference_candidate" if candidate.get("value") is not None else "equipment_reference_unresolved",
        "source_ref": list(dict.fromkeys(source_ref)),
        "confidence_score": confidence,
        "confidence_tag": _confidence_band(confidence),
        "evidence_strength": _retrieval_evidence_strength(candidate),
        "is_missing": candidate.get("value") is None,
        "metadata": {
            "manufacturer": candidate.get("manufacturer"),
            "model": candidate.get("model"),
            "equipment_family": candidate.get("equipment_family"),
            "spec_field": candidate.get("spec_field"),
            "matched_field_key": candidate.get("matched_field_key"),
            "canonical_field_key": candidate.get("canonical_field_key"),
            "confidence_reason": candidate.get("confidence_reason"),
            "source_lookup_strategy": candidate.get("lookup_strategy"),
            "review_required": bool(candidate.get("review_required")),
            "source_type_detail": source_type_detail,
            "source_priority": source_priority,
            "source_kind": source_kind,
            "document_type": document_type,
            "document_path": candidate.get("document_path"),
            "evidence_tier": evidence_tier,
            "match_reason": match_reason,
            "evidence_text": candidate.get("evidence_text"),
            "source_method": source_priority or source_type_detail or candidate.get("lookup_strategy"),
            "field_id": registry_field_id_for_path(field_path),
            "matched_target_fields": list(support_summary.get("matched_target_fields", [])) if isinstance(support_summary.get("matched_target_fields", []), list) else [],
            "field_support_strength": str(support_summary.get("support_strength", "")).strip(),
            "exact_model_support_count": int(support_summary.get("exact_model_support_count", 0) or 0),
            "official_source_count": int(support_summary.get("official_source_count", 0) or 0),
            "weak_support_only": bool(support_summary.get("weak_support_only", False)),
            "best_source_hierarchy": str(support_summary.get("best_source_hierarchy", "")).strip(),
            "best_specificity": str(support_summary.get("best_specificity", "")).strip(),
        },
    }


def _candidate_record_from_interview_candidate(candidate: dict[str, Any], field_path: str) -> dict[str, Any]:
    value = candidate.get("value")
    unresolved = bool(candidate.get("unresolved")) or value is None
    support_summary = candidate.get("field_support_summary") if isinstance(candidate.get("field_support_summary"), dict) else {}
    return {
        "field_record_id": f"direct_interview::{field_path}",
        "field_path": field_path,
        "value": value,
        "source_stage": "interview",
        "source_type": "human_input" if not unresolved else "interview_unresolved",
        "source_ref": ["engineer_input"] if not unresolved else ["interview_followup"],
        "confidence_score": 1.0 if not unresolved else None,
        "confidence_tag": "HIGH" if not unresolved else "UNRESOLVED",
        "evidence_strength": "STRONG" if not unresolved else "UNKNOWN",
        "is_missing": unresolved,
        "metadata": {
            "question_id": candidate.get("question_id"),
            "source_context": candidate.get("source_context"),
            "confirmed_by": candidate.get("confirmed_by", "applicant"),
            "field_id": registry_field_id_for_path(field_path),
            "matched_target_fields": list(support_summary.get("matched_target_fields", [])) if isinstance(support_summary.get("matched_target_fields", []), list) else [],
            "field_support_strength": str(support_summary.get("support_strength", "")).strip(),
            "exact_model_support_count": int(support_summary.get("exact_model_support_count", 0) or 0),
            "official_source_count": int(support_summary.get("official_source_count", 0) or 0),
            "weak_support_only": bool(support_summary.get("weak_support_only", False)),
            "best_source_hierarchy": str(support_summary.get("best_source_hierarchy", "")).strip(),
            "best_specificity": str(support_summary.get("best_specificity", "")).strip(),
        },
    }


def _direct_source_candidate_records(canonical_state: dict[str, Any], lookup_keys: list[str], *, include_planner_candidate_rows: bool = True) -> list[dict[str, Any]]:
    payload = _source_candidate_inputs(canonical_state)
    if not payload:
        return []
    normalized = {str(key).strip() for key in lookup_keys if str(key).strip()}
    records: list[dict[str, Any]] = []
    for candidate in payload.get("extraction_candidates", []):
        field_path = str(candidate.get("field_path", "")).strip()
        if field_path and field_path in normalized:
            records.append(_candidate_record_from_extraction_candidate(candidate, field_path))
    field_support_summary = _field_support_summary_inputs(canonical_state)
    for candidate in payload.get("retrieval_candidates", []):
        field_path = str(candidate.get("field_path", "")).strip()
        if field_path and field_path in normalized:
            records.append(_candidate_record_from_retrieval_candidate(candidate, field_path, field_support_summary.get(field_path, {})))
    for candidate in payload.get("interview_candidates", []):
        field_path = str(candidate.get("field_path", "")).strip()
        if field_path and field_path in normalized:
            records.append(_candidate_record_from_interview_candidate(candidate, field_path))
    if include_planner_candidate_rows:
        records.extend(
            candidate_ledger_records_for_lookup_keys(
                payload.get("planner_candidate_rows", []),
                lookup_keys,
                include_rejected=False,
            )
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _supporting_sources_for_lookup_keys(
    canonical_state: dict[str, Any],
    lookup_keys: list[str],
    *,
    field_family: str,
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    payload = _supporting_source_inputs(canonical_state)
    if not payload:
        return []
    normalized = {str(key).strip() for key in lookup_keys if str(key).strip()}
    candidate_meta = [item.get("metadata", {}) for item in (candidates or []) if isinstance(item, dict)]
    candidate_models = {str(meta.get("model", "")).strip().lower() for meta in candidate_meta if isinstance(meta, dict) and str(meta.get("model", "")).strip()}
    candidate_mfrs = {str(meta.get("manufacturer", "")).strip().lower() for meta in candidate_meta if isinstance(meta, dict) and str(meta.get("manufacturer", "")).strip()}
    results: list[dict[str, Any]] = []
    for source_key, stream_name in (("knowledge_library_sources", "knowledge_library"), ("vendor_pdf_sources", "vendor_pdf"), ("official_web_sources", "official_web")):
        for item in payload.get(source_key, []):
            if not isinstance(item, dict):
                continue
            target_fields = {str(v).strip() for v in item.get("target_fields", []) if str(v).strip()} if isinstance(item.get("target_fields"), list) else set()
            family = str(item.get("equipment_family", "")).strip().lower()
            manufacturer = str(item.get("manufacturer", "")).strip().lower()
            model = str(item.get("model", "")).strip().lower()
            if target_fields and not (target_fields & normalized):
                if not ((manufacturer and manufacturer in candidate_mfrs) or (model and model in candidate_models)):
                    continue
            elif not target_fields and family and family != field_family:
                if not ((manufacturer and manufacturer in candidate_mfrs) or (model and model in candidate_models)):
                    continue
            results.append(
                {
                    "source_stream": stream_name,
                    "source_type": str(item.get("source_type", "")).strip() or stream_name,
                    "source_ref": str(item.get("source_ref", "")).strip(),
                    "source_url": str(item.get("source_url", "")).strip(),
                    "allowed_domain": str(item.get("allowed_domain", "")).strip(),
                    "manufacturer": manufacturer,
                    "model": model,
                    "equipment_family": family,
                    "target_fields": sorted(target_fields),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in results:
        key = (
            str(item.get("source_stream", "")),
            str(item.get("source_type", "")),
            str(item.get("source_ref", "")),
            str(item.get("source_url", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _mark_legacy_candidate_supplement(record: dict[str, Any], *, candidate_ledger_present: bool) -> dict[str, Any]:
    """Return a governed compatibility copy for non-ledger candidate records."""
    item = dict(record)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = dict(metadata)
    if candidate_ledger_present and metadata.get("record_origin") != "planner_candidate_ledger":
        metadata["legacy_candidate_supplement"] = True
        metadata["candidate_governance_source"] = "planner_candidate_ledger_primary_legacy_supplement"
        item["source_type"] = str(item.get("source_type", "legacy_candidate_supplement")).strip() or "legacy_candidate_supplement"
    item["metadata"] = metadata
    return item


def _records_for_lookup_keys(canonical_state: dict[str, Any], lookup_keys: list[str]) -> list[dict[str, Any]]:
    normalized = {str(key).strip() for key in lookup_keys if str(key).strip()}
    payload = _source_candidate_inputs(canonical_state)
    planner_candidate_records = candidate_ledger_records_for_lookup_keys(
        payload.get("planner_candidate_rows", []) if isinstance(payload, dict) else [],
        lookup_keys,
        include_rejected=False,
    )
    candidate_ledger_present = any(not bool(record.get("is_missing")) for record in planner_candidate_records)

    legacy_records: list[dict[str, Any]] = []
    field_records = canonical_state.get("field_records")
    if isinstance(field_records, list):
        for record in field_records:
            if not isinstance(record, dict):
                continue
            field_path = str(record.get("field_path", "")).strip()
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            record_field_id = str(metadata.get("field_id", "")).strip()
            if (field_path and field_path in normalized) or (record_field_id and record_field_id in normalized):
                legacy_records.append(record)
    for record in _direct_source_candidate_records(canonical_state, lookup_keys, include_planner_candidate_rows=False):
        legacy_records.append(record)

    records: list[dict[str, Any]] = []
    records.extend(planner_candidate_records)
    records.extend(_mark_legacy_candidate_supplement(record, candidate_ledger_present=candidate_ledger_present) for record in legacy_records)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _build_candidates(
    field_id: str,
    field_path: str,
    label: str,
    field_family: str,
    records: list[dict[str, Any]],
    canonical_state: dict[str, Any],
) -> list[dict[str, Any]]:
    counts = Counter(
        _canonical_value(record.get("value"))
        for record in records
        if isinstance(record, dict) and record.get("value") is not None and not bool(record.get("is_missing"))
    )
    family_context = _build_family_identity_context(canonical_state)
    candidates: list[FieldResolutionCandidate] = []
    for index, record in enumerate(records, start=1):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        confidence = _safe_float(record.get("confidence_score"))
        canonical = _canonical_value(record.get("value"))
        corroboration_count = counts.get(canonical, 1) if canonical is not None else 1
        source_hierarchy = _infer_source_hierarchy(record, field_family)
        specificity = _infer_specificity(record)
        context_score, consistency_notes = _context_consistency(
            canonical_state=canonical_state,
            field_id=field_id,
            field_path=field_path,
            field_family=field_family,
            record=record,
            family_context=family_context,
        )
        promotion_adjustment, promotion_notes = _promotion_adjustment(
            record,
            field_family=field_family,
            field_id=field_id,
            field_path=field_path,
        )
        combined_notes = list(consistency_notes)
        combined_notes.extend(note for note in promotion_notes if note not in combined_notes)
        candidate = FieldResolutionCandidate(
            candidate_id=str(record.get("field_record_id", "")).strip() or f"{field_id}__candidate_{index}",
            field_id=field_id,
            field_path=field_path,
            label=label,
            value=record.get("value"),
            field_family=field_family,
            unit=str(metadata.get("unit", "")).strip() or str(metadata.get("units", "")).strip(),
            source_stage=str(record.get("source_stage", "")).strip(),
            source_type=str(record.get("source_type", "")).strip(),
            source_stream=_infer_source_stream(record),
            source_hierarchy=source_hierarchy,
            source_ref=[str(item).strip() for item in (record.get("source_ref") or []) if str(item).strip()] if isinstance(record.get("source_ref"), list) else [],
            source_anchor=_anchor_from_record(record),
            specificity=specificity,
            confidence=confidence,
            confidence_band=_confidence_band(confidence),
            evidence_strength=str(record.get("evidence_strength", "UNKNOWN")).strip().upper() or "UNKNOWN",
            corroboration_count=corroboration_count,
            context_score=context_score + promotion_adjustment,
            consistency_notes=combined_notes,
            metadata=metadata,
        )
        candidate.score = _candidate_score(
            record,
            corroboration_count,
            field_family=field_family,
            field_id=field_id,
            field_path=field_path,
            context_score=context_score,
        )
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.score, item.confidence or -1.0, item.candidate_id), reverse=True)
    return _apply_group_support_adjustments([item.to_dict() for item in candidates])


def _candidate_group_key(value: Any) -> str:
    return repr(_canonical_value(value))



def _source_identity_tokens(candidate: dict[str, Any]) -> set[str]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    identity = ""
    for value, prefix in (
        (candidate.get("source_anchor"), "anchor"),
        ((candidate.get("source_ref") or [""])[0] if isinstance(candidate.get("source_ref"), list) and candidate.get("source_ref") else "", "ref"),
        (metadata.get("source_url"), "url"),
        (metadata.get("source_artifact_id"), "artifact"),
        (metadata.get("artifact_name"), "artifact"),
        (metadata.get("source_document_id"), "doc"),
        (candidate.get("candidate_id"), "candidate"),
    ):
        cleaned = str(value).strip().lower()
        if cleaned:
            identity = f"{prefix}:{cleaned}"
            break
    return {identity} if identity else set()



def _candidate_value_groups(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = _candidate_group_key(candidate.get("value"))
        bucket = groups.setdefault(
            key,
            {
                "group_key": key,
                "canonical_value": _canonical_value(candidate.get("value")),
                "value": candidate.get("value"),
                "candidate_count": 0,
                "independent_source_tokens": set(),
                "source_streams": set(),
                "source_hierarchies": set(),
                "specificities": set(),
                "total_score": 0.0,
                "max_score": 0.0,
                "official_source_count": 0,
                "exact_model_support_count": 0,
                "applicant_support_count": 0,
                "executed_official_web_count": 0,
                "promoted_interconnection_fact_count": 0,
            },
        )
        bucket["candidate_count"] += 1
        bucket["independent_source_tokens"].update(_source_identity_tokens(candidate))
        stream = str(candidate.get("source_stream", "")).strip()
        if stream:
            bucket["source_streams"].add(stream)
        hierarchy = str(candidate.get("source_hierarchy", "")).strip()
        if hierarchy:
            bucket["source_hierarchies"].add(hierarchy)
            if hierarchy == "official_interconnection_source":
                bucket["official_source_count"] += 1
            if hierarchy.startswith("applicant_"):
                bucket["applicant_support_count"] += 1
        specificity = str(candidate.get("specificity", "")).strip()
        if specificity:
            bucket["specificities"].add(specificity)
            if specificity == "exact_model_match":
                bucket["exact_model_support_count"] += 1
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if bool(metadata.get("is_official_source", False)):
            bucket["official_source_count"] += 1
        if str(metadata.get("source_priority", "")).strip().lower() == "official_web_executed":
            bucket["executed_official_web_count"] += 1
        if str(metadata.get("source_method", "")).strip().lower().startswith("interconnection_study."):
            bucket["promoted_interconnection_fact_count"] += 1
        if str(metadata.get("manufacturer", "")).strip() and str(metadata.get("model", "")).strip():
            bucket["exact_model_support_count"] += 1
        score = float(candidate.get("score", 0.0) or 0.0)
        bucket["total_score"] += score
        bucket["max_score"] = max(float(bucket.get("max_score", 0.0) or 0.0), score)
    for bucket in groups.values():
        tokens = bucket.pop("independent_source_tokens", set())
        bucket["independent_source_count"] = len(tokens)
        bucket["source_stream_count"] = len(bucket.pop("source_streams", set()))
        bucket["source_hierarchy_count"] = len(bucket.pop("source_hierarchies", set()))
        bucket["specificity_count"] = len(bucket.pop("specificities", set()))
    return groups



def _group_agreement_boost(bucket: dict[str, Any]) -> float:
    candidate_count = int(bucket.get("candidate_count", 0) or 0)
    independent_source_count = int(bucket.get("independent_source_count", 0) or 0)
    source_stream_count = int(bucket.get("source_stream_count", 0) or 0)
    exact_model_support_count = int(bucket.get("exact_model_support_count", 0) or 0)
    official_source_count = int(bucket.get("official_source_count", 0) or 0)
    applicant_support_count = int(bucket.get("applicant_support_count", 0) or 0)
    executed_official_web_count = int(bucket.get("executed_official_web_count", 0) or 0)
    promoted_interconnection_fact_count = int(bucket.get("promoted_interconnection_fact_count", 0) or 0)
    boost = 0.0
    if candidate_count > 1:
        boost += min(candidate_count - 1, 3) * 6.0
    if independent_source_count > 1:
        boost += min(independent_source_count - 1, 3) * 7.0
    if source_stream_count > 1:
        boost += min(source_stream_count - 1, 2) * 5.0
    if exact_model_support_count > 0 and independent_source_count > 1:
        boost += 6.0
    if official_source_count > 0 and independent_source_count > 1:
        boost += 6.0
    if applicant_support_count > 0 and independent_source_count > 1:
        boost += 4.0
    if executed_official_web_count > 0 and applicant_support_count > 0:
        boost += 8.0
    if promoted_interconnection_fact_count > 0 and official_source_count > 0:
        boost += 6.0
    return boost



def _apply_group_support_adjustments(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = _candidate_value_groups(candidates)
    adjusted: list[dict[str, Any]] = []
    for candidate in candidates:
        payload = dict(candidate)
        metadata = dict(payload.get("metadata", {})) if isinstance(payload.get("metadata"), dict) else {}
        bucket = groups.get(_candidate_group_key(payload.get("value")), {})
        agreement_boost = _group_agreement_boost(bucket)
        payload["score"] = float(payload.get("score", 0.0) or 0.0) + agreement_boost
        payload["group_candidate_count"] = int(bucket.get("candidate_count", 0) or 0)
        payload["group_independent_source_count"] = int(bucket.get("independent_source_count", 0) or 0)
        payload["group_source_stream_count"] = int(bucket.get("source_stream_count", 0) or 0)
        payload["group_total_score"] = float(bucket.get("total_score", 0.0) or 0.0)
        payload["group_agreement_boost"] = agreement_boost
        payload["group_official_source_count"] = int(bucket.get("official_source_count", 0) or 0)
        payload["group_executed_official_web_count"] = int(bucket.get("executed_official_web_count", 0) or 0)
        payload["group_promoted_interconnection_fact_count"] = int(bucket.get("promoted_interconnection_fact_count", 0) or 0)
        metadata["group_candidate_count"] = payload["group_candidate_count"]
        metadata["group_independent_source_count"] = payload["group_independent_source_count"]
        metadata["group_source_stream_count"] = payload["group_source_stream_count"]
        metadata["group_total_score"] = payload["group_total_score"]
        metadata["group_agreement_boost"] = agreement_boost
        metadata["group_official_source_count"] = payload["group_official_source_count"]
        metadata["group_executed_official_web_count"] = payload["group_executed_official_web_count"]
        metadata["group_promoted_interconnection_fact_count"] = payload["group_promoted_interconnection_fact_count"]
        payload["metadata"] = metadata
        adjusted.append(payload)
    adjusted.sort(key=lambda item: (item.get("score", 0.0), item.get("confidence") or -1.0, item.get("candidate_id", "")), reverse=True)
    return adjusted



def _dominance_profile(candidates: list[dict[str, Any]], winner: dict[str, Any] | None, runner_up: dict[str, Any] | None) -> dict[str, Any]:
    groups = _candidate_value_groups(candidates)
    winner_group = groups.get(_candidate_group_key(winner.get("value"))) if isinstance(winner, dict) else None
    runner_group = groups.get(_candidate_group_key(runner_up.get("value"))) if isinstance(runner_up, dict) else None
    winner_total = float(winner_group.get("total_score", 0.0) or 0.0) if isinstance(winner_group, dict) else 0.0
    runner_total = float(runner_group.get("total_score", 0.0) or 0.0) if isinstance(runner_group, dict) else 0.0
    group_score_margin = winner_total - runner_total
    winner_sources = int(winner_group.get("independent_source_count", 0) or 0) if isinstance(winner_group, dict) else 0
    runner_sources = int(runner_group.get("independent_source_count", 0) or 0) if isinstance(runner_group, dict) else 0
    winner_count = int(winner_group.get("candidate_count", 0) or 0) if isinstance(winner_group, dict) else 0
    runner_count = int(runner_group.get("candidate_count", 0) or 0) if isinstance(runner_group, dict) else 0
    if runner_up is None:
        level = "strong" if winner_sources > 1 or winner_count > 1 else "single_source"
    elif group_score_margin >= 40.0 and winner_sources >= max(runner_sources, 1):
        level = "strong"
    elif group_score_margin >= 20.0 and winner_sources >= runner_sources:
        level = "moderate"
    elif group_score_margin > 0:
        level = "narrow"
    else:
        level = "contested"
    return {
        "winner_group_candidate_count": winner_count,
        "winner_group_independent_source_count": winner_sources,
        "winner_group_source_stream_count": int(winner_group.get("source_stream_count", 0) or 0) if isinstance(winner_group, dict) else 0,
        "winner_group_total_score": winner_total,
        "winner_group_exact_model_support_count": int(winner_group.get("exact_model_support_count", 0) or 0) if isinstance(winner_group, dict) else 0,
        "winner_group_official_source_count": int(winner_group.get("official_source_count", 0) or 0) if isinstance(winner_group, dict) else 0,
        "winner_group_applicant_support_count": int(winner_group.get("applicant_support_count", 0) or 0) if isinstance(winner_group, dict) else 0,
        "runner_up_group_candidate_count": runner_count,
        "runner_up_group_independent_source_count": runner_sources,
        "runner_up_group_total_score": runner_total,
        "group_score_margin": group_score_margin,
        "dominance_level": level,
        "has_multi_source_group_support": winner_sources > 1,
        "has_competing_multi_source_group": runner_sources > 1,
    }


def _score_gap(winner: dict[str, Any] | None, runner_up: dict[str, Any] | None) -> float:
    if not isinstance(winner, dict) or not isinstance(runner_up, dict):
        return 0.0
    return float(winner.get("score", 0.0) or 0.0) - float(runner_up.get("score", 0.0) or 0.0)


def _runner_up_profile(winner: dict[str, Any] | None, runner_up: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(runner_up, dict):
        return {}
    return {
        "candidate_id": str(runner_up.get("candidate_id", "")).strip(),
        "value": runner_up.get("value"),
        "unit": str(runner_up.get("unit", "")).strip(),
        "source_hierarchy": str(runner_up.get("source_hierarchy", "")).strip(),
        "specificity": str(runner_up.get("specificity", "")).strip(),
        "source_anchor": str(runner_up.get("source_anchor", "")).strip(),
        "source_stage": str(runner_up.get("source_stage", "")).strip(),
        "source_type": str(runner_up.get("source_type", "")).strip(),
        "score": float(runner_up.get("score", 0.0) or 0.0),
        "confidence": _safe_float(runner_up.get("confidence")),
        "group_candidate_count": int(runner_up.get("group_candidate_count", 0) or 0),
        "group_independent_source_count": int(runner_up.get("group_independent_source_count", 0) or 0),
        "group_source_stream_count": int(runner_up.get("group_source_stream_count", 0) or 0),
        "group_total_score": float(runner_up.get("group_total_score", 0.0) or 0.0),
        "not_accepted_reason": _alternative_reason(winner if isinstance(winner, dict) else {}, runner_up),
    }


def _conflict_profile(
    winner: dict[str, Any] | None,
    runner_up: dict[str, Any] | None,
    *,
    planner_critical: bool,
    conflict_materiality: str,
    dominance_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(winner, dict) or not isinstance(runner_up, dict):
        return {}
    numeric_delta_ratio = _numeric_material_difference(winner.get("value"), runner_up.get("value"))
    dominance = dominance_profile if isinstance(dominance_profile, dict) else _dominance_profile([winner, runner_up], winner, runner_up)
    source_delta = int(dominance.get("winner_group_independent_source_count", 0) or 0) - int(dominance.get("runner_up_group_independent_source_count", 0) or 0)
    hierarchy_delta = SOURCE_HIERARCHY_PRIORITY.get(str(winner.get("source_hierarchy", "")).strip(), 0) - SOURCE_HIERARCHY_PRIORITY.get(str(runner_up.get("source_hierarchy", "")).strip(), 0)
    specificity_delta = SPECIFICITY_PRIORITY.get(str(winner.get("specificity", "")).strip(), 0) - SPECIFICITY_PRIORITY.get(str(runner_up.get("specificity", "")).strip(), 0)
    score_gap = _score_gap(winner, runner_up)
    if conflict_materiality == "high":
        plausibility = "material_runner_up_conflict"
    elif conflict_materiality == "medium":
        plausibility = "credible_runner_up_conflict"
    elif score_gap <= 0:
        plausibility = "contested_runner_up_conflict"
    else:
        plausibility = "low_runner_up_conflict"
    summary_bits: list[str] = []
    if runner_up.get("value") is not None:
        summary_bits.append(f"Runner-up value {_stringify_value_for_reason(runner_up.get('value'))} remains plausible")
    if numeric_delta_ratio is not None:
        summary_bits.append(f"numeric delta {numeric_delta_ratio * 100:.1f}%")
    summary_bits.append(f"materiality={conflict_materiality}")
    summary_bits.append(f"group source delta={source_delta:+d}")
    return {
        "has_runner_up_conflict": True,
        "runner_up_value": runner_up.get("value"),
        "runner_up_source_hierarchy": str(runner_up.get("source_hierarchy", "")).strip(),
        "runner_up_specificity": str(runner_up.get("specificity", "")).strip(),
        "runner_up_source_anchor": str(runner_up.get("source_anchor", "")).strip(),
        "runner_up_group_independent_source_count": int(runner_up.get("group_independent_source_count", 0) or 0),
        "runner_up_group_candidate_count": int(runner_up.get("group_candidate_count", 0) or 0),
        "winner_vs_runner_up_score_gap": score_gap,
        "winner_vs_runner_up_group_source_delta": source_delta,
        "winner_vs_runner_up_hierarchy_delta": hierarchy_delta,
        "winner_vs_runner_up_specificity_delta": specificity_delta,
        "numeric_delta_ratio": numeric_delta_ratio,
        "conflict_materiality": conflict_materiality,
        "runner_up_plausibility": plausibility,
        "requires_applicant_decision": planner_critical and conflict_materiality in {"high", "medium"},
        "summary_text": "; ".join(summary_bits),
    }


def _applicant_question_profile(
    *,
    status: str,
    requiredness: str,
    planner_critical: bool,
    needs_confirmation: bool,
    planner_review_flag: bool,
    dominance_profile: dict[str, Any] | None,
    runner_up_profile: dict[str, Any] | None,
    conflict_profile: dict[str, Any] | None,
    unresolved_reason: str,
    acceptance_margin: float,
) -> dict[str, Any]:
    dominance = dominance_profile if isinstance(dominance_profile, dict) else {}
    runner_up = runner_up_profile if isinstance(runner_up_profile, dict) else {}
    conflict = conflict_profile if isinstance(conflict_profile, dict) else {}
    status_normalized = str(status).strip().lower() or "unresolved"
    required_normalized = str(requiredness).strip().lower() or "optional"
    conflict_materiality = str(conflict.get("conflict_materiality", "none")).strip().lower() or "none"
    dominance_level = str(dominance.get("dominance_level", "single_source")).strip().lower() or "single_source"

    if status_normalized == "missing":
        question_category = "missing"
        strategy = "fill_missing_required_value" if required_normalized == "required" else "fill_missing_optional_value"
        urgency = "blocker" if planner_critical or required_normalized == "required" else "follow_up"
    elif conflict_materiality == "high":
        question_category = "conflicting"
        strategy = "resolve_material_conflict"
        urgency = "blocker"
    elif status_normalized in {"conflicting", "review_required"}:
        question_category = "confirmation"
        strategy = "confirm_provisional_value"
        urgency = "high_priority" if planner_critical or needs_confirmation else "follow_up"
    elif needs_confirmation:
        question_category = "confirmation"
        strategy = "verify_best_supported_value"
        urgency = "high_priority" if planner_critical else "follow_up"
    else:
        question_category = "missing"
        strategy = "fill_unresolved_value"
        urgency = "follow_up"

    score = 0
    score += {"blocker": 520, "high_priority": 410, "follow_up": 300}.get(urgency, 250)
    if planner_critical:
        score += 70
    if required_normalized == "required":
        score += 40
    if planner_review_flag:
        score += 30
    if conflict_materiality == "high":
        score += 80
    elif conflict_materiality == "medium":
        score += 45
    if dominance_level in {"contested", "narrow", "single_source"}:
        score += 35
    score += min(max(int(acceptance_margin or 0.0), 0), 25)

    selection_rationale: list[str] = []
    if status_normalized == "missing":
        selection_rationale.append("Planner packet still lacks a usable accepted value for this field.")
    if conflict.get("requires_applicant_decision"):
        selection_rationale.append("Runner-up conflict is still material enough that the applicant should decide the final engineering value.")
    if planner_critical and planner_review_flag:
        selection_rationale.append("This field remains planner-critical and still carries review posture downstream.")
    if dominance_level in {"contested", "narrow", "single_source"}:
        selection_rationale.append(
            f"Current dominance posture is {dominance_level.replace('_', ' ')} with {int(dominance.get('winner_group_independent_source_count', 0) or 0)} independent source trace(s)."
        )
    if int(runner_up.get("group_independent_source_count", 0) or 0) > 0:
        selection_rationale.append(
            f"Runner-up support remains visible from {int(runner_up.get('group_independent_source_count', 0) or 0)} independent source trace(s)."
        )
    if unresolved_reason:
        selection_rationale.append(f"Unresolved reason: {unresolved_reason}")

    return {
        "question_category": question_category,
        "question_strategy": strategy,
        "interview_urgency": urgency,
        "interview_priority_score": score,
        "should_ask_now": bool(needs_confirmation or status_normalized in {"missing", "conflicting", "review_required", "unresolved"}),
        "selection_rationale": selection_rationale[:5],
        "accepted_value_snapshot": None,
        "runner_up_value_snapshot": runner_up.get("value") if isinstance(runner_up, dict) else None,
        "dominance_level": dominance_level,
        "conflict_materiality": conflict_materiality,
    }



def _planner_trust_row(
    *,
    label: str,
    accepted_value: Any,
    accepted_unit: str,
    status: str,
    confidence_band: str,
    planner_critical: bool,
    planner_review_flag: bool,
    needs_confirmation: bool,
    dominance_profile: dict[str, Any] | None,
    runner_up_profile: dict[str, Any] | None,
    conflict_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    dominance = dominance_profile if isinstance(dominance_profile, dict) else {}
    runner_up = runner_up_profile if isinstance(runner_up_profile, dict) else {}
    conflict = conflict_profile if isinstance(conflict_profile, dict) else {}
    status_normalized = str(status).strip().lower() or "unresolved"
    dominance_level = str(dominance.get("dominance_level", "single_source")).strip().lower() or "single_source"
    conflict_materiality = str(conflict.get("conflict_materiality", "none")).strip().lower() or "none"

    if status_normalized == "resolved" and not planner_review_flag and not needs_confirmation:
        trust_posture = "settled"
    elif status_normalized in {"conflicting", "review_required"} or conflict_materiality in {"high", "medium"}:
        trust_posture = "contested"
    elif status_normalized == "missing":
        trust_posture = "missing"
    else:
        trust_posture = "provisional"

    planner_action = (
        "ask_applicant_now"
        if needs_confirmation and conflict_materiality in {"high", "medium"}
        else "planner_review_before_use"
        if planner_review_flag or status_normalized in {"conflicting", "review_required", "unresolved"}
        else "use_with_traceability"
    )

    support_summary = (
        f"winner_sources={int(dominance.get('winner_group_independent_source_count', 0) or 0)}; "
        f"runner_up_sources={int(runner_up.get('group_independent_source_count', 0) or 0)}; "
        f"dominance={dominance_level}"
    )

    return {
        "label": label,
        "accepted_value": accepted_value,
        "accepted_unit": accepted_unit,
        "status": status_normalized,
        "confidence_band": str(confidence_band).strip() or "UNRESOLVED",
        "trust_posture": trust_posture,
        "planner_action": planner_action,
        "support_summary": support_summary,
        "runner_up_value": runner_up.get("value") if isinstance(runner_up, dict) else None,
        "runner_up_plausibility": str(conflict.get("runner_up_plausibility", "")).strip(),
        "planner_critical": planner_critical,
    }



def _acceptance_policy_result(
    *,
    winner: dict[str, Any] | None,
    runner_up: dict[str, Any] | None,
    status: str,
    confidence: float | None,
    planner_critical: bool,
    requiredness: str,
    conflict_materiality: str,
    dominance_profile: dict[str, Any] | None,
    validation_impacts: list[dict[str, Any]] | None,
    field_policy_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    dominance = dominance_profile if isinstance(dominance_profile, dict) else {}
    impacts = validation_impacts if isinstance(validation_impacts, list) else []
    status_normalized = str(status).strip().lower() or "unresolved"
    required_normalized = str(requiredness).strip().lower() or "optional"
    materiality = str(conflict_materiality).strip().lower() or "none"
    winner_sources = int(dominance.get("winner_group_independent_source_count", 0) or 0)
    winner_streams = int(dominance.get("winner_group_source_stream_count", 0) or 0)
    exact_model_support = int(dominance.get("winner_group_exact_model_support_count", 0) or 0)
    official_support = int(dominance.get("winner_group_official_source_count", 0) or 0)
    applicant_support = int(dominance.get("winner_group_applicant_support_count", 0) or 0)
    dominance_level = str(dominance.get("dominance_level", "single_source")).strip().lower() or "single_source"
    group_score_margin = float(dominance.get("group_score_margin", 0.0) or 0.0)
    specificity = str((winner or {}).get("specificity", "")).strip().lower() if isinstance(winner, dict) else ""
    source_hierarchy = str((winner or {}).get("source_hierarchy", "")).strip().lower() if isinstance(winner, dict) else ""
    validation_error_count = len([item for item in impacts if str(item.get("severity", "")).strip().lower() == "error"])
    validation_warning_count = len([item for item in impacts if str(item.get("severity", "")).strip().lower() == "warning"])
    policy_profile = field_policy_profile if isinstance(field_policy_profile, dict) else {}
    field_class = str(policy_profile.get("field_class", "planner_critical" if planner_critical else "supporting")).strip().lower() or ("planner_critical" if planner_critical else "supporting")
    materiality_class = str(policy_profile.get("materiality_class", "supporting_context")).strip().lower() or "supporting_context"
    threshold = float(policy_profile.get("confidence_threshold", 0.80 if planner_critical else 0.62) or (0.80 if planner_critical else 0.62))
    minimum_independent_sources = int(policy_profile.get("minimum_independent_sources", 1) or 1)
    medium_conflict_blocks = bool(policy_profile.get("medium_conflict_blocks", False))
    narrow_single_source_is_provisional = bool(policy_profile.get("narrow_single_source_is_provisional", True))
    threshold_met = bool(winner is not None and winner.get("value") is not None and confidence is not None and confidence >= threshold)
    strong_direct_document = bool(
        winner is not None
        and winner.get("value") is not None
        and source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_confirmed_answer"}
        and specificity in {"direct_field_match", "exact_instance_match", "exact_model_match"}
        and confidence is not None
        and confidence >= max(0.72, threshold - 0.12)
        and materiality not in {"high"}
    )
    corroborated_direct_document = bool(
        winner is not None
        and winner.get("value") is not None
        and winner_sources >= 2
        and source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_inferred_document"}
        and confidence is not None
        and confidence >= max(0.68, threshold - 0.18)
        and materiality not in {"high", "medium"}
    )
    effective_threshold_met = threshold_met or strong_direct_document or corroborated_direct_document

    strength_points = 0
    if effective_threshold_met:
        strength_points += 3
    elif confidence is not None and confidence >= max(threshold - 0.08, 0.0):
        strength_points += 2
    elif confidence is not None and confidence >= 0.45:
        strength_points += 1
    self_supporting = (
        source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_confirmed_answer", "manufacturer_model_specific_spec"}
        and specificity in {"exact_model_match", "exact_instance_match", "direct_field_match"}
    )
    if winner_sources >= max(minimum_independent_sources, 2):
        strength_points += 2
    elif winner_sources >= 1:
        strength_points += 1
    if winner_sources < minimum_independent_sources and not self_supporting:
        strength_points -= 2 if field_class == "planner_critical" else 1
    if winner_streams >= 2:
        strength_points += 1
    if exact_model_support > 0 or specificity in {"exact_model_match", "exact_instance_match"}:
        strength_points += 2
    elif specificity == "direct_field_match":
        strength_points += 1
    if source_hierarchy in {"applicant_direct_document", "manufacturer_model_specific_spec", "official_interconnection_source", "applicant_confirmed_answer"}:
        strength_points += 2
    elif source_hierarchy in {"applicant_inferred_document", "manufacturer_family_spec", "vendor_pdf"}:
        strength_points += 1
    if official_support > 0:
        strength_points += 1
    if applicant_support > 0:
        strength_points += 1
    if dominance_level == "strong":
        strength_points += 2
    elif dominance_level == "moderate":
        strength_points += 1
    if materiality == "high":
        strength_points -= 4
    elif materiality == "medium":
        strength_points -= 3 if medium_conflict_blocks else 2
    if validation_error_count:
        strength_points -= 3
    elif validation_warning_count:
        strength_points -= 1

    if strength_points >= 9:
        support_strength_tier = "HIGH"
    elif strength_points >= 6:
        support_strength_tier = "MODERATE"
    elif strength_points >= 3:
        support_strength_tier = "LOW"
    else:
        support_strength_tier = "WEAK"

    if winner is None or winner.get("value") is None:
        outcome = "blocked_insufficient_support"
        recommended_status = "missing" if required_normalized != "optional" else "unresolved"
    elif validation_error_count and planner_critical:
        outcome = "blocked_conflict"
        recommended_status = "conflicting"
    elif materiality == "high":
        outcome = "blocked_conflict"
        recommended_status = "conflicting"
    elif materiality == "medium" and medium_conflict_blocks:
        outcome = "blocked_conflict"
        recommended_status = "conflicting"
    elif not effective_threshold_met and required_normalized != "optional":
        outcome = "blocked_insufficient_support"
        recommended_status = "review_required"
    elif winner_sources < minimum_independent_sources and required_normalized != "optional" and field_class in {"planner_critical", "planner_relevant"} and not self_supporting:
        outcome = "blocked_insufficient_support"
        recommended_status = "review_required"
    elif materiality == "medium" or validation_warning_count or (narrow_single_source_is_provisional and dominance_level in {"single_source", "narrow"} and not self_supporting):
        outcome = "accepted_provisional"
        recommended_status = "review_required"
    elif source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_confirmed_answer"} and support_strength_tier == "HIGH":
        outcome = "accepted_confirmed"
        recommended_status = "resolved"
    else:
        outcome = "accepted_inferred"
        recommended_status = "resolved"

    reasons = []
    if winner is None or winner.get("value") is None:
        reasons.append("No usable accepted-value candidate exists yet.")
    else:
        reasons.append(f"Support tier evaluated as {support_strength_tier} using source hierarchy, specificity, agreement, and conflict checks.")
        if threshold_met:
            reasons.append(f"Winner confidence cleared the governed threshold ({threshold:.2f}).")
        else:
            reasons.append(f"Winner confidence did not clear the governed threshold ({threshold:.2f}).")
        if winner_sources > 0:
            reasons.append(f"Winner group is backed by {winner_sources} independent source trace(s) across {max(winner_streams, 1)} source stream(s).")
        if winner_sources < minimum_independent_sources and not self_supporting:
            reasons.append(f"Field policy expects at least {minimum_independent_sources} independent source trace(s) for this field class.")
        elif winner_sources < minimum_independent_sources and self_supporting:
            reasons.append("Single-source support is acceptable here because the winner is a direct or exact high-trust source.")
        if materiality in {"high", "medium"}:
            reasons.append(f"Competing evidence remains {materiality} material.")
        if validation_error_count:
            reasons.append("Validation errors still affect this field.")
        elif validation_warning_count:
            reasons.append("Validation warnings still affect this field.")
    required_next_action = (
        "obtain_applicant_clarification"
        if outcome in {"blocked_conflict", "accepted_provisional"} and planner_critical
        else "planner_review"
        if outcome in {"blocked_conflict", "blocked_insufficient_support", "accepted_provisional"}
        else "none"
    )
    return {
        "policy_version": "field_acceptance_v2",
        "outcome": outcome,
        "status_recommendation": recommended_status,
        "acceptance_threshold_met": effective_threshold_met,
        "raw_confidence_threshold_met": threshold_met,
        "direct_document_threshold_relief": strong_direct_document,
        "corroborated_document_threshold_relief": corroborated_direct_document,
        "support_strength_tier": support_strength_tier,
        "confidence_threshold": threshold,
        "field_class": field_class,
        "materiality_class": materiality_class,
        "minimum_independent_sources": minimum_independent_sources,
        "conflict_materiality": materiality,
        "winner_source_hierarchy": source_hierarchy,
        "winner_specificity": specificity,
        "winner_independent_source_count": winner_sources,
        "winner_source_stream_count": winner_streams,
        "dominance_level": dominance_level,
        "group_score_margin": group_score_margin,
        "validation_error_count": validation_error_count,
        "validation_warning_count": validation_warning_count,
        "required_next_action": required_next_action,
        "reasons": reasons,
    }

def _field_release_profile(
    *,
    accepted_value: Any,
    status: str,
    planner_critical: bool,
    planner_review_flag: bool,
    needs_confirmation: bool,
    confidence_band: str,
    applicant_question_profile: dict[str, Any] | None,
    planner_trust_row: dict[str, Any] | None,
    conflict_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    question_profile = applicant_question_profile if isinstance(applicant_question_profile, dict) else {}
    trust_row = planner_trust_row if isinstance(planner_trust_row, dict) else {}
    conflict = conflict_profile if isinstance(conflict_profile, dict) else {}
    status_normalized = str(status).strip().lower() or "unresolved"
    confidence = str(confidence_band).strip().upper() or "UNRESOLVED"
    trust_posture = str(trust_row.get("trust_posture", "provisional")).strip().lower() or "provisional"
    planner_action = str(trust_row.get("planner_action", "planner_review_before_use")).strip() or "planner_review_before_use"
    conflict_materiality = str(conflict.get("conflict_materiality", "none")).strip().lower() or "none"

    if accepted_value is None or status_normalized in {"missing", "conflicting"}:
        release_state = "BLOCKED"
        export_readiness_tier = "blocked"
        translation_use_policy = "hold_from_modeled_output"
        scenario_use_policy = "hold_for_review_variant_only"
        planner_packet_use_policy = "show_as_unresolved"
    elif planner_critical and (planner_review_flag or needs_confirmation or status_normalized in {"review_required", "unresolved"}):
        release_state = "BLOCKED"
        export_readiness_tier = "blocked"
        translation_use_policy = "hold_from_modeled_output"
        scenario_use_policy = "hold_for_review_variant_only"
        planner_packet_use_policy = "show_as_provisional_with_blocker"
    elif planner_review_flag or needs_confirmation or status_normalized in {"review_required", "unresolved"}:
        release_state = "PROVISIONAL"
        export_readiness_tier = "provisional"
        translation_use_policy = "use_with_provisional_tag"
        scenario_use_policy = "use_with_review_variant"
        planner_packet_use_policy = "show_as_provisional"
    else:
        release_state = "READY"
        export_readiness_tier = "auto_acceptable"
        translation_use_policy = "use_in_modeled_output"
        scenario_use_policy = "use_in_modeled_output"
        planner_packet_use_policy = "show_as_accepted"

    reasons: list[str] = []
    if accepted_value is None:
        reasons.append("No accepted value is available for modeled use.")
    elif release_state == "READY":
        reasons.append("Field cleared governed adjudication for modeled downstream use.")
    elif release_state == "PROVISIONAL":
        reasons.append("Field may proceed only with explicit provisional tagging and review traceability.")
    else:
        reasons.append("Field is not safe for modeled downstream use until the governing blocker is resolved.")
    if planner_critical:
        reasons.append("Planner-critical posture is enforced for this field.")
    if planner_review_flag:
        reasons.append("Planner review remains required before treated use.")
    if needs_confirmation:
        reasons.append("Applicant confirmation is still recommended before relying on the value.")
    if conflict_materiality in {"high", "medium"}:
        reasons.append(f"Competing evidence remains {conflict_materiality} material.")
    targeting_summary = str(question_profile.get("targeting_summary", "")).strip()
    if targeting_summary:
        reasons.append(targeting_summary)

    return {
        "release_state": release_state,
        "export_readiness_tier": export_readiness_tier,
        "translation_use_policy": translation_use_policy,
        "scenario_use_policy": scenario_use_policy,
        "planner_packet_use_policy": planner_packet_use_policy,
        "planner_action": planner_action,
        "trust_posture": trust_posture,
        "confidence_band": confidence,
        "conflict_materiality": conflict_materiality,
        "reason_summary": " ".join(dict.fromkeys(reasons)),
        "blocking": release_state == "BLOCKED",
        "provisional": release_state == "PROVISIONAL",
    }


def _adjudication_next_action(*, field_release_profile: dict[str, Any] | None, applicant_question_profile: dict[str, Any] | None) -> dict[str, Any]:
    release = field_release_profile if isinstance(field_release_profile, dict) else {}
    question = applicant_question_profile if isinstance(applicant_question_profile, dict) else {}
    release_state = str(release.get("release_state", "")).strip().upper()
    planner_action = str(release.get("planner_action", "")).strip() or "planner_review_before_use"
    should_ask_now = bool(question.get("should_ask_now", False))
    strategy = str(question.get("question_strategy", "")).strip() or "none"
    if release_state == "BLOCKED" and should_ask_now:
        owner = "applicant"
        action = "ask_applicant_now"
    elif release_state == "BLOCKED":
        owner = "planner"
        action = "planner_review_before_use"
    elif release_state == "PROVISIONAL":
        owner = "planner"
        action = "use_with_provisional_tag"
    else:
        owner = "system"
        action = "use_as_accepted"
    rationale = str(release.get("reason_summary", "")).strip()
    return {
        "owner": owner,
        "action": action,
        "planner_action": planner_action,
        "question_strategy": strategy,
        "summary": rationale or f"Next action is {action}.",
    }


def _adjudication_trace(*, label: str, accepted_value: Any, accepted_unit: str, status: str, confidence_band: str, why_accepted: list[str] | None, runner_up_profile: dict[str, Any] | None, conflict_profile: dict[str, Any] | None, applicant_question_profile: dict[str, Any] | None, field_release_profile: dict[str, Any] | None) -> dict[str, Any]:
    why = [str(item).strip() for item in (why_accepted or []) if str(item).strip()]
    runner_up = runner_up_profile if isinstance(runner_up_profile, dict) else {}
    conflict = conflict_profile if isinstance(conflict_profile, dict) else {}
    release = field_release_profile if isinstance(field_release_profile, dict) else {}
    next_action = _adjudication_next_action(field_release_profile=release, applicant_question_profile=applicant_question_profile)
    accepted_value_text = _stringify_value_for_reason(accepted_value)
    accepted_with_unit = accepted_value_text + (f" {str(accepted_unit).strip()}" if str(accepted_unit).strip() else "")
    winner_summary = why[0] if why else "No explicit winner rationale recorded."
    runner_up_value = runner_up.get("value")
    runner_up_loss_reason = str(runner_up.get("not_accepted_reason", "")).strip()
    runner_up_summary = ""
    if runner_up_value is not None:
        runner_up_summary = f"Runner-up {_stringify_value_for_reason(runner_up_value)} lost because {runner_up_loss_reason or 'it ranked below the accepted value.'}"
    conflict_summary = str(conflict.get("summary_text", "")).strip()
    planner_narrative_parts = [
        f"{label} accepted {accepted_with_unit} with status {str(status).strip().lower() or 'unresolved'} and confidence {str(confidence_band).strip() or 'UNRESOLVED'}.",
        winner_summary,
    ]
    if runner_up_summary:
        planner_narrative_parts.append(runner_up_summary)
    if conflict_summary:
        planner_narrative_parts.append(conflict_summary)
    if next_action.get("summary"):
        planner_narrative_parts.append(str(next_action.get("summary")))
    return {
        "accepted_value_text": accepted_with_unit,
        "winner_summary": winner_summary,
        "winner_reason_chain": why[:3],
        "runner_up_value": runner_up_value,
        "runner_up_loss_reason": runner_up_loss_reason,
        "runner_up_summary": runner_up_summary,
        "conflict_summary": conflict_summary,
        "release_summary": str(release.get("reason_summary", "")).strip(),
        "next_action": next_action,
        "planner_narrative": " ".join(part for part in planner_narrative_parts if part),
    }


def _numeric_material_difference(left: Any, right: Any) -> float | None:
    left_num = _safe_float(left)
    right_num = _safe_float(right)
    if left_num is None or right_num is None:
        return None
    baseline = max(abs(left_num), abs(right_num), 1.0)
    return abs(left_num - right_num) / baseline


def _conflict_materiality(
    winner: dict[str, Any] | None,
    runner_up: dict[str, Any] | None,
    *,
    planner_critical: bool,
    field_policy_profile: dict[str, Any] | None = None,
    applicant_force_review: bool = False,
) -> str:
    if not isinstance(winner, dict) or not isinstance(runner_up, dict):
        return "none"
    policy_profile = field_policy_profile if isinstance(field_policy_profile, dict) else {}
    field_class = str(policy_profile.get("field_class", "planner_critical" if planner_critical else "supporting")).strip().lower() or ("planner_critical" if planner_critical else "supporting")
    materiality_class = str(policy_profile.get("materiality_class", "supporting_context")).strip().lower() or "supporting_context"
    if _canonical_value(winner.get("value")) == _canonical_value(runner_up.get("value")):
        return "none"
    gap = _score_gap(winner, runner_up)
    numeric_delta = _numeric_material_difference(winner.get("value"), runner_up.get("value"))
    if applicant_force_review:
        return "high"
    if numeric_delta is not None:
        if materiality_class == "topology_configuration":
            if numeric_delta >= 0.01:
                return "high" if field_class == "planner_critical" else "medium"
        elif materiality_class == "electrical_numeric":
            if numeric_delta >= (0.03 if field_class == "planner_critical" else 0.08):
                return "high"
            if numeric_delta >= (0.01 if field_class == "planner_critical" else 0.03):
                return "medium"
        else:
            if planner_critical and numeric_delta >= 0.10:
                return "high"
            if numeric_delta >= 0.25:
                return "high"
            if numeric_delta >= 0.05:
                return "medium"
        return "low" if gap < 18.0 else "none"
    if materiality_class == "topology_configuration":
        if gap < 18.0:
            return "high" if field_class == "planner_critical" else "medium"
        if gap < 28.0:
            return "medium"
    if gap < 10.0:
        return "high" if planner_critical else "medium"
    if gap < 18.0:
        return "medium" if planner_critical else "low"
    return "low"


def _unresolved_reason(
    *,
    status: str,
    winner: dict[str, Any] | None,
    runner_up: dict[str, Any] | None,
    planner_critical: bool,
    applicant_force_review: bool,
    conflict_materiality: str,
) -> str:
    if status == "missing":
        return "No accepted value was available for this planner field."
    if status == "unresolved":
        return "Optional field remains unresolved because no strong supported candidate was found."
    if status == "conflicting":
        if applicant_force_review:
            return "Applicant-confirmed evidence conflicts with other plausible values and must be reviewed."
        if conflict_materiality == "high":
            return "Top candidates disagree materially on a planner-relevant value."
        return "Top candidates disagree and the score margin is too narrow for safe auto-acceptance."
    if status == "review_required":
        winner_conf = _safe_float(winner.get("confidence")) if isinstance(winner, dict) else None
        if applicant_force_review:
            return "Accepted value is provisional because applicant evidence contradicts other sources."
        if planner_critical and winner_conf is not None and winner_conf < 0.75:
            return "Planner-critical field did not clear the governed confidence threshold."
        if runner_up is not None and conflict_materiality in {"medium", "high"}:
            return "Accepted value is provisional because competing evidence remains materially plausible."
        return "Accepted value is provisional and should be reviewed before planner use."
    return ""




def _winner_requires_support_review(winner: dict[str, Any] | None, *, planner_critical: bool) -> bool:
    if not isinstance(winner, dict):
        return False
    metadata = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
    source_stage = str(winner.get("source_stage", "")).strip().lower()
    source_hierarchy = str(winner.get("source_hierarchy", "")).strip()
    specificity = str(winner.get("specificity", "")).strip()
    corroboration_count = int(winner.get("corroboration_count", 1) or 1)
    weak_support_only = bool(metadata.get("weak_support_only", False))
    field_support_strength = str(metadata.get("field_support_strength", "")).strip().upper()
    if weak_support_only and planner_critical:
        return True
    if source_stage == "retrieval" and field_support_strength == "LOW" and corroboration_count <= 1:
        return True
    if source_hierarchy in {"secondary_web", "official_website"} and specificity == "context_inferred" and corroboration_count <= 1 and planner_critical:
        return True
    return False

def _accepted_status(
    candidates: list[dict[str, Any]],
    *,
    planner_critical: bool,
    requiredness: str,
    applicant_force_review: bool = False,
    dominance_profile: dict[str, Any] | None = None,
    field_policy_profile: dict[str, Any] | None = None,
) -> str:
    if not candidates:
        return "missing" if requiredness != "optional" else "unresolved"
    distinct_values = {
        _canonical_value(item.get("value"))
        for item in candidates
        if item.get("value") is not None
    }
    winner = candidates[0]
    winner_conf = _safe_float(winner.get("confidence"))
    if winner.get("value") is None:
        return "missing" if requiredness != "optional" else "unresolved"
    runner_up = candidates[1] if len(candidates) > 1 else None
    policy_profile = field_policy_profile if isinstance(field_policy_profile, dict) else {}
    field_class = str(policy_profile.get("field_class", "planner_critical" if planner_critical else "supporting")).strip().lower() or ("planner_critical" if planner_critical else "supporting")
    minimum_independent_sources = int(policy_profile.get("minimum_independent_sources", 1) or 1)
    medium_conflict_blocks = bool(policy_profile.get("medium_conflict_blocks", False))
    materiality = _conflict_materiality(winner, runner_up, planner_critical=planner_critical, field_policy_profile=policy_profile, applicant_force_review=applicant_force_review)
    dominance = dominance_profile if isinstance(dominance_profile, dict) else _dominance_profile(candidates, winner, runner_up)
    dominance_level = str(dominance.get("dominance_level", "single_source")).strip().lower() or "single_source"
    winner_group_sources = int(dominance.get("winner_group_independent_source_count", 0) or 0)
    runner_group_sources = int(dominance.get("runner_up_group_independent_source_count", 0) or 0)
    group_score_margin = float(dominance.get("group_score_margin", 0.0) or 0.0)
    source_hierarchy = str(winner.get("source_hierarchy", "")).strip().lower()
    specificity = str(winner.get("specificity", "")).strip().lower()
    if len(distinct_values) > 1 and runner_up is not None:
        gap = _score_gap(winner, runner_up)
        if materiality == "high":
            return "conflicting"
        if planner_critical and dominance_level == "contested":
            return "conflicting"
        if planner_critical and dominance_level == "narrow" and runner_group_sources >= max(winner_group_sources, 1):
            return "review_required"
        if runner_group_sources > winner_group_sources and group_score_margin < 25.0:
            return "review_required"
        if materiality == "medium" and (medium_conflict_blocks or planner_critical or gap < 15.0):
            return "conflicting" if medium_conflict_blocks else "review_required"
        if gap < 12.0:
            return "conflicting"
    threshold = float(policy_profile.get("confidence_threshold", 0.75 if planner_critical else 0.60) or (0.75 if planner_critical else 0.60))
    if applicant_force_review:
        return "review_required"
    strong_direct_document = (
        source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_confirmed_answer"}
        and specificity in {"direct_field_match", "exact_instance_match", "exact_model_match"}
        and (winner_conf or 0.0) >= max(0.72, threshold - 0.12)
        and materiality not in {"high"}
    )
    corroborated_direct_document = (
        winner_group_sources >= 2
        and source_hierarchy in {"applicant_direct_document", "official_interconnection_source", "applicant_inferred_document"}
        and (winner_conf or 0.0) >= max(0.68, threshold - 0.18)
        and materiality not in {"high", "medium"}
    )
    if winner_conf is None or winner_conf < threshold:
        if strong_direct_document or corroborated_direct_document:
            return "resolved"
        return "review_required"
    if field_class in {"planner_critical", "planner_relevant"} and winner_group_sources < minimum_independent_sources and runner_up is not None:
        if strong_direct_document:
            return "resolved"
        return "review_required"
    if planner_critical and dominance_level in {"single_source", "narrow"} and winner_group_sources <= 1 and runner_up is not None:
        return "review_required"
    if _winner_requires_support_review(winner, planner_critical=planner_critical):
        return "review_required"
    return "resolved"


def _why_accepted(winner: dict[str, Any], runner_up: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    specificity = str(winner.get("specificity", "")).strip()
    if specificity:
        reasons.append(f"Selected candidate had {specificity.replace('_', ' ')} evidence.")
    source_hierarchy = str(winner.get("source_hierarchy", "")).strip()
    if source_hierarchy:
        reasons.append(f"Source hierarchy favored {source_hierarchy.replace('_', ' ')}.")
    source_type = str(winner.get("source_type", "")).strip()
    source_stage = str(winner.get("source_stage", "")).strip()
    if source_stage or source_type:
        reasons.append(f"Source ranked highest from {source_stage or 'unknown stage'} / {source_type or 'unknown type'}.")
    corroboration_count = int(winner.get("corroboration_count", 1) or 1)
    if corroboration_count > 1:
        reasons.append(f"Value was corroborated by {corroboration_count} candidate records.")
    group_candidate_count = int(winner.get("group_candidate_count", 0) or 0)
    group_source_count = int(winner.get("group_independent_source_count", 0) or 0)
    if group_candidate_count > 1 or group_source_count > 1:
        reasons.append(
            f"Accepted value clustered across {max(group_candidate_count, 1)} candidate records from {max(group_source_count, 1)} independent source traces."
        )
    if str(winner.get("source_hierarchy", "")).strip() == "applicant_confirmed_answer":
        reasons.append("Applicant-confirmed interview evidence supports this value.")
    winner_metadata = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
    if str(winner_metadata.get("source_priority", "")).strip().lower() == "official_web_executed" or int(winner_metadata.get("group_executed_official_web_count", 0) or 0) > 0:
        reasons.append("Executed official web retrieval was captured and ranked as governed supporting evidence.")
    if str(winner_metadata.get("source_method", "")).strip().lower().startswith("interconnection_study.") or int(winner_metadata.get("group_promoted_interconnection_fact_count", 0) or 0) > 0:
        reasons.append("Value came from explicit interconnection-study promotion rather than loose text only.")
    if int(winner.get("group_independent_source_count", 0) or 0) > 1 and (
        str(winner.get("source_hierarchy", "")).strip() in {"official_interconnection_source", "applicant_direct_document"}
        or int(winner_metadata.get("group_official_source_count", 0) or 0) > 0
    ):
        reasons.append("Accepted value was reinforced by multiple independent governed source traces.")
    for note in winner.get("consistency_notes", [])[:3] if isinstance(winner.get("consistency_notes"), list) else []:
        reasons.append(note)
    if runner_up is not None:
        score_gap = _score_gap(winner, runner_up)
        reasons.append(f"Winner exceeded runner-up by {score_gap:.1f} score points.")
    anchor = str(winner.get("source_anchor", "")).strip()
    if anchor:
        reasons.append(f"Primary anchor: {anchor}.")
    return reasons


def _candidate_evidence_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.get("candidate_id", "")).strip(),
        "value": candidate.get("value"),
        "source_stream": str(candidate.get("source_stream", "")).strip(),
        "source_hierarchy": str(candidate.get("source_hierarchy", "")).strip(),
        "source_anchor": str(candidate.get("source_anchor", "")).strip(),
        "specificity": str(candidate.get("specificity", "")).strip(),
        "score": float(candidate.get("score", 0.0) or 0.0),
        "confidence": _safe_float(candidate.get("confidence")),
        "confidence_band": str(candidate.get("confidence_band", "UNRESOLVED")).strip() or "UNRESOLVED",
        "consistency_notes": list(candidate.get("consistency_notes", [])) if isinstance(candidate.get("consistency_notes"), list) else [],
        "group_candidate_count": int(candidate.get("group_candidate_count", 0) or 0),
        "group_independent_source_count": int(candidate.get("group_independent_source_count", 0) or 0),
        "group_source_stream_count": int(candidate.get("group_source_stream_count", 0) or 0),
        "group_agreement_boost": float(candidate.get("group_agreement_boost", 0.0) or 0.0),
        "not_accepted_reason": str(candidate.get("not_accepted_reason", "")).strip(),
    }


def _governance_posture_summary(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    release_state_counts: Counter[str] = Counter()
    export_readiness_tier_counts: Counter[str] = Counter()
    materiality_class_counts: Counter[str] = Counter()
    source_hierarchy_counts: Counter[str] = Counter()
    policy_outcome_counts: Counter[str] = Counter()
    blocked_fields: list[dict[str, Any]] = []
    provisional_fields: list[dict[str, Any]] = []
    meaningful_alternative_count = 0

    for item in ledger:
        if not isinstance(item, dict):
            continue
        release_profile = item.get("field_release_profile") if isinstance(item.get("field_release_profile"), dict) else {}
        acceptance_policy = item.get("acceptance_policy_result") if isinstance(item.get("acceptance_policy_result"), dict) else {}
        release_state = str(release_profile.get("release_state", "UNKNOWN")).strip().upper() or "UNKNOWN"
        export_tier = str(release_profile.get("export_readiness_tier", "unknown")).strip().lower() or "unknown"
        materiality_class = str(item.get("field_materiality_class", "supporting_context")).strip().lower() or "supporting_context"
        source_hierarchy = str(item.get("accepted_source_hierarchy", "unknown")).strip().lower() or "unknown"
        policy_outcome = str(acceptance_policy.get("outcome", "unknown")).strip().lower() or "unknown"

        release_state_counts[release_state] += 1
        export_readiness_tier_counts[export_tier] += 1
        materiality_class_counts[materiality_class] += 1
        source_hierarchy_counts[source_hierarchy] += 1
        policy_outcome_counts[policy_outcome] += 1

        alternatives = item.get("alternatives", []) if isinstance(item.get("alternatives"), list) else []
        if alternatives:
            meaningful_alternative_count += 1

        entry = {
            "field_id": str(item.get("field_id", "")).strip(),
            "field_path": str(item.get("field_path", "")).strip(),
            "label": str(item.get("label", "")).strip(),
            "accepted_status": str(item.get("accepted_status", "unresolved")).strip().lower() or "unresolved",
            "planner_critical": bool(item.get("planner_critical", False)),
            "confidence_band": str(item.get("confidence_band", "UNRESOLVED")).strip().upper() or "UNRESOLVED",
            "release_state": release_state,
            "export_readiness_tier": export_tier,
            "conflict_materiality": str(item.get("conflict_materiality", "none")).strip().lower() or "none",
            "planner_attention_tier": str(item.get("planner_attention_tier", "information")).strip().lower() or "information",
            "accepted_source_hierarchy": source_hierarchy,
        }
        if release_state == "BLOCKED":
            blocked_fields.append(entry)
        elif release_state == "PROVISIONAL":
            provisional_fields.append(entry)

    blocked_fields.sort(key=lambda entry: (0 if entry.get("planner_critical") else 1, entry.get("label", ""), entry.get("field_path", "")))
    provisional_fields.sort(key=lambda entry: (0 if entry.get("planner_critical") else 1, entry.get("label", ""), entry.get("field_path", "")))

    return {
        "release_state_counts": dict(sorted(release_state_counts.items())),
        "export_readiness_tier_counts": dict(sorted(export_readiness_tier_counts.items())),
        "materiality_class_counts": dict(sorted(materiality_class_counts.items())),
        "accepted_source_hierarchy_counts": dict(sorted(source_hierarchy_counts.items())),
        "policy_outcome_counts": dict(sorted(policy_outcome_counts.items())),
        "blocked_field_count": len(blocked_fields),
        "provisional_field_count": len(provisional_fields),
        "meaningful_alternative_field_count": meaningful_alternative_count,
        "blocked_fields_top": blocked_fields[:10],
        "provisional_fields_top": provisional_fields[:10],
    }

def _alternative_reason(winner: dict[str, Any], alternative: dict[str, Any]) -> str:
    reasons: list[str] = []
    score_gap = _score_gap(winner, alternative)
    if score_gap > 0:
        reasons.append(f"Score trailed accepted candidate by {score_gap:.1f} points.")
    alt_hierarchy = SOURCE_HIERARCHY_PRIORITY.get(str(alternative.get("source_hierarchy", "")).strip(), 0)
    win_hierarchy = SOURCE_HIERARCHY_PRIORITY.get(str(winner.get("source_hierarchy", "")).strip(), 0)
    if alt_hierarchy < win_hierarchy:
        reasons.append("Source hierarchy ranked below the accepted candidate.")
    alt_specificity = SPECIFICITY_PRIORITY.get(str(alternative.get("specificity", "")).strip(), 0)
    win_specificity = SPECIFICITY_PRIORITY.get(str(winner.get("specificity", "")).strip(), 0)
    if alt_specificity < win_specificity:
        reasons.append("Specificity was weaker than the accepted candidate.")
    alt_group_sources = int(alternative.get("group_independent_source_count", 0) or 0)
    win_group_sources = int(winner.get("group_independent_source_count", 0) or 0)
    if alt_group_sources < win_group_sources:
        reasons.append("Cross-source agreement was weaker than the accepted candidate.")
    if any(isinstance(note, str) and note for note in alternative.get("consistency_notes", []) or []):
        reasons.append("Context consistency was weaker or conflicted with related evidence.")
    return " ".join(reasons) or "Accepted candidate ranked stronger after adjudication."



def _applicant_answer_state(candidates: list[dict[str, Any]], winner: dict[str, Any] | None) -> tuple[str, str, bool]:
    applicant_candidates = [
        item for item in candidates
        if str(item.get("source_hierarchy", "")).strip() == "applicant_confirmed_answer"
    ]
    if not applicant_candidates:
        return "", "", False
    if winner is None:
        return "applicant_followup_needed", "Applicant answer exists but no accepted value was resolved.", True
    winner_value = _canonical_value(winner.get("value"))
    matching = [item for item in applicant_candidates if _canonical_value(item.get("value")) == winner_value]
    conflicting = [item for item in applicant_candidates if _canonical_value(item.get("value")) != winner_value]
    non_applicant_conflicts = [
        item for item in candidates
        if str(item.get("source_hierarchy", "")).strip() != "applicant_confirmed_answer"
        and _canonical_value(item.get("value")) != winner_value
    ]
    if str(winner.get("source_hierarchy", "")).strip() == "applicant_confirmed_answer":
        if conflicting or non_applicant_conflicts:
            return (
                "applicant_override_selected",
                "Applicant-confirmed value was accepted over conflicting candidate evidence after adjudication.",
                True,
            )
        return (
            "applicant_confirmed_winner",
            "Applicant-confirmed answer aligned with the accepted value.",
            False,
        )
    if matching and conflicting:
        return (
            "applicant_partial_conflict",
            "An applicant-confirmed value supports the accepted value, but another applicant-provided value conflicts and should be reviewed.",
            True,
        )
    if conflicting or (applicant_candidates and not matching):
        alt = conflicting[0] if conflicting else applicant_candidates[0]
        return (
            "applicant_conflicts_with_winner",
            f"Applicant-confirmed value {_stringify_value_for_reason(alt.get('value'))} conflicts with the accepted value and requires review.",
            True,
        )
    return (
        "applicant_supports_winner",
        "Applicant-confirmed answer supports the accepted value.",
        False,
    )





def _accepted_value_kind(status: str, winner: dict[str, Any] | None, applicant_state: str) -> str:
    if not winner:
        return "unresolved"
    if status in {"missing", "unresolved"}:
        return status
    if status == "conflicting":
        return "conflicting"
    if applicant_state in {"applicant_confirmed_winner", "applicant_supports_winner"}:
        return "applicant_confirmed_clarification"
    if applicant_state == "applicant_override_selected":
        return "applicant_override"
    hierarchy = str(winner.get("source_hierarchy", "")).strip()
    specificity = str(winner.get("specificity", "")).strip()
    if hierarchy == "applicant_direct_document" and specificity in {"direct_field_match", "exact_instance_match"}:
        return "direct_document_fact"
    if hierarchy == "manufacturer_model_specific_spec":
        return "model_derived_inference"
    if hierarchy in {"applicant_inferred_document", "manufacturer_family_spec", "official_interconnection_source"}:
        return "evidence_backed_inference"
    if status == "review_required":
        return "provisional_inference"
    return "resolved"


def _planner_attention_tier(status: str, planner_critical: bool, needs_confirmation: bool, planner_review_flag: bool) -> str:
    if planner_review_flag or status in {"conflicting", "review_required"}:
        return "planner_review_required"
    if needs_confirmation or status in {"missing", "unresolved"}:
        return "applicant_confirmation_required" if planner_critical else "followup_required"
    if planner_critical:
        return "critical_resolved"
    return "information"
def _decision_basis(status: str, winner: dict[str, Any] | None, applicant_state: str) -> str:
    if not winner:
        return "no_accepted_value"
    if applicant_state in {"applicant_override_selected", "applicant_conflicts_with_winner", "applicant_partial_conflict"}:
        return "accepted_with_applicant_contradiction"
    hierarchy = str(winner.get("source_hierarchy", "")).strip()
    if hierarchy == "applicant_confirmed_answer":
        return "accepted_from_applicant_confirmation"
    if status == "resolved":
        return "accepted_from_governed_adjudication"
    if status in {"review_required", "conflicting"}:
        return "provisional_acceptance_review_required"
    return "unresolved"



def _stringify_value_for_reason(value: Any) -> str:
    if value is None:
        return "<missing>"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_stringify_value_for_reason(item) for item in value)
    return str(value)




def _validation_related_field_ids(issue: dict[str, Any]) -> list[str]:
    code = str(issue.get("code", "")).strip().upper()
    metadata = issue.get("metadata") if isinstance(issue.get("metadata"), dict) else {}
    related: list[str] = []
    explicit = metadata.get("related_field_ids")
    if isinstance(explicit, list):
        related.extend(str(item).strip() for item in explicit if str(item).strip())
    field_id = str(metadata.get("field_id", "")).strip()
    if field_id:
        related.append(field_id)

    code_map = {
        "INVALID_NET_POWER_FACTOR_AT_POI": ["net_power_factor_at_poi"],
        "LOW_NET_POWER_FACTOR_AT_POI": ["net_power_factor_at_poi"],
        "INVALID_ZIP_FRACTION_VALUE": [field_id] if field_id else [],
        "ZIP_FRACTIONS_DO_NOT_SUM_TO_ONE": [
            "steady_state_zip_fraction_z",
            "steady_state_zip_fraction_i",
            "steady_state_zip_fraction_p",
        ],
        "UPS_TOPOLOGY_REDUNDANCY_MISMATCH": ["ups_topology", "redundancy_architecture"],
        "GENERATOR_RATING_BASIS_UNRECOGNIZED": ["generator_prime_or_standby_rating_basis"],
        "GENERATOR_STANDBY_RATING_BELOW_PRIME": ["generator_prime_or_standby_rating_basis", "generator_rated_kw_per_unit"],
        "GENERATOR_CAPACITY_BELOW_PEAK_DEMAND": ["generator_rated_kw_per_unit", "peak_demand_mw"],
        "TELEMETRY_PRESENT_WITHOUT_POINTS_LIST": ["telemetry_points_list_present"],
        "TELEMETRY_WITHOUT_PROTECTION_SUMMARY": ["protection_scheme_summary"],
        "POI_TRANSFORMER_VOLTAGE_MISMATCH": ["point_of_interconnection_voltage_kv", "interconnection_transformer_hv_kv"],
        "GENERATOR_BUS_VOLTAGE_MISMATCH": ["generator_terminal_voltage_kv_or_v", "main_bus_nominal_voltage_kv"],
        "TRANSFORMER_VOLTAGE_RATIO_INVALID": ["interconnection_transformer_hv_kv", "interconnection_transformer_lv_kv"],
        "TRANSFORMER_RATIO_SUSPICIOUS": ["interconnection_transformer_hv_kv", "interconnection_transformer_lv_kv"],
        "LOAD_EXCEEDS_TRANSFORMER_CAPACITY": ["interconnection_transformer_mva_per_unit", "interconnection_transformer_unit_count", "peak_demand_mw"],
    }
    related.extend(code_map.get(code, []))
    return [item for item in dict.fromkeys(str(v).strip() for v in related if str(v).strip())]


def _validation_impacts_by_lookup_key(validation_report: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    report = validation_report if isinstance(validation_report, dict) else {}
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for section in ("errors", "warnings", "info"):
        issues = report.get(section)
        if not isinstance(issues, list):
            continue
        for item in issues:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", section[:-1])).strip().lower() or section[:-1]
            field_path = str(item.get("field_path", "")).strip()
            related_field_ids = _validation_related_field_ids(item)
            impact = {
                "code": str(item.get("code", "")).strip().upper(),
                "severity": severity,
                "message": str(item.get("message", "")).strip(),
                "field_path": field_path,
                "recommendation": str(item.get("recommendation", "")).strip(),
            }
            keys = []
            if field_path:
                keys.append(field_path)
            keys.extend(related_field_ids)
            if not keys:
                continue
            for key in dict.fromkeys(keys):
                buckets[key].append(dict(impact))
    review_flags = report.get("review_flags")
    if isinstance(review_flags, list):
        for item in review_flags:
            if not isinstance(item, dict):
                continue
            field_path = str(item.get("field_path", "")).strip()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            keys = []
            if field_path:
                keys.append(field_path)
            explicit = metadata.get("related_field_ids")
            if isinstance(explicit, list):
                keys.extend(str(v).strip() for v in explicit if str(v).strip())
            if not keys:
                continue
            impact = {
                "code": str(item.get("category", "REVIEW_FLAG")).strip().upper() or "REVIEW_FLAG",
                "severity": str(item.get("severity", "warning")).strip().lower() or "warning",
                "message": str(item.get("message", "")).strip(),
                "field_path": field_path,
                "recommendation": "",
            }
            for key in dict.fromkeys(keys):
                buckets[key].append(dict(impact))
    return buckets


def _apply_validation_impacts(
    *,
    field_id: str,
    field_path: str,
    lookup_keys: list[str],
    planner_critical: bool,
    status: str,
    confidence: float | None,
    confidence_band: str,
    needs_confirmation: bool,
    planner_review_flag: bool,
    why_accepted: list[str],
    unresolved_reason: str,
    validation_impacts: dict[str, list[dict[str, Any]]],
) -> tuple[str, float | None, str, bool, bool, list[str], str, list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    for key in [field_id, field_path, *lookup_keys]:
        matched.extend(validation_impacts.get(str(key).strip(), []))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in matched:
        marker = (str(item.get("code", "")), str(item.get("field_path", "")), str(item.get("message", "")))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    if not deduped:
        return status, confidence, confidence_band, needs_confirmation, planner_review_flag, why_accepted, unresolved_reason, []

    errors = [item for item in deduped if str(item.get("severity", "")).lower() == "error"]
    warnings = [item for item in deduped if str(item.get("severity", "")).lower() != "error"]
    contradiction_codes = {
        "POI_TRANSFORMER_VOLTAGE_MISMATCH",
        "GENERATOR_BUS_VOLTAGE_MISMATCH",
        "TRANSFORMER_VOLTAGE_RATIO_INVALID",
        "TRANSFORMER_RATIO_SUSPICIOUS",
        "UPS_TOPOLOGY_REDUNDANCY_MISMATCH",
        "GENERATOR_STANDBY_RATING_BELOW_PRIME",
        "LOAD_EXCEEDS_TRANSFORMER_CAPACITY",
        "INVALID_ZIP_FRACTION_VALUE",
    }
    contradiction_present = any(str(item.get("code", "")).upper() in contradiction_codes for item in deduped)

    if errors:
        planner_review_flag = True
        needs_confirmation = True
        if status == "resolved":
            status = "conflicting" if contradiction_present or planner_critical else "review_required"
        elif status not in {"missing", "unresolved", "conflicting"}:
            status = "review_required"
        if confidence is not None:
            confidence = min(confidence, 0.59 if contradiction_present else 0.64)
        confidence_band = "LOW" if contradiction_present else ("MODERATE" if confidence_band == "HIGH" else confidence_band)
        primary = errors[0]
        note = primary.get("message") or primary.get("code")
        if note:
            why_accepted = list(why_accepted)
            why_accepted.append(f"Validation flagged this field: {note}")
        if not unresolved_reason:
            unresolved_reason = primary.get("recommendation") or primary.get("message") or primary.get("code", "")

    elif warnings:
        planner_review_flag = True
        needs_confirmation = True if planner_critical or contradiction_present else needs_confirmation
        if status not in {"missing", "unresolved", "conflicting", "review_required"}:
            status = "review_required"
        if confidence is not None:
            confidence = min(confidence, 0.74 if contradiction_present else 0.79)
        confidence_band = "MODERATE" if confidence_band == "HIGH" else confidence_band
        primary = warnings[0]
        note = primary.get("message") or primary.get("code")
        if note:
            why_accepted = list(why_accepted)
            why_accepted.append(f"Validation requires follow-up: {note}")
        if not unresolved_reason and contradiction_present:
            unresolved_reason = primary.get("recommendation") or primary.get("message") or primary.get("code", "")

    return status, confidence, confidence_band, needs_confirmation, planner_review_flag, why_accepted, unresolved_reason, deduped

def build_field_resolution_result(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
    queue_limit: int = 50,
    context: Any | None = None,
) -> dict[str, Any]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    ledger: list[dict[str, Any]] = []
    validation_impacts = _validation_impacts_by_lookup_key(validation_report)

    for section_id in planner_packet_sections():
        for field in planner_packet_fields(section_id, include_optional=include_optional):
            field_id = str(field.get("field_id", "")).strip()
            if not field_id:
                continue
            lookup_keys = registry_lookup_keys(field_id)
            field_path = next((key for key in lookup_keys if "." in key), field_id)
            label = str(field.get("label", "")).strip() or field_label(field_id)
            field_family = _field_family(field_id, field_path, section_id)
            records = _records_for_lookup_keys(state, lookup_keys)
            candidates = _build_candidates(field_id, field_path, label, field_family, records, state)
            winner = candidates[0] if candidates else None
            runner_up = candidates[1] if len(candidates) > 1 else None
            supporting_sources = _supporting_sources_for_lookup_keys(state, lookup_keys, field_family=field_family, candidates=candidates)
            stream_counts = Counter(str(item.get("source_stream", "record")).strip() or "record" for item in candidates)
            for source in supporting_sources:
                stream = str(source.get("source_stream", "supporting")).strip() or "supporting"
                stream_counts[stream] += 1
            requiredness = str(field.get("requiredness", "optional")).strip() or "optional"
            planner_critical = bool(field.get("planner_critical", False))
            field_policy_profile = _field_policy_profile(
                field_id=field_id,
                field_path=field_path,
                field_family=field_family,
                planner_critical=planner_critical,
                requiredness=requiredness,
            )
            applicant_answer_state, contradiction_summary, applicant_force_review = _applicant_answer_state(candidates, winner if isinstance(winner, dict) else None)
            dominance_profile = _dominance_profile(candidates, winner if isinstance(winner, dict) else None, runner_up if isinstance(runner_up, dict) else None)
            status = _accepted_status(
                candidates,
                planner_critical=planner_critical,
                requiredness=requiredness,
                applicant_force_review=applicant_force_review,
                dominance_profile=dominance_profile,
                field_policy_profile=field_policy_profile,
            )
            confidence = _safe_float(winner.get("confidence")) if isinstance(winner, dict) else None
            confidence_band = _confidence_band(confidence, status)
            acceptance_margin = _score_gap(winner if isinstance(winner, dict) else None, runner_up if isinstance(runner_up, dict) else None)
            conflict_materiality = _conflict_materiality(
                winner if isinstance(winner, dict) else None,
                runner_up if isinstance(runner_up, dict) else None,
                planner_critical=planner_critical,
                field_policy_profile=field_policy_profile,
                applicant_force_review=applicant_force_review,
            )
            alternatives = []
            if len(candidates) > 1:
                winner_value = _canonical_value(candidates[0].get("value")) if candidates else None
                for candidate in candidates[1:4]:
                    if _canonical_value(candidate.get("value")) == winner_value and confidence_band == "HIGH":
                        continue
                    candidate = dict(candidate)
                    candidate["not_accepted_reason"] = _alternative_reason(candidates[0], candidate)
                    alternatives.append(candidate)
            runner_up_profile = _runner_up_profile(winner if isinstance(winner, dict) else None, runner_up if isinstance(runner_up, dict) else None)
            conflict_profile = _conflict_profile(
                winner if isinstance(winner, dict) else None,
                runner_up if isinstance(runner_up, dict) else None,
                planner_critical=planner_critical,
                conflict_materiality=conflict_materiality,
                dominance_profile=dominance_profile,
            )
            needs_confirmation = applicant_force_review or status in {"conflicting", "review_required", "missing", "unresolved"}
            planner_review_flag = applicant_force_review or status in {"conflicting", "review_required"} or (planner_critical and status != "resolved")
            why_accepted = _why_accepted(winner, runner_up) if isinstance(winner, dict) else []
            unresolved_reason = _unresolved_reason(
                status=status,
                winner=winner if isinstance(winner, dict) else None,
                runner_up=runner_up if isinstance(runner_up, dict) else None,
                planner_critical=planner_critical,
                applicant_force_review=applicant_force_review,
                conflict_materiality=conflict_materiality,
            )
            (
                status,
                confidence,
                confidence_band,
                needs_confirmation,
                planner_review_flag,
                why_accepted,
                unresolved_reason,
                matched_validation_impacts,
            ) = _apply_validation_impacts(
                field_id=field_id,
                field_path=field_path,
                lookup_keys=lookup_keys,
                planner_critical=planner_critical,
                status=status,
                confidence=confidence,
                confidence_band=confidence_band,
                needs_confirmation=needs_confirmation,
                planner_review_flag=planner_review_flag,
                why_accepted=why_accepted,
                unresolved_reason=unresolved_reason,
                validation_impacts=validation_impacts,
            )
            conflict_materiality = _conflict_materiality(
                winner if isinstance(winner, dict) else None,
                runner_up if isinstance(runner_up, dict) else None,
                planner_critical=planner_critical,
                field_policy_profile=field_policy_profile,
                applicant_force_review=applicant_force_review or bool(matched_validation_impacts and any(str(item.get("severity", "")).lower() == "error" for item in matched_validation_impacts)),
            )
            acceptance_policy_result = _acceptance_policy_result(
                winner=winner if isinstance(winner, dict) else None,
                runner_up=runner_up if isinstance(runner_up, dict) else None,
                status=status,
                confidence=confidence,
                planner_critical=planner_critical,
                requiredness=requiredness,
                conflict_materiality=conflict_materiality,
                dominance_profile=dominance_profile,
                validation_impacts=matched_validation_impacts,
                field_policy_profile=field_policy_profile,
            )
            policy_status = str(acceptance_policy_result.get("status_recommendation", "")).strip().lower()
            if policy_status:
                status = _more_restrictive_status(status, policy_status)
                confidence_band = _confidence_band(confidence, status)
            policy_outcome = str(acceptance_policy_result.get("outcome", "")).strip().lower()
            if policy_outcome in {"blocked_conflict", "blocked_insufficient_support", "accepted_provisional"}:
                needs_confirmation = True
            if policy_outcome in {"blocked_conflict", "blocked_insufficient_support", "accepted_provisional"}:
                planner_review_flag = True if planner_critical or status in {"conflicting", "review_required", "missing", "unresolved"} else planner_review_flag
            if not unresolved_reason and policy_outcome in {"blocked_conflict", "blocked_insufficient_support", "accepted_provisional"}:
                unresolved_reason = " ".join(str(item).strip() for item in acceptance_policy_result.get("reasons", [])[:2] if str(item).strip())
            anchors = []
            for item in candidates:
                anchor = str(item.get("source_anchor", "")).strip()
                if anchor and anchor not in anchors:
                    anchors.append(anchor)
            applicant_question_profile = _applicant_question_profile(
                status=status,
                requiredness=requiredness,
                planner_critical=planner_critical,
                needs_confirmation=needs_confirmation,
                planner_review_flag=planner_review_flag,
                dominance_profile=dominance_profile,
                runner_up_profile=runner_up_profile,
                conflict_profile=conflict_profile,
                unresolved_reason=unresolved_reason,
                acceptance_margin=acceptance_margin,
            )
            applicant_question_profile["accepted_value_snapshot"] = winner.get("value") if isinstance(winner, dict) else None
            planner_trust_row = _planner_trust_row(
                label=label,
                accepted_value=winner.get("value") if isinstance(winner, dict) else None,
                accepted_unit=str(winner.get("unit", "")).strip() if isinstance(winner, dict) else "",
                status=status,
                confidence_band=confidence_band,
                planner_critical=planner_critical,
                planner_review_flag=planner_review_flag,
                needs_confirmation=needs_confirmation,
                dominance_profile=dominance_profile,
                runner_up_profile=runner_up_profile,
                conflict_profile=conflict_profile,
            )
            field_release_profile = _field_release_profile(
                accepted_value=winner.get("value") if isinstance(winner, dict) else None,
                status=status,
                planner_critical=planner_critical,
                planner_review_flag=planner_review_flag,
                needs_confirmation=needs_confirmation,
                confidence_band=confidence_band,
                applicant_question_profile=applicant_question_profile,
                planner_trust_row=planner_trust_row,
                conflict_profile=conflict_profile,
            )
            adjudication_trace = _adjudication_trace(
                label=label,
                accepted_value=winner.get("value") if isinstance(winner, dict) else None,
                accepted_unit=str(winner.get("unit", "")).strip() if isinstance(winner, dict) else "",
                status=status,
                confidence_band=confidence_band,
                why_accepted=why_accepted,
                runner_up_profile=runner_up_profile,
                conflict_profile=conflict_profile,
                applicant_question_profile=applicant_question_profile,
                field_release_profile=field_release_profile,
            )
            entry = FieldResolutionLedgerEntry(
                field_id=field_id,
                field_path=field_path,
                label=label,
                packet_section=section_id,
                packet_section_label=planner_packet_section_label(section_id),
                requiredness=requiredness,
                planner_critical=planner_critical,
                field_family=field_family,
                accepted_value=winner.get("value") if isinstance(winner, dict) else None,
                accepted_unit=str(winner.get("unit", "")).strip() if isinstance(winner, dict) else "",
                accepted_status=status,
                accepted_confidence=confidence,
                confidence_band=confidence_band,
                accepted_candidate_id=str(winner.get("candidate_id", "")).strip() if isinstance(winner, dict) else "",
                why_accepted=why_accepted,
                candidates=candidates,
                alternatives=alternatives,
                source_anchors=anchors,
                accepted_source_hierarchy=str(winner.get("source_hierarchy", "")).strip() if isinstance(winner, dict) else "",
                accepted_specificity=str(winner.get("specificity", "")).strip() if isinstance(winner, dict) else "",
                candidate_evidence_appendix=[_candidate_evidence_summary(item) for item in ([dict(candidates[0])] + alternatives)[:5]] if candidates else [],
                supporting_sources=supporting_sources[:6],
                source_stream_counts=dict(sorted(stream_counts.items())),
                applicant_answer_state=applicant_answer_state,
                contradiction_summary=contradiction_summary,
                decision_basis=_decision_basis(status, winner if isinstance(winner, dict) else None, applicant_answer_state),
                accepted_value_kind=_accepted_value_kind(status, winner if isinstance(winner, dict) else None, applicant_answer_state),
                planner_attention_tier=_planner_attention_tier(status, planner_critical, needs_confirmation, planner_review_flag),
                field_policy_class=str(field_policy_profile.get("field_class", "supporting")).strip(),
                field_materiality_class=str(field_policy_profile.get("materiality_class", "supporting_context")).strip(),
                conflict_materiality=conflict_materiality,
                acceptance_margin=acceptance_margin,
                runner_up_candidate_id=str(runner_up.get("candidate_id", "")).strip() if isinstance(runner_up, dict) else "",
                unresolved_reason=unresolved_reason,
                candidate_summary={
                    "candidate_count": len(candidates),
                    "distinct_value_count": len({_canonical_value(item.get("value")) for item in candidates if item.get("value") is not None}),
                    "supporting_source_count": len(supporting_sources),
                    "corroborated_candidate_count": len([item for item in candidates if int(item.get("corroboration_count", 1) or 1) > 1]),
                    "validation_impact_count": len(matched_validation_impacts),
                    "validation_error_count": len([item for item in matched_validation_impacts if str(item.get("severity", "")).lower() == "error"]),
                    "exact_model_support_count": int((winner.get("metadata", {}) if isinstance(winner, dict) and isinstance(winner.get("metadata"), dict) else {}).get("exact_model_support_count", 0) or 0),
                    "official_source_count": int((winner.get("metadata", {}) if isinstance(winner, dict) and isinstance(winner.get("metadata"), dict) else {}).get("official_source_count", 0) or 0),
                    "weak_support_only": bool((winner.get("metadata", {}) if isinstance(winner, dict) and isinstance(winner.get("metadata"), dict) else {}).get("weak_support_only", False)),
                    "winner_group_candidate_count": int(dominance_profile.get("winner_group_candidate_count", 0) or 0),
                    "winner_group_independent_source_count": int(dominance_profile.get("winner_group_independent_source_count", 0) or 0),
                    "winner_group_source_stream_count": int(dominance_profile.get("winner_group_source_stream_count", 0) or 0),
                    "runner_up_group_candidate_count": int(dominance_profile.get("runner_up_group_candidate_count", 0) or 0),
                    "runner_up_group_independent_source_count": int(dominance_profile.get("runner_up_group_independent_source_count", 0) or 0),
                    "group_score_margin": float(dominance_profile.get("group_score_margin", 0.0) or 0.0),
                    "dominance_level": str(dominance_profile.get("dominance_level", "single_source")).strip() or "single_source",
                    "field_class": str(field_policy_profile.get("field_class", "supporting")).strip(),
                    "materiality_class": str(field_policy_profile.get("materiality_class", "supporting_context")).strip(),
                    "policy_confidence_threshold": float(field_policy_profile.get("confidence_threshold", 0.0) or 0.0),
                    "runner_up_plausibility": str(conflict_profile.get("runner_up_plausibility", "")).strip(),
                    "numeric_delta_ratio": conflict_profile.get("numeric_delta_ratio"),
                },
                needs_applicant_confirmation=needs_confirmation,
                planner_review_flag=planner_review_flag,
                dominance_profile=dominance_profile,
                runner_up_profile=runner_up_profile,
                conflict_profile=conflict_profile,
                applicant_question_profile=applicant_question_profile,
                planner_trust_row=planner_trust_row,
                acceptance_policy_result=acceptance_policy_result,
                field_release_profile=field_release_profile,
                adjudication_trace=adjudication_trace,
            )
            ledger.append(entry.to_dict())

    ledger.sort(key=lambda item: (
        0 if bool(item.get("planner_critical", False)) else 1,
        0 if str(item.get("requiredness", "optional")).strip().lower() == "required" else 1,
        STATUS_SORT_ORDER.get(str(item.get("accepted_status", "unresolved")).strip().lower(), 5),
        1 if item.get("accepted_confidence") is None else 0,
        item.get("accepted_confidence") if isinstance(item.get("accepted_confidence"), (int, float)) else -1.0,
        str(item.get("label", "")).lower(),
    ))

    backlog = [
        {
            **item,
            "status": item.get("accepted_status"),
            "resolution_priority": index,
        }
        for index, item in enumerate(
            [
                entry for entry in ledger
                if str(entry.get("accepted_status", "unresolved")).strip().lower() != "resolved"
            ][:queue_limit],
            start=1,
        )
    ]

    status_counts = Counter(str(item.get("accepted_status", "unresolved")).strip().lower() for item in ledger)
    governance_posture_summary = _governance_posture_summary(ledger)
    unique_accepted_field_count = len([
        item for item in ledger
        if isinstance(item, dict)
        and item.get("accepted_value") is not None
        and str(item.get("accepted_status", "unresolved")).strip().lower() not in {"missing", "unresolved"}
    ])
    accepted_field_index: dict[str, dict[str, Any]] = {}
    for item in ledger:
        if not isinstance(item, dict):
            continue
        field_id = str(item.get("field_id", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        if field_id:
            accepted_field_index[field_id] = dict(item)
        if field_path:
            accepted_field_index[field_path] = dict(item)
    high_materiality_conflicts = [
        dict(item)
        for item in ledger
        if str(item.get("conflict_materiality", "")).strip().lower() == "high"
    ][:queue_limit]
    planner_review_queue = [
        dict(item)
        for item in ledger
        if bool(item.get("planner_review_flag", False))
    ][:queue_limit]

    result = {
        "planner_registry_backed": True,
        "ledger": ledger,
        "ledger_count": len(ledger),
        "accepted_field_index": accepted_field_index,
        "backlog": backlog,
        "backlog_count": len(backlog),
        "backlog_field_ids": [str(item.get("field_id", "")).strip() for item in backlog if str(item.get("field_id", "")).strip()],
        "planner_review_queue": planner_review_queue,
        "planner_review_queue_count": len(planner_review_queue),
        "high_materiality_conflicts": high_materiality_conflicts,
        "high_materiality_conflict_count": len(high_materiality_conflicts),
        "governance_posture_summary": governance_posture_summary,
        "summary": {
            "resolved_count": status_counts.get("resolved", 0),
            "review_required_count": status_counts.get("review_required", 0),
            "conflicting_count": status_counts.get("conflicting", 0),
            "missing_count": status_counts.get("missing", 0),
            "unresolved_count": status_counts.get("unresolved", 0),
            "planner_review_count": len([item for item in ledger if bool(item.get("planner_review_flag", False))]),
            "applicant_confirmation_needed_count": len([item for item in ledger if bool(item.get("needs_applicant_confirmation", False))]),
            "high_materiality_conflict_count": len([item for item in ledger if str(item.get("conflict_materiality", "")).strip().lower() == "high"]),
            "accepted_field_index_count": unique_accepted_field_count,
            "accepted_field_lookup_key_count": len(accepted_field_index),
            "release_state_counts": dict(governance_posture_summary.get("release_state_counts", {})),
            "export_readiness_tier_counts": dict(governance_posture_summary.get("export_readiness_tier_counts", {})),
            "materiality_class_counts": dict(governance_posture_summary.get("materiality_class_counts", {})),
            "accepted_source_hierarchy_counts": dict(governance_posture_summary.get("accepted_source_hierarchy_counts", {})),
            "policy_outcome_counts": dict(governance_posture_summary.get("policy_outcome_counts", {})),
            "blocked_field_count": int(governance_posture_summary.get("blocked_field_count", 0)),
            "provisional_field_count": int(governance_posture_summary.get("provisional_field_count", 0)),
            "meaningful_alternative_field_count": int(governance_posture_summary.get("meaningful_alternative_field_count", 0)),
            "source_stream_totals": dict(sorted(Counter(
                stream
                for item in ledger if isinstance(item, dict)
                for stream, count in (item.get("source_stream_counts", {}) or {}).items()
                for _ in range(int(count or 0))
            ).items())),
        },
    }

    run_id = getattr(context, "run_id", None) if context is not None else None
    evidence_route_records = _evidence_route_record_inputs(canonical_state)
    adjudication_targets: list[dict[str, Any]] = []
    for item in ledger:
        if not isinstance(item, dict):
            continue
        if not (
            bool(item.get("planner_critical", False))
            or str(item.get("accepted_status", "")).strip().lower() in {"review_required", "conflicting"}
            or bool(item.get("alternatives", []))
        ):
            continue
        target = dict(item)
        route_record = evidence_route_records.get(str(item.get("field_path", "")).strip(), {}) or evidence_route_records.get(str(item.get("field_id", "")).strip(), {})
        if isinstance(route_record, dict) and route_record:
            target["evidence_route_record"] = dict(route_record)
            target["evidence_route_status"] = str(route_record.get("route_status", "")).strip()
            if isinstance(route_record.get("query_sources"), list):
                target["evidence_route_query_sources"] = list(route_record.get("query_sources", []))
            if isinstance(route_record.get("preferred_corpora"), list):
                target["evidence_route_preferred_corpora"] = list(route_record.get("preferred_corpora", []))
        adjudication_targets.append(target)

    adjudication_packet_plan = build_adjudication_packet_plan(
        ledger=ledger,
        summary=dict(result.get("summary", {})),
    )
    result["adjudication_packet_plan"] = adjudication_packet_plan.to_dict()
    result["adjudication_status"] = adjudication_packet_plan.status

    def _merge_adjudication_structured_output(structured_output: dict[str, Any]) -> None:
        if not isinstance(structured_output, dict):
            return
        per_field_adjudication = structured_output.get("per_field_adjudication", []) if isinstance(structured_output.get("per_field_adjudication", []), list) else []
        notes_by_field: dict[str, dict[str, Any]] = {}
        for note in per_field_adjudication:
            if not isinstance(note, dict):
                continue
            for field_key in (str(note.get("field_id", "")).strip(), str(note.get("field_path", "")).strip()):
                if field_key:
                    notes_by_field[field_key] = note
        for item in ledger:
            if not isinstance(item, dict):
                continue
            note = notes_by_field.get(str(item.get("field_id", "")).strip()) or notes_by_field.get(str(item.get("field_path", "")).strip())
            if not isinstance(note, dict):
                continue
            stronger_reasoning = str(note.get("stronger_candidate_reasoning", "")).strip()
            runner_up_summary = str(note.get("runner_up_summary", "")).strip()
            hidden_flags = [str(flag).strip() for flag in note.get("hidden_conflict_flags", []) if str(flag).strip()] if isinstance(note.get("hidden_conflict_flags"), list) else []
            adjudication_notes = [str(bit).strip() for bit in item.get("adjudication_notes", []) if str(bit).strip()] if isinstance(item.get("adjudication_notes"), list) else []
            if stronger_reasoning:
                adjudication_notes.append(stronger_reasoning)
            if runner_up_summary:
                adjudication_notes.append(runner_up_summary)
            adjudication_notes.extend(hidden_flags)
            if adjudication_notes:
                item["adjudication_notes"] = adjudication_notes[:6]
            if stronger_reasoning:
                item["stronger_candidate_reasoning"] = stronger_reasoning
            if runner_up_summary:
                item["runner_up_summary"] = runner_up_summary
            if hidden_flags:
                item["hidden_conflict_flags"] = hidden_flags[:4]
            route_record = evidence_route_records.get(str(item.get("field_path", "")).strip(), {}) or evidence_route_records.get(str(item.get("field_id", "")).strip(), {})
            if isinstance(route_record, dict) and route_record:
                item["evidence_route_record"] = dict(route_record)
            for text_key in (
                "evidence_route_rationale",
                "source_quality_comparison",
                "specificity_comparison",
                "why_search_path_was_trusted",
            ):
                text_value = str(note.get(text_key, "")).strip()
                if text_value:
                    item[text_key] = text_value
            item["ask_applicant_recommendation"] = bool(note.get("ask_applicant_recommendation", False))
            item["downgrade_recommendation"] = bool(note.get("downgrade_recommendation", False))

    if isinstance(run_id, str) and run_id.strip() and adjudication_packet_plan.packets:
        adjudication_results: list[dict[str, Any]] = []
        completed_count = 0
        blocked_count = 0
        error_count = 0
        try:
            for packet in adjudication_packet_plan.packets:
                associated_paths = [
                    str(item.get("field_path", "")).strip()
                    for item in packet.get("adjudication_targets", [])
                    if isinstance(item, dict) and str(item.get("field_path", "")).strip()
                ]
                adjudication_result = run_agent(
                    context=context,
                    request=AgentRequest(
                        agent_id="adjudication_support_agent",
                        stage_name="canonical_state",
                        task_name="field_resolution_review",
                        inputs=packet,
                        metadata={
                            "service": "field_resolution_service",
                            "adjudication_packet_version": "field_compact_v1",
                            "packet_index": packet.get("packet_index"),
                            "chunking_enabled": True,
                            "chunking_strategy": "adjudication_field_group_packet",
                            "chunk_domain": str(packet.get("domain") or packet.get("field_group") or "adjudication_conflicts"),
                        },
                        trigger_reason="compact_field_resolution_governance_review",
                        associated_field_paths=associated_paths,
                        suggested_output_fields=[
                            "adjudication_summary",
                            "priority_conflicts",
                            "priority_applicant_confirmations",
                            "priority_planner_review_fields",
                            "recommended_interview_targets",
                            "per_field_adjudication",
                            "stronger_candidate_reasoning",
                            "hidden_conflict_flags",
                            "ask_applicant_recommendation",
                            "downgrade_recommendation",
                            "runner_up_summary",
                            "evidence_route_rationale",
                            "source_quality_comparison",
                            "specificity_comparison",
                            "why_search_path_was_trusted",
                            "rationale",
                            "confidence",
                        ],
                    ),
                )
                adjudication_results.append(adjudication_result)
                status = str(adjudication_result.get("status", "")).strip().upper() if isinstance(adjudication_result, dict) else "ERROR"
                if status == "COMPLETED":
                    completed_count += 1
                    structured_output = adjudication_result.get("structured_output", {}) if isinstance(adjudication_result, dict) else {}
                    if isinstance(structured_output, dict):
                        _merge_adjudication_structured_output(structured_output)
                elif status == "PROMPT_TOO_LARGE":
                    blocked_count += 1
                else:
                    error_count += 1
            result["adjudication_support"] = {
                "status": "COMPLETED" if completed_count == len(adjudication_results) else "PARTIAL",
                "packet_results": adjudication_results,
                "completed_packet_count": completed_count,
                "blocked_packet_count": blocked_count,
                "error_packet_count": error_count,
            }
            if blocked_count:
                result["adjudication_status"] = "ADJUDICATION_BLOCKED_PROMPT_TOO_LARGE" if completed_count == 0 else "ADJUDICATION_PARTIAL"
            elif error_count:
                result["adjudication_status"] = "ADJUDICATION_PARTIAL" if completed_count else "ADJUDICATION_REQUIRED_BUT_FAILED"
            elif completed_count:
                result["adjudication_status"] = "ADJUDICATION_COMPLETED"
            structured_outputs = [
                item.get("structured_output", {})
                for item in adjudication_results
                if isinstance(item, dict) and isinstance(item.get("structured_output", {}), dict)
            ]
            result["adjudication_support_summary"] = {
                "adjudication_summary": " | ".join(
                    str(item.get("adjudication_summary", "")).strip()
                    for item in structured_outputs
                    if str(item.get("adjudication_summary", "")).strip()
                )[:1200],
                "recommended_interview_targets": list(dict.fromkeys(
                    str(target).strip()
                    for item in structured_outputs
                    for target in (item.get("recommended_interview_targets", []) if isinstance(item.get("recommended_interview_targets", []), list) else [])
                    if str(target).strip()
                ))[:20],
                "priority_conflict_count": sum(len(item.get("priority_conflicts", [])) for item in structured_outputs if isinstance(item.get("priority_conflicts", []), list)),
                "priority_planner_review_count": sum(len(item.get("priority_planner_review_fields", [])) for item in structured_outputs if isinstance(item.get("priority_planner_review_fields", []), list)),
                "ask_applicant_recommendation": any(bool(item.get("ask_applicant_recommendation", False)) for item in structured_outputs),
                "downgrade_recommendation": any(bool(item.get("downgrade_recommendation", False)) for item in structured_outputs),
                "packet_count": len(adjudication_results),
                "completed_packet_count": completed_count,
            }
        except Exception as exc:
            result["adjudication_status"] = "ADJUDICATION_REQUIRED_BUT_FAILED"
            result["adjudication_support"] = {
                "status": "ERROR",
                "error": str(exc),
            }
    elif adjudication_packet_plan.status == "ADJUDICATION_SKIPPED_NO_CONFLICTS":
        result["adjudication_support"] = {
            "status": "SKIPPED",
            "reason": "No planner-critical conflicts or review-required field candidates required adjudication.",
        }
    elif adjudication_packet_plan.target_count > 0:
        result["adjudication_support"] = {
            "status": "SKIPPED",
            "reason": "Adjudication targets existed but no compact packet could be built within policy caps or run context was unavailable.",
        }


    return result



def resolve_field_resolution(canonical_state: dict[str, Any] | None, validation_report: dict[str, Any] | None = None, *, include_optional: bool = False, queue_limit: int = 50) -> dict[str, Any]:
    """Backward-compatible wrapper for building the governed field resolution result."""
    return build_field_resolution_result(
        canonical_state,
        validation_report,
        include_optional=include_optional,
        queue_limit=queue_limit,
    )
