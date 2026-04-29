from __future__ import annotations

from typing import Any

from shared.planner_registry import summarize_field_resolution_governance


def _coerce_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _coerce_list(payload: Any) -> list[Any]:
    return payload if isinstance(payload, list) else []


def _clean_text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _flatten_planner_packet_rows(canonical_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows_payload = canonical_payload.get("planner_packet_field_rows")
    rows: list[dict[str, Any]] = []
    if isinstance(rows_payload, dict):
        for value in rows_payload.values():
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
    elif isinstance(rows_payload, list):
        rows.extend(item for item in rows_payload if isinstance(item, dict))
    return rows


def _summarize_planner_packet_resolution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    value_kind_counts: dict[str, int] = {}
    attention_tier_counts: dict[str, int] = {}
    decision_basis_counts: dict[str, int] = {}
    contradiction_count = 0
    anchored_field_count = 0
    runner_up_field_count = 0
    direct_fact_count = 0
    inferred_count = 0
    assumed_count = 0
    applicant_confirmed_count = 0

    for row in rows:
        value_kind = _clean_text(row.get("accepted_value_kind")).lower()
        if value_kind:
            value_kind_counts[value_kind] = value_kind_counts.get(value_kind, 0) + 1
            if "direct" in value_kind:
                direct_fact_count += 1
            elif "infer" in value_kind:
                inferred_count += 1
            elif "assum" in value_kind:
                assumed_count += 1
            elif "applicant" in value_kind:
                applicant_confirmed_count += 1

        attention_tier = _clean_text(row.get("planner_attention_tier")).lower()
        if attention_tier:
            attention_tier_counts[attention_tier] = attention_tier_counts.get(attention_tier, 0) + 1

        decision_basis = _clean_text(row.get("decision_basis")).lower()
        if decision_basis:
            decision_basis_counts[decision_basis] = decision_basis_counts.get(decision_basis, 0) + 1

        if _clean_text(row.get("contradiction_summary")):
            contradiction_count += 1
        anchors = row.get("source_anchors")
        if isinstance(anchors, list) and any(_clean_text(a) for a in anchors):
            anchored_field_count += 1
        alternatives = row.get("alternatives")
        if isinstance(alternatives, list) and alternatives:
            runner_up_field_count += 1

    return {
        "planner_packet_row_count": len(rows),
        "value_kind_counts": value_kind_counts,
        "attention_tier_counts": attention_tier_counts,
        "decision_basis_counts": decision_basis_counts,
        "contradiction_count": contradiction_count,
        "anchored_field_count": anchored_field_count,
        "runner_up_field_count": runner_up_field_count,
        "direct_fact_count": direct_fact_count,
        "evidence_backed_inferred_count": inferred_count,
        "assumed_count": assumed_count,
        "applicant_confirmed_count": applicant_confirmed_count,
    }


def summarize_canonical_governance(canonical_state: dict[str, Any] | None, validation_result: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical_payload = _coerce_dict(canonical_state)
    validation_payload = _coerce_dict(validation_result)
    validation_report = _coerce_dict(validation_payload.get("validation_report"))
    field_records = [item for item in _coerce_list(canonical_payload.get("field_records")) if isinstance(item, dict)]
    planner_summary = summarize_field_resolution_governance(canonical_payload, validation_report)
    planner_packet_rows = _flatten_planner_packet_rows(canonical_payload)
    packet_resolution_summary = _summarize_planner_packet_resolution(planner_packet_rows)
    source_stream_counts: dict[str, int] = {}
    for row in planner_packet_rows:
        if not isinstance(row, dict):
            continue
        stream_counts = row.get("source_stream_counts")
        if isinstance(stream_counts, dict):
            for key, value in stream_counts.items():
                key_text = _clean_text(key).lower()
                try:
                    count_value = int(value)
                except (TypeError, ValueError):
                    continue
                if key_text and count_value > 0:
                    source_stream_counts[key_text] = source_stream_counts.get(key_text, 0) + count_value

    field_resolution_payload = _coerce_dict(canonical_payload.get("field_resolution"))
    field_resolution_summary = _coerce_dict(field_resolution_payload.get("summary"))

    summary = {
        "field_record_count": len(field_records),
        "primary_record_count": 0,
        "confirmed_count": 0,
        "provisional_retrieved_count": 0,
        "provisional_extracted_count": 0,
        "assumed_count": int(planner_summary.get("assumed_count", 0)),
        "missing_count": int(planner_summary.get("missing_count", 0)),
        "conflicting_count": int(planner_summary.get("conflicting_count", 0)),
        "review_required_count": int(planner_summary.get("review_required_count", 0)),
        "validation_missing_field_count": len(_coerce_list(validation_report.get("missing_fields"))),
        "validation_conflict_count": len(_coerce_list(validation_report.get("conflicts"))),
        "review_flag_count": len(_coerce_list(canonical_payload.get("review_flags"))),
        "accepted_planner_field_count": int(planner_summary.get("accepted_planner_field_count", 0)),
        "applicant_confirmation_needed_count": int(planner_summary.get("applicant_confirmation_needed_count", 0)),
        "planner_review_count": int(planner_summary.get("planner_review_count", 0)),
        "planner_review_queue_count": int(field_resolution_payload.get("planner_review_queue_count", field_resolution_summary.get("planner_review_count", 0))),
        "applicant_confirmation_needed_count": int(planner_summary.get("applicant_confirmation_needed_count", 0)),
        "high_materiality_conflict_count": int(field_resolution_summary.get("high_materiality_conflict_count", 0)),
        "resolution_queue_count": int(planner_summary.get("resolution_queue_count", 0)),
        "top_backlog_field_ids": list(planner_summary.get("top_backlog_field_ids", [])),
        "planner_registry_backed": bool(planner_summary.get("planner_registry_backed", False)),
        "planner_packet_row_count": int(packet_resolution_summary.get("planner_packet_row_count", 0)),
        "contradiction_count": int(packet_resolution_summary.get("contradiction_count", 0)),
        "anchored_field_count": int(packet_resolution_summary.get("anchored_field_count", 0)),
        "runner_up_field_count": int(packet_resolution_summary.get("runner_up_field_count", 0)),
        "decision_basis_counts": dict(packet_resolution_summary.get("decision_basis_counts", {})) if isinstance(packet_resolution_summary.get("decision_basis_counts"), dict) else {},
        "value_kind_counts": dict(packet_resolution_summary.get("value_kind_counts", {})) if int(packet_resolution_summary.get("planner_packet_row_count", 0)) > 0 else (dict(planner_summary.get("value_kind_counts", {})) if isinstance(planner_summary.get("value_kind_counts"), dict) else {}),
        "attention_tier_counts": dict(packet_resolution_summary.get("attention_tier_counts", {})) if int(packet_resolution_summary.get("planner_packet_row_count", 0)) > 0 else (dict(planner_summary.get("attention_tier_counts", {})) if isinstance(planner_summary.get("attention_tier_counts"), dict) else {}),
        "source_stream_counts": dict(source_stream_counts),
    }

    for record in field_records:
        if bool(record.get("is_primary")):
            summary["primary_record_count"] += 1

        status = _clean_text(record.get("status")).lower()
        validation_status = _clean_text(record.get("validation_status")).upper()
        source_method = _clean_text(record.get("source_method")).lower()
        provenance_type = _clean_text(_coerce_dict(record.get("metadata")).get("provenance_type")).lower()

        if validation_status in {"VALIDATED", "CALIBRATED", "INTERVIEW_CONFIRMED"} or status in {"validated", "interview_confirmed"}:
            summary["confirmed_count"] += 1
        if validation_status == "PROVISIONAL_RETRIEVED" or status == "provisional_retrieved":
            summary["provisional_retrieved_count"] += 1
        if validation_status == "PROVISIONAL_EXTRACTED" or status == "provisional_extracted":
            summary["provisional_extracted_count"] += 1
        if "assumption" in source_method or provenance_type == "assumption" or status == "assumed":
            summary["assumed_count"] = max(summary["assumed_count"], int(planner_summary.get("assumed_count", 0)))

    if int(packet_resolution_summary.get("planner_packet_row_count", 0)) > 0:
        summary["confirmed_count"] = max(summary["confirmed_count"], int(packet_resolution_summary.get("direct_fact_count", 0)) + int(packet_resolution_summary.get("applicant_confirmed_count", 0)))
        summary["assumed_count"] = max(summary["assumed_count"], int(packet_resolution_summary.get("assumed_count", 0)))

    summary["governed_distinction_summary"] = {
        "confirmed": summary["confirmed_count"],
        "evidence_backed_inferred": max(summary["provisional_extracted_count"], int(planner_summary.get("evidence_backed_inferred_count", 0)), int(packet_resolution_summary.get("evidence_backed_inferred_count", 0))),
        "provisional_retrieved": summary["provisional_retrieved_count"],
        "assumed": summary["assumed_count"],
        "missing": max(summary["missing_count"], summary["validation_missing_field_count"]),
        "conflicting": max(summary["conflicting_count"], summary["validation_conflict_count"]),
        "review_required": summary["review_required_count"],
        "applicant_confirmation_needed": summary["applicant_confirmation_needed_count"],
        "planner_review_queue_count": summary["planner_review_queue_count"],
        "high_materiality_conflicts": summary["high_materiality_conflict_count"],
        "value_kind_counts": dict(summary.get("value_kind_counts", {})),
        "attention_tier_counts": dict(summary.get("attention_tier_counts", {})),
        "decision_basis_counts": dict(summary.get("decision_basis_counts", {})),
        "contradiction_count": int(summary.get("contradiction_count", 0)),
        "anchored_field_count": int(summary.get("anchored_field_count", 0)),
        "runner_up_field_count": int(summary.get("runner_up_field_count", 0)),
        "source_stream_counts": dict(summary.get("source_stream_counts", {})),
    }
    return summary


def build_governed_summary(canonical_state: dict[str, Any] | None, validation_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backward-compatible wrapper returning the governed canonical summary."""
    return summarize_canonical_governance(canonical_state, validation_result)


def summarize_gap_resolution_governance(retrieval_result: dict[str, Any] | None, interview_result: dict[str, Any] | None, gap_resolution_result: dict[str, Any] | None = None) -> dict[str, Any]:
    retrieval_payload = _coerce_dict(retrieval_result)
    interview_payload = _coerce_dict(interview_result)
    gap_payload = _coerce_dict(gap_resolution_result)
    if not retrieval_payload:
        retrieval_payload = _coerce_dict(gap_payload.get("retrieval"))
    if not interview_payload:
        interview_payload = _coerce_dict(gap_payload.get("interview"))

    backlog = [item for item in _coerce_list(retrieval_payload.get("resolution_backlog")) if isinstance(item, dict)]
    backlog_summary = _coerce_dict(retrieval_payload.get("resolution_backlog_summary"))
    questions = _coerce_list(interview_payload.get("questions"))
    clarifications = _coerce_list(interview_payload.get("clarifications"))

    type_counts = {"retrieval_gap": 0, "retrieval_confirmation": 0, "retrieval_deferred": 0}
    for item in backlog:
        item_type = _clean_text(item.get("type"))
        if item_type in type_counts:
            type_counts[item_type] += 1

    return {
        "retrieval_status": _clean_text(retrieval_payload.get("status")) or "NOT_RUN",
        "interview_status": _clean_text(interview_payload.get("status")) or "NOT_RUN",
        "snippet_count": len(_coerce_list(retrieval_payload.get("snippets"))),
        "warning_count": len(_coerce_list(retrieval_payload.get("warnings"))),
        "resolution_backlog_count": len(backlog),
        "resolution_backlog_types": type_counts,
        "requested_field_count": len(_coerce_list(retrieval_payload.get("requested_field_paths"))),
        "review_required_field_count": len(_coerce_list(retrieval_payload.get("review_required_field_paths"))),
        "deferred_field_count": len(_coerce_list(retrieval_payload.get("out_of_scope_missing_field_paths"))),
        "question_count": len(questions),
        "clarification_count": len(clarifications),
        "ready_for_validation": bool(interview_payload.get("ready_for_validation", False)),
        "backlog_summary": backlog_summary,
    }


def summarize_translation_governance(translation_result: dict[str, Any] | None, scenario_result: dict[str, Any] | None = None) -> dict[str, Any]:
    translation_payload = _coerce_dict(translation_result)
    scenario_payload = _coerce_dict(scenario_result)
    output_parameters = [item for item in _coerce_list(translation_payload.get("output_parameters")) if isinstance(item, dict)]
    assumptions = _coerce_list(translation_payload.get("assumptions"))
    translation_support = _coerce_dict(translation_payload.get("translation_support"))
    confidence_summary = _coerce_dict(translation_payload.get("confidence_summary"))

    provenance_summary: dict[str, int] = {}
    review_required_count = 0
    for item in output_parameters:
        provenance_type = _clean_text(item.get("provenance_type")).lower() or "unknown"
        provenance_summary[provenance_type] = provenance_summary.get(provenance_type, 0) + 1
        confidence_tag = _clean_text(item.get("confidence_tag")).upper()
        if confidence_tag in {"LOW", "UNRESOLVED"} or _clean_text(item.get("review_note")):
            review_required_count += 1

    scenarios = scenario_payload.get("scenarios")
    scenario_count = len(scenarios) if isinstance(scenarios, dict) else 0

    return {
        "translation_status": _clean_text(translation_payload.get("status")) or "NOT_RUN",
        "output_parameter_count": len(output_parameters),
        "assumption_count": len(assumptions),
        "review_required_output_count": review_required_count,
        "confidence_summary": confidence_summary,
        "provenance_type_summary": provenance_summary,
        "assumption_backed_parameter_count": len(_coerce_list(translation_support.get("assumption_backed_parameters"))),
        "missing_dependency_parameter_count": len(_coerce_list(translation_support.get("missing_dependency_parameters"))),
        "scenario_count": scenario_count,
    }


def summarize_export_outputs(export_result: dict[str, Any] | None) -> dict[str, Any]:
    export_payload = _coerce_dict(export_result)
    manifest = _coerce_dict(export_payload.get("export_manifest"))
    exports = _coerce_dict(manifest.get("exports"))
    exported_files = {
        key: value
        for key, value in exports.items()
        if isinstance(value, str) and value.strip()
    }
    return {
        "export_status": _clean_text(export_payload.get("status")) or "NOT_RUN",
        "exported_file_count": len(exported_files),
        "exported_files": exported_files,
        "warning_count": len(_coerce_list(export_payload.get("warnings"))),
    }


def summarize_runtime_observability(
    extraction_result: dict[str, Any] | None,
    retrieval_result: dict[str, Any] | None,
    interview_result: dict[str, Any] | None,
    canonical_state: dict[str, Any] | None,
    validation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extraction_payload = _coerce_dict(extraction_result)
    retrieval_payload = _coerce_dict(retrieval_result)
    interview_payload = _coerce_dict(interview_result)

    schema_field_candidates = [item for item in _coerce_list(extraction_payload.get("schema_field_candidates")) if isinstance(item, dict)]
    promoted_candidates = 0
    promoted_methods: dict[str, int] = {}
    for candidate in schema_field_candidates:
        method = _clean_text(candidate.get("method")).lower()
        if not method:
            continue
        if "promot" in method or "interconnection_" in method:
            promoted_candidates += 1
            promoted_methods[method] = promoted_methods.get(method, 0) + 1

    executed_web = _coerce_dict(retrieval_payload.get("executed_official_web_retrieval"))
    field_pack = _coerce_dict(retrieval_payload.get("document_field_pack"))
    field_support_summary = _coerce_dict(retrieval_payload.get("field_support_summary"))
    resolution_backlog_summary = _coerce_dict(retrieval_payload.get("resolution_backlog_summary"))

    canonical_summary = summarize_canonical_governance(canonical_state, validation_result)
    interview_summary = _coerce_dict(interview_payload.get("session_summary"))

    planner_blocking = int(interview_summary.get("planner_critical_blocking_question_count", 0) or 0)
    clarification_questions = int(interview_summary.get("high_value_clarification_question_count", 0) or 0)
    informational_questions = int(interview_summary.get("informational_question_count", 0) or 0)
    suppressed_questions = int(interview_summary.get("suppressed_low_yield_question_count", 0) or 0)

    return {
        "extraction": {
            "entity_count": len(_coerce_list(extraction_payload.get("entities"))),
            "candidate_entity_count": len(_coerce_list(extraction_payload.get("candidate_entities"))),
            "schema_field_candidate_count": len(schema_field_candidates),
            "promoted_candidate_count": promoted_candidates,
            "promoted_candidate_methods": promoted_methods,
            "source_anchor_count": len(_coerce_list(extraction_payload.get("source_anchors"))),
            "topology_cue_count": len(_coerce_list(extraction_payload.get("topology_cues"))),
            "uncovered_planner_registry_field_count": len(_coerce_list(extraction_payload.get("uncovered_planner_registry_fields"))),
        },
        "retrieval": {
            "snippet_count": len(_coerce_list(retrieval_payload.get("snippets"))),
            "warning_count": len(_coerce_list(retrieval_payload.get("warnings"))),
            "resolution_backlog_count": len(_coerce_list(retrieval_payload.get("resolution_backlog"))),
            "planner_critical_unresolved_field_count": int(resolution_backlog_summary.get("planner_critical_unresolved_count", 0) or 0),
            "requested_field_count": len(_coerce_list(retrieval_payload.get("requested_field_paths"))),
            "review_required_field_count": len(_coerce_list(retrieval_payload.get("review_required_field_paths"))),
            "field_support_count": len(field_support_summary),
            "executed_official_web_attempted_count": int(executed_web.get("attempted_count", 0) or 0),
            "executed_official_web_count": int(executed_web.get("executed_count", 0) or 0),
            "document_active_field_count": len(_coerce_list(field_pack.get("active_field_paths"))),
            "document_suppressed_field_count": len(_coerce_list(field_pack.get("suppressed_field_paths"))),
            "external_retrieval_candidate_field_count": len(_coerce_list(field_pack.get("external_retrieval_candidate_field_paths"))),
        },
        "interview": {
            "question_count": len(_coerce_list(interview_payload.get("questions"))),
            "clarification_count": len(_coerce_list(interview_payload.get("clarifications"))),
            "planner_critical_blocking_question_count": planner_blocking,
            "high_value_clarification_question_count": clarification_questions,
            "informational_question_count": informational_questions,
            "suppressed_low_yield_question_count": suppressed_questions,
        },
        "canonical_resolution": {
            "accepted_planner_field_count": int(canonical_summary.get("accepted_planner_field_count", 0) or 0),
            "missing_count": int(canonical_summary.get("missing_count", 0) or 0),
            "conflicting_count": int(canonical_summary.get("conflicting_count", 0) or 0),
            "review_required_count": int(canonical_summary.get("review_required_count", 0) or 0),
            "planner_review_queue_count": int(canonical_summary.get("planner_review_queue_count", 0) or 0),
            "applicant_confirmation_needed_count": int(canonical_summary.get("applicant_confirmation_needed_count", 0) or 0),
            "provisional_retrieved_count": int(canonical_summary.get("provisional_retrieved_count", 0) or 0),
            "provisional_extracted_count": int(canonical_summary.get("provisional_extracted_count", 0) or 0),
            "assumed_count": int(canonical_summary.get("assumed_count", 0) or 0),
            "planner_critical_blocking_question_count": planner_blocking,
        },
    }


def build_governed_run_summary(*, canonical_state: dict[str, Any] | None, validation_result: dict[str, Any] | None, retrieval_result: dict[str, Any] | None, interview_result: dict[str, Any] | None, gap_resolution_result: dict[str, Any] | None, translation_result: dict[str, Any] | None, scenario_result: dict[str, Any] | None, export_result: dict[str, Any] | None = None, extraction_result: dict[str, Any] | None = None) -> dict[str, Any]:
    canonical_summary = summarize_canonical_governance(canonical_state, validation_result)
    gap_summary = summarize_gap_resolution_governance(retrieval_result, interview_result, gap_resolution_result)
    translation_summary = summarize_translation_governance(translation_result, scenario_result)
    export_summary = summarize_export_outputs(export_result)
    runtime_observability = summarize_runtime_observability(extraction_result, retrieval_result, interview_result, canonical_state, validation_result)
    return {
        "canonical_governance": canonical_summary,
        "gap_resolution_governance": gap_summary,
        "translation_governance": translation_summary,
        "export_governance": export_summary,
        "runtime_observability": runtime_observability,
        "governed_distinction_summary": dict(canonical_summary.get("governed_distinction_summary", {})),
    }
