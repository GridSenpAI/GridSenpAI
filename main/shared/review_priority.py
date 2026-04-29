from __future__ import annotations

from typing import Any


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_manual_review_queue(
    canonical_state: dict[str, Any],
    field_agent_consumption_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_resolution = canonical_state.get("field_resolution") if isinstance(canonical_state.get("field_resolution"), dict) else {}
    ledger = field_resolution.get("ledger", []) if isinstance(field_resolution.get("ledger"), list) else []
    source_inputs = canonical_state.get("source_candidate_inputs") if isinstance(canonical_state.get("source_candidate_inputs"), dict) else {}
    route_records = source_inputs.get("evidence_route_records", []) if isinstance(source_inputs.get("evidence_route_records"), list) else []

    route_by_key: dict[str, dict[str, Any]] = {}
    for record in route_records:
        if not isinstance(record, dict):
            continue
        for key in (record.get("field_path"), record.get("field_id")):
            cleaned = _clean_text(key)
            if cleaned and cleaned not in route_by_key:
                route_by_key[cleaned] = record

    agent_fields = field_agent_consumption_audit.get("fields", []) if isinstance(field_agent_consumption_audit, dict) and isinstance(field_agent_consumption_audit.get("fields"), list) else []
    agent_by_key: dict[str, dict[str, Any]] = {}
    for entry in agent_fields:
        if not isinstance(entry, dict):
            continue
        for key in (entry.get("field_id"), entry.get("field_path")):
            cleaned = _clean_text(key)
            if cleaned and cleaned not in agent_by_key:
                agent_by_key[cleaned] = entry

    queue_groups: dict[str, list[dict[str, Any]]] = {
        "evidence_weakness": [],
        "conflict": [],
        "interview_dependency": [],
        "deterministic_override": [],
    }

    def _bucket_for_entry(item: dict[str, Any], route_record: dict[str, Any] | None, agent_entry: dict[str, Any] | None) -> str:
        hidden_conflicts = item.get("hidden_conflict_flags", []) if isinstance(item.get("hidden_conflict_flags"), list) else []
        if bool(item.get("needs_applicant_confirmation", False)) or bool(item.get("ask_applicant_recommendation", False)):
            return "interview_dependency"
        if _clean_text(item.get("accepted_status")) == "conflicting" or _clean_text(item.get("decision_basis")) == "accepted_with_validation_contradiction" or _clean_text(item.get("contradiction_summary")) or hidden_conflicts:
            return "conflict"
        route = route_record if isinstance(route_record, dict) else {}
        if bool(route.get("weak_support_only", False)) or _clean_text(route.get("support_strength")) == "LOW" or _clean_text(item.get("accepted_specificity")) == "context_inferred":
            return "evidence_weakness"
        dispositions = agent_entry.get("disposition_counts", {}) if isinstance(agent_entry, dict) and isinstance(agent_entry.get("disposition_counts"), dict) else {}
        if any((key in dispositions) for key in ("blocked_by_policy", "ignored_non_completed_output")) or bool(item.get("downgrade_recommendation", False)):
            return "deterministic_override"
        if bool(item.get("planner_review_flag", False)) and _clean_text(item.get("accepted_status")) == "review_required":
            return "deterministic_override"
        return "evidence_weakness"

    for item in ledger:
        if not isinstance(item, dict):
            continue
        status = _clean_text(item.get("accepted_status"))
        if status not in {"review_required", "conflicting", "missing", "unresolved"}:
            continue
        field_id = _clean_text(item.get("field_id"))
        field_path = _clean_text(item.get("field_path"))
        route_record = route_by_key.get(field_path) or route_by_key.get(field_id) or (item.get("evidence_route_record") if isinstance(item.get("evidence_route_record"), dict) else {})
        agent_entry = agent_by_key.get(field_id) or agent_by_key.get(field_path)
        bucket = _bucket_for_entry(item, route_record, agent_entry)
        queue_groups[bucket].append({
            "field_id": field_id,
            "field_path": field_path,
            "label": _clean_text(item.get("label")) or field_id or field_path or "Unknown Field",
            "status": status or "unresolved",
            "planner_critical": bool(item.get("planner_critical", False)),
            "confidence_band": _clean_text(item.get("confidence_band")) or "LOW",
            "reason": _clean_text(item.get("unresolved_reason")) or _clean_text(item.get("contradiction_summary")) or _clean_text(item.get("why_search_path_was_trusted")) or "Manual review required.",
            "decision_basis": _clean_text(item.get("decision_basis")),
            "accepted_value": item.get("accepted_value"),
            "accepted_source_hierarchy": _clean_text(item.get("accepted_source_hierarchy")),
            "accepted_specificity": _clean_text(item.get("accepted_specificity")),
            "route_support_strength": _clean_text((route_record or {}).get("support_strength")),
            "route_weak_support_only": bool((route_record or {}).get("weak_support_only", False)),
            "agent_dispositions": dict(agent_entry.get("disposition_counts", {})) if isinstance(agent_entry, dict) and isinstance(agent_entry.get("disposition_counts"), dict) else {},
        })

    def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (not bool(item.get("planner_critical", False)), 0 if item.get("status") == "conflicting" else 1, str(item.get("label", "")))

    for key in queue_groups:
        queue_groups[key].sort(key=_sort_key)

    return {
        "summary": {
            "total_count": sum(len(items) for items in queue_groups.values()),
            "evidence_weakness_count": len(queue_groups["evidence_weakness"]),
            "conflict_count": len(queue_groups["conflict"]),
            "interview_dependency_count": len(queue_groups["interview_dependency"]),
            "deterministic_override_count": len(queue_groups["deterministic_override"]),
            "planner_critical_count": sum(1 for items in queue_groups.values() for item in items if bool(item.get("planner_critical", False))),
        },
        "groups": queue_groups,
    }


def build_interview_priority_plan(
    *,
    manual_review_queue: dict[str, Any] | None,
    questions: list[dict[str, Any]],
    answered_field_paths: set[str] | None = None,
) -> dict[str, Any]:
    answered = answered_field_paths if isinstance(answered_field_paths, set) else set()
    groups = manual_review_queue.get("groups", {}) if isinstance(manual_review_queue, dict) and isinstance(manual_review_queue.get("groups"), dict) else {}
    priority_order = ["interview_dependency", "conflict", "deterministic_override", "evidence_weakness"]
    review_labels = {
        "interview_dependency": "interview dependency",
        "conflict": "conflict",
        "deterministic_override": "deterministic override",
        "evidence_weakness": "evidence weakness",
    }
    bucket_rank = {
        "interview_dependency": 0,
        "conflict": 1,
        "deterministic_override": 2,
        "evidence_weakness": 3,
    }
    status_rank = {
        "conflicting": 0,
        "review_required": 1,
        "missing": 2,
        "unresolved": 3,
    }

    def _question_priority(question: dict[str, Any]) -> int:
        metadata = question.get("metadata", {}) if isinstance(question.get("metadata"), dict) else {}
        for key in ("interview_priority_score", "priority"):
            value = metadata.get(key) if key == "interview_priority_score" else question.get(key)
            try:
                return int(value or 0)
            except Exception:
                continue
        return 0

    def _note_sort_key(note: dict[str, Any]) -> tuple[Any, ...]:
        return (
            bucket_rank.get(str(note.get("review_bucket", "")), 99),
            0 if bool(note.get("planner_critical", False)) else 1,
            status_rank.get(str(note.get("status", "")).lower(), 99),
            -int(note.get("question_priority", 0) or 0),
            str(note.get("label", "")).lower(),
            str(note.get("field_path", "")).lower(),
        )

    field_notes: dict[str, dict[str, Any]] = {}
    blocker_field_paths: list[str] = []
    review_counts: dict[str, int] = {}
    for group_name in priority_order:
        items = groups.get(group_name, []) if isinstance(groups.get(group_name), list) else []
        review_counts[group_name] = len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            field_path = _clean_text(item.get("field_path"))
            if not field_path or field_path in answered:
                continue
            if field_path not in field_notes:
                field_notes[field_path] = {
                    "field_path": field_path,
                    "field_id": _clean_text(item.get("field_id")),
                    "review_bucket": group_name,
                    "focus_reason": _clean_text(item.get("reason")) or f"Prioritize due to {review_labels[group_name]}.",
                    "planner_critical": bool(item.get("planner_critical", False)),
                    "status": _clean_text(item.get("status")) or "unresolved",
                    "question_category": group_name,
                    "label": _clean_text(item.get("label")) or field_path,
                    "question_priority": 0,
                }
            if group_name in {"interview_dependency", "conflict"} and field_path not in blocker_field_paths:
                blocker_field_paths.append(field_path)

    question_index_by_field: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        if not isinstance(question, dict):
            continue
        field_path = _clean_text(question.get("field_path"))
        if not field_path:
            continue
        question_index_by_field.setdefault(field_path, []).append(question)
        if field_path in field_notes:
            field_notes[field_path]["question_priority"] = max(field_notes[field_path].get("question_priority", 0), _question_priority(question))

    ordered_question_ids: list[str] = []
    targeted_question_notes: list[dict[str, Any]] = []
    sorted_notes = sorted(field_notes.values(), key=_note_sort_key)
    for note in sorted_notes:
        field_path = str(note.get("field_path", "")).strip()
        for question in question_index_by_field.get(field_path, []):
            qid = _clean_text(question.get("question_id"))
            if qid and qid not in ordered_question_ids:
                ordered_question_ids.append(qid)
            targeted_question_notes.append({
                "question_id": qid,
                "field_path": field_path,
                "field_id": note.get("field_id", ""),
                "focus_reason": note.get("focus_reason", ""),
                "question_category": note.get("review_bucket", ""),
                "planner_registry_backed": bool(((question.get("metadata") or {}).get("planner_registry_backed", False))) if isinstance(question.get("metadata"), dict) else False,
                "planner_critical": bool(note.get("planner_critical", False)),
                "status": note.get("status", "unresolved"),
                "question_priority": int(note.get("question_priority", 0) or 0),
                "presentation_phase": "immediate" if str(note.get("review_bucket", "")) in {"interview_dependency", "conflict"} else "deferred",
            })
            break
    for question in sorted(
        [item for item in questions if isinstance(item, dict)],
        key=lambda item: (-_question_priority(item), _clean_text(item.get("field_path")), _clean_text(item.get("question_id"))),
    ):
        qid = _clean_text(question.get("question_id"))
        if qid and qid not in ordered_question_ids:
            ordered_question_ids.append(qid)

    total_items = sum(review_counts.values())
    immediate_count = len([note for note in targeted_question_notes if str(note.get("presentation_phase", "")) == "immediate"])
    deferred_count = max(len(ordered_question_ids) - immediate_count, 0)
    focus_summary = "Ask only the smallest high-impact interview set first: applicant-confirmation blockers and material conflicts before lower-value clarifications."
    if total_items <= 0:
        focus_summary = "No shared manual review priorities were identified for interview sequencing."
    return {
        "question_sequence": ordered_question_ids,
        "targeted_question_notes": targeted_question_notes,
        "blocker_field_paths": blocker_field_paths,
        "review_priority_counts": review_counts,
        "initial_focus_question_count": immediate_count,
        "deferred_question_count": deferred_count,
        "interview_focus_summary": focus_summary,
    }


def build_planner_action_queue(
    *,
    manual_review_queue: dict[str, Any] | None,
    interview_priority_plan: dict[str, Any] | None = None,
    translation_governance_alerts: dict[str, Any] | None = None,
    scenario_governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    groups = review_queue.get("groups", {}) if isinstance(review_queue.get("groups"), dict) else {}
    review_summary = review_queue.get("summary", {}) if isinstance(review_queue.get("summary"), dict) else {}
    interview_plan = interview_priority_plan if isinstance(interview_priority_plan, dict) else {}
    translation_alerts = translation_governance_alerts if isinstance(translation_governance_alerts, dict) else {}
    scenario_alerts = scenario_governance_alerts if isinstance(scenario_governance_alerts, dict) else {}

    actions: list[dict[str, Any]] = []
    seen_field_action_keys: set[str] = set()

    stage_map = {
        "conflict": "planner_review",
        "interview_dependency": "applicant_interview",
        "evidence_weakness": "evidence_resolution",
        "deterministic_override": "planner_review",
        "downstream_gating": "planner_review",
        "provisional_monitoring": "provisional_monitoring",
    }
    owner_map = {
        "planner_review": "planner",
        "applicant_interview": "applicant_interview",
        "evidence_resolution": "evidence_resolution",
        "provisional_monitoring": "planner",
    }
    review_labels = {
        "conflict": "conflict",
        "interview_dependency": "interview dependency",
        "evidence_weakness": "evidence weakness",
        "deterministic_override": "deterministic override",
    }

    def _priority_for_item(bucket: str, item: dict[str, Any]) -> str:
        status = _clean_text(item.get("status")).lower()
        planner_critical = bool(item.get("planner_critical", False))
        if bucket in {"conflict", "interview_dependency"}:
            return "CRITICAL" if planner_critical or status == "conflicting" else "HIGH"
        if bucket == "deterministic_override":
            return "HIGH" if planner_critical else "MODERATE"
        if bucket == "evidence_weakness":
            return "HIGH" if planner_critical else "MODERATE"
        return "LOW"

    def _title_for_item(bucket: str, label: str, next_stage: str) -> str:
        stage_phrase = {
            "planner_review": "planner review",
            "applicant_interview": "applicant interview",
            "evidence_resolution": "evidence resolution",
            "provisional_monitoring": "provisional tracking",
        }.get(next_stage, next_stage.replace("_", " "))
        return f"Escalate {label} to {stage_phrase}."

    def _stage_reason_for_item(bucket: str, item: dict[str, Any]) -> str:
        reason = _clean_text(item.get("reason")) or "Manual review required."
        if bucket == "interview_dependency":
            return f"The field still needs applicant confirmation before it can be treated as governed output. {reason}"
        if bucket == "conflict":
            return f"Materially competing values remain and need planner adjudication rather than silent auto-resolution. {reason}"
        if bucket == "evidence_weakness":
            return f"Current support is too weak or contextual to trust without stronger route evidence. {reason}"
        if bucket == "deterministic_override":
            return f"Deterministic governance prevented auto-acceptance and left the field in review-required state. {reason}"
        return reason

    def _add_field_action(bucket: str, item: dict[str, Any]) -> None:
        field_path = _clean_text(item.get("field_path"))
        field_id = _clean_text(item.get("field_id"))
        if not field_path and not field_id:
            return
        action_key = field_path or field_id
        if action_key in seen_field_action_keys:
            return
        seen_field_action_keys.add(action_key)
        next_stage = stage_map.get(bucket, "planner_review")
        label = _clean_text(item.get("label")) or field_id or field_path or "Unknown Field"
        priority = _priority_for_item(bucket, item)
        stage_reason = _stage_reason_for_item(bucket, item)
        actions.append({
            "action_id": f"{bucket}_{field_id or field_path}".replace(".", "_").replace("/", "_").lower(),
            "action_scope": "field",
            "priority": priority,
            "owner": owner_map.get(next_stage, "planner"),
            "category": bucket,
            "title": _title_for_item(bucket, label, next_stage),
            "rationale": stage_reason,
            "field_id": field_id,
            "field_path": field_path,
            "field_label": label,
            "field_paths": [value for value in [field_path] if value],
            "next_best_stage": next_stage,
            "stage_owner": owner_map.get(next_stage, "planner"),
            "stage_reason": stage_reason,
            "planner_critical": bool(item.get("planner_critical", False)),
            "status": _clean_text(item.get("status")) or "unresolved",
            "decision_basis": _clean_text(item.get("decision_basis")),
            "provisional_allowed": bucket == "evidence_weakness",
            "source_review_bucket": bucket,
            "escalation_trigger": review_labels.get(bucket, bucket.replace("_", " ")),
        })

    for bucket in ("conflict", "interview_dependency", "evidence_weakness", "deterministic_override"):
        items = groups.get(bucket, []) if isinstance(groups.get(bucket), list) else []
        for item in items:
            if isinstance(item, dict):
                _add_field_action(bucket, item)

    def _add_run_action(
        action_id: str,
        *,
        priority: str,
        category: str,
        title: str,
        rationale: str,
        next_stage: str = "planner_review",
    ) -> None:
        actions.append({
            "action_id": action_id,
            "action_scope": "run",
            "priority": priority,
            "owner": owner_map.get(next_stage, "planner"),
            "category": category,
            "title": title,
            "rationale": rationale,
            "field_paths": [],
            "next_best_stage": next_stage,
            "stage_owner": owner_map.get(next_stage, "planner"),
            "stage_reason": rationale,
            "planner_critical": False,
            "status": "review_required",
            "provisional_allowed": False,
            "source_review_bucket": category,
            "escalation_trigger": category.replace("_", " "),
        })

    if bool(translation_alerts.get("has_governance_attention", False)):
        _add_run_action(
            "keep_translation_outputs_review_tagged",
            priority="HIGH",
            category="downstream_gating",
            title="Keep governance-gated translated outputs review-tagged until their driving fields are resolved.",
            rationale="Shared review-priority governance reduced translation confidence for one or more downstream parameters.",
        )

    if bool(scenario_alerts.get("has_governance_attention", False)) or int(scenario_alerts.get("scenario_needs_review_variant_count", 0) or 0) > 0:
        _add_run_action(
            "treat_needs_review_scenarios_as_provisional",
            priority="HIGH",
            category="downstream_gating",
            title="Treat low-confidence scenario variants as provisional.",
            rationale="Scenario confidence was reduced by unresolved governance issues affecting downstream planner outputs.",
        )

    priority_rank = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    stage_rank = {"applicant_interview": 0, "evidence_resolution": 1, "planner_review": 2, "provisional_monitoring": 3}
    actions.sort(
        key=lambda item: (
            priority_rank.get(str(item.get("priority", "LOW")), 99),
            stage_rank.get(str(item.get("next_best_stage", "planner_review")), 99),
            str(item.get("field_label", item.get("title", ""))),
        )
    )

    next_stage_counts: dict[str, int] = {}
    for item in actions:
        next_stage = _clean_text(item.get("next_best_stage")) or "planner_review"
        next_stage_counts[next_stage] = next_stage_counts.get(next_stage, 0) + 1

    return {
        "summary": {
            "total_count": len(actions),
            "critical_count": sum(1 for item in actions if item.get("priority") == "CRITICAL"),
            "high_count": sum(1 for item in actions if item.get("priority") == "HIGH"),
            "field_linked_count": sum(1 for item in actions if item.get("action_scope") == "field"),
            "run_level_count": sum(1 for item in actions if item.get("action_scope") == "run"),
            "owners": sorted({str(item.get("owner", "")).strip() for item in actions if str(item.get("owner", "")).strip()}),
            "categories": sorted({str(item.get("category", "")).strip() for item in actions if str(item.get("category", "")).strip()}),
            "next_stage_counts": next_stage_counts,
        },
        "actions": actions,
    }


def build_escalation_registry(
    *,
    canonical_state: dict[str, Any] | None,
    manual_review_queue: dict[str, Any] | None,
    planner_action_queue: dict[str, Any] | None,
) -> dict[str, Any]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    field_resolution = state.get("field_resolution") if isinstance(state.get("field_resolution"), dict) else {}
    ledger = field_resolution.get("ledger", []) if isinstance(field_resolution.get("ledger"), list) else []
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    queue_groups = review_queue.get("groups", {}) if isinstance(review_queue.get("groups"), dict) else {}
    action_queue = planner_action_queue if isinstance(planner_action_queue, dict) else {}
    actions = action_queue.get("actions", []) if isinstance(action_queue.get("actions"), list) else []

    action_by_key: dict[str, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict) or _clean_text(action.get("action_scope")) != "field":
            continue
        for key in (_clean_text(action.get("field_path")), _clean_text(action.get("field_id"))):
            if key and key not in action_by_key:
                action_by_key[key] = action

    review_bucket_by_key: dict[str, str] = {}
    for bucket, items in queue_groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in (_clean_text(item.get("field_path")), _clean_text(item.get("field_id"))):
                if key and key not in review_bucket_by_key:
                    review_bucket_by_key[key] = str(bucket)

    current_stage_map = {
        "interview_dependency": "applicant_interview_pending",
        "evidence_weakness": "evidence_resolution_pending",
        "conflict": "planner_review_pending",
        "deterministic_override": "deterministic_override_pending",
    }
    owner_map = {
        "applicant_interview_pending": "applicant_interview",
        "evidence_resolution_pending": "evidence_resolution",
        "planner_review_pending": "planner",
        "deterministic_override_pending": "deterministic_core",
        "provisional_monitoring": "planner",
        "resolved_monitoring": "deterministic_core",
    }

    entries: list[dict[str, Any]] = []
    for item in ledger:
        if not isinstance(item, dict):
            continue
        field_id = _clean_text(item.get("field_id"))
        field_path = _clean_text(item.get("field_path"))
        if not field_id and not field_path:
            continue
        action = action_by_key.get(field_path) or action_by_key.get(field_id) or {}
        review_bucket = review_bucket_by_key.get(field_path) or review_bucket_by_key.get(field_id)
        status = _clean_text(item.get("accepted_status")) or "unresolved"
        unresolved = status in {"review_required", "conflicting", "missing", "unresolved"}
        next_best_stage = _clean_text(action.get("next_best_stage"))
        if not next_best_stage:
            next_best_stage = "planner_review" if unresolved else "provisional_monitoring"
        current_handling_stage = current_stage_map.get(review_bucket or "", "resolved_monitoring" if not unresolved else "planner_review_pending")
        if next_best_stage == "provisional_monitoring" and unresolved:
            current_handling_stage = "planner_review_pending"
        stage_reason = _clean_text(action.get("stage_reason")) or _clean_text(item.get("unresolved_reason")) or _clean_text(item.get("contradiction_summary")) or "Governed escalation registry entry."
        entries.append({
            "field_id": field_id,
            "field_path": field_path,
            "field_label": _clean_text(item.get("label")) or field_id or field_path or "Unknown Field",
            "accepted_status": status,
            "planner_critical": bool(item.get("planner_critical", False)),
            "review_bucket": review_bucket or ("resolved" if not unresolved else "uncategorized"),
            "current_handling_stage": current_handling_stage,
            "current_stage_owner": owner_map.get(current_handling_stage, "planner"),
            "next_escalation_target": next_best_stage,
            "next_stage_owner": _clean_text(action.get("stage_owner")) or owner_map.get(next_best_stage, "planner"),
            "stage_reason": stage_reason,
            "escalation_trigger": _clean_text(action.get("escalation_trigger")) or review_bucket or status,
            "provisional_allowed": bool(action.get("provisional_allowed", False)),
            "authoritative_source": "shared_escalation_registry",
        })

    entries.sort(key=lambda item: (not bool(item.get("planner_critical", False)), str(item.get("field_label", ""))))

    current_stage_counts: dict[str, int] = {}
    next_stage_counts: dict[str, int] = {}
    for item in entries:
        current_stage = _clean_text(item.get("current_handling_stage")) or "unknown"
        next_stage = _clean_text(item.get("next_escalation_target")) or "unknown"
        current_stage_counts[current_stage] = current_stage_counts.get(current_stage, 0) + 1
        next_stage_counts[next_stage] = next_stage_counts.get(next_stage, 0) + 1

    return {
        "summary": {
            "field_count": len(entries),
            "unresolved_field_count": sum(1 for item in entries if item.get("accepted_status") in {"review_required", "conflicting", "missing", "unresolved"}),
            "planner_critical_count": sum(1 for item in entries if bool(item.get("planner_critical", False))),
            "current_stage_counts": current_stage_counts,
            "next_stage_counts": next_stage_counts,
        },
        "fields": entries,
    }



def build_stage_transition_decisions(
    *,
    canonical_state: dict[str, Any] | None,
    escalation_registry: dict[str, Any] | None,
    planner_action_queue: dict[str, Any] | None,
) -> dict[str, Any]:
    registry = escalation_registry if isinstance(escalation_registry, dict) else {}
    fields = registry.get("fields", []) if isinstance(registry.get("fields"), list) else []
    action_queue = planner_action_queue if isinstance(planner_action_queue, dict) else {}
    actions = action_queue.get("actions", []) if isinstance(action_queue.get("actions"), list) else []
    action_by_key: dict[str, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        for key in (_clean_text(action.get("field_path")), _clean_text(action.get("field_id"))):
            if key and key not in action_by_key:
                action_by_key[key] = action

    decisions: list[dict[str, Any]] = []
    for entry in fields:
        if not isinstance(entry, dict):
            continue
        field_id = _clean_text(entry.get("field_id"))
        field_path = _clean_text(entry.get("field_path"))
        action = action_by_key.get(field_path) or action_by_key.get(field_id) or {}
        accepted_status = _clean_text(entry.get("accepted_status")) or "unresolved"
        current_stage = _clean_text(entry.get("current_handling_stage")) or "planner_review_pending"
        next_stage = _clean_text(entry.get("next_escalation_target")) or "planner_review"
        review_bucket = _clean_text(entry.get("review_bucket"))
        provisional_allowed = bool(entry.get("provisional_allowed", False) or action.get("provisional_allowed", False))

        if accepted_status == "resolved" and next_stage in {"provisional_monitoring", "resolved_monitoring"}:
            decision = "maintain_governed_acceptance"
            transition_state = "stable"
        elif next_stage == "applicant_interview":
            decision = "escalate_to_applicant_interview"
            transition_state = "pending"
        elif next_stage == "evidence_resolution":
            decision = "return_to_evidence_resolution"
            transition_state = "pending"
        elif next_stage == "planner_review":
            decision = "escalate_to_planner_review"
            transition_state = "pending"
        elif provisional_allowed:
            decision = "hold_as_provisional"
            transition_state = "held"
        else:
            decision = "retain_current_stage"
            transition_state = "held"

        rationale = _clean_text(action.get("stage_reason")) or _clean_text(entry.get("stage_reason")) or _clean_text(entry.get("escalation_trigger")) or "Governed transition decision recorded."
        decisions.append({
            "field_id": field_id,
            "field_path": field_path,
            "field_label": _clean_text(entry.get("field_label")) or field_id or field_path or "Unknown Field",
            "accepted_status": accepted_status,
            "review_bucket": review_bucket,
            "current_handling_stage": current_stage,
            "next_escalation_target": next_stage,
            "transition_decision": decision,
            "transition_state": transition_state,
            "planner_critical": bool(entry.get("planner_critical", False)),
            "provisional_allowed": provisional_allowed,
            "rationale": rationale,
            "stage_owner": _clean_text(action.get("stage_owner")) or _clean_text(entry.get("next_stage_owner")),
            "current_stage_owner": _clean_text(entry.get("current_stage_owner")),
            "authoritative_source": "shared_stage_transition_decisions",
        })

    decisions.sort(key=lambda item: (not bool(item.get("planner_critical", False)), str(item.get("field_label", ""))))
    decision_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for item in decisions:
        decision = _clean_text(item.get("transition_decision")) or "unknown"
        state = _clean_text(item.get("transition_state")) or "unknown"
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        "summary": {
            "field_count": len(decisions),
            "planner_critical_count": sum(1 for item in decisions if bool(item.get("planner_critical", False))),
            "decision_counts": decision_counts,
            "transition_state_counts": state_counts,
        },
        "fields": decisions,
    }


def build_field_governance_registry(
    *,
    canonical_state: dict[str, Any] | None,
    field_agent_consumption_audit: dict[str, Any] | None,
    manual_review_queue: dict[str, Any] | None,
    planner_action_queue: dict[str, Any] | None,
    escalation_registry: dict[str, Any] | None,
    stage_transition_decisions: dict[str, Any] | None,
) -> dict[str, Any]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    field_resolution = state.get("field_resolution") if isinstance(state.get("field_resolution"), dict) else {}
    ledger = field_resolution.get("ledger", []) if isinstance(field_resolution.get("ledger"), list) else []
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    queue_groups = review_queue.get("groups", {}) if isinstance(review_queue.get("groups"), dict) else {}
    actions = planner_action_queue.get("actions", []) if isinstance(planner_action_queue, dict) and isinstance(planner_action_queue.get("actions"), list) else []
    registry_fields = escalation_registry.get("fields", []) if isinstance(escalation_registry, dict) and isinstance(escalation_registry.get("fields"), list) else []
    transition_fields = stage_transition_decisions.get("fields", []) if isinstance(stage_transition_decisions, dict) and isinstance(stage_transition_decisions.get("fields"), list) else []
    audit_fields = field_agent_consumption_audit.get("fields", []) if isinstance(field_agent_consumption_audit, dict) and isinstance(field_agent_consumption_audit.get("fields"), list) else []

    def _index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in (_clean_text(item.get("field_path")), _clean_text(item.get("field_id"))):
                if key and key not in result:
                    result[key] = item
        return result

    action_by_key = _index(actions)
    escalation_by_key = _index(registry_fields)
    transition_by_key = _index(transition_fields)
    audit_by_key = _index(audit_fields)
    bucket_by_key: dict[str, str] = {}
    for bucket, items in queue_groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in (_clean_text(item.get("field_path")), _clean_text(item.get("field_id"))):
                if key and key not in bucket_by_key:
                    bucket_by_key[key] = str(bucket)

    entries: list[dict[str, Any]] = []
    for ledger_entry in ledger:
        if not isinstance(ledger_entry, dict):
            continue
        field_id = _clean_text(ledger_entry.get("field_id"))
        field_path = _clean_text(ledger_entry.get("field_path"))
        if not field_id and not field_path:
            continue
        action = action_by_key.get(field_path) or action_by_key.get(field_id) or {}
        escalation = escalation_by_key.get(field_path) or escalation_by_key.get(field_id) or {}
        transition = transition_by_key.get(field_path) or transition_by_key.get(field_id) or {}
        audit = audit_by_key.get(field_path) or audit_by_key.get(field_id) or {}
        route = ledger_entry.get("evidence_route_record") if isinstance(ledger_entry.get("evidence_route_record"), dict) else {}
        review_bucket = bucket_by_key.get(field_path) or bucket_by_key.get(field_id) or _clean_text(escalation.get("review_bucket"))
        accepted_status = _clean_text(ledger_entry.get("accepted_status")) or "unresolved"
        planner_critical = bool(ledger_entry.get("planner_critical", False))
        release_profile = ledger_entry.get("field_release_profile") if isinstance(ledger_entry.get("field_release_profile"), dict) else {}
        field_release_state = _clean_text(release_profile.get("release_state"))
        if not field_release_state:
            if accepted_status in {"conflicting", "missing"}:
                field_release_state = "BLOCKED"
            elif planner_critical and accepted_status in {"review_required", "unresolved"}:
                field_release_state = "BLOCKED"
            elif accepted_status in {"review_required", "unresolved"}:
                field_release_state = "PROVISIONAL"
            else:
                field_release_state = "READY"
        entries.append({
            "field_id": field_id,
            "field_path": field_path,
            "field_label": _clean_text(ledger_entry.get("label")) or field_id or field_path or "Unknown Field",
            "accepted_status": accepted_status,
            "planner_critical": planner_critical,
            "confidence_band": _clean_text(ledger_entry.get("confidence_band")) or "LOW",
            "review_bucket": review_bucket or "resolved",
            "current_handling_stage": _clean_text(escalation.get("current_handling_stage")),
            "next_escalation_target": _clean_text(escalation.get("next_escalation_target")) or _clean_text(action.get("next_best_stage")),
            "transition_decision": _clean_text(transition.get("transition_decision")),
            "transition_state": _clean_text(transition.get("transition_state")),
            "stage_reason": _clean_text(escalation.get("stage_reason")) or _clean_text(action.get("stage_reason")) or _clean_text(ledger_entry.get("unresolved_reason")) or _clean_text(ledger_entry.get("contradiction_summary")),
            "action_title": _clean_text(action.get("title")),
            "action_priority": _clean_text(action.get("priority")) or "LOW",
            "accepted_value": ledger_entry.get("accepted_value"),
            "accepted_source_hierarchy": _clean_text(ledger_entry.get("accepted_source_hierarchy")),
            "accepted_specificity": _clean_text(ledger_entry.get("accepted_specificity")),
            "field_release_state": field_release_state,
            "export_readiness_tier": _clean_text(release_profile.get("export_readiness_tier")),
            "translation_use_policy": _clean_text(release_profile.get("translation_use_policy")),
            "scenario_use_policy": _clean_text(release_profile.get("scenario_use_policy")),
            "support_strength": _clean_text(route.get("support_strength")),
            "weak_support_only": bool(route.get("weak_support_only", False)),
            "agent_dispositions": dict(audit.get("disposition_counts", {})) if isinstance(audit.get("disposition_counts"), dict) else {},
            "linked_agents": list(audit.get("linked_agent_ids", [])) if isinstance(audit.get("linked_agent_ids"), list) else [],
            "authoritative_source": "shared_field_governance_registry",
        })

    entries.sort(key=lambda item: (not bool(item.get("planner_critical", False)), str(item.get("field_label", ""))))
    review_bucket_counts: dict[str, int] = {}
    transition_counts: dict[str, int] = {}
    for item in entries:
        bucket = _clean_text(item.get("review_bucket")) or "unknown"
        decision = _clean_text(item.get("transition_decision")) or "unknown"
        review_bucket_counts[bucket] = review_bucket_counts.get(bucket, 0) + 1
        transition_counts[decision] = transition_counts.get(decision, 0) + 1

    return {
        "summary": {
            "field_count": len(entries),
            "unresolved_field_count": sum(1 for item in entries if item.get("accepted_status") in {"review_required", "conflicting", "missing", "unresolved"}),
            "planner_critical_count": sum(1 for item in entries if bool(item.get("planner_critical", False))),
            "review_bucket_counts": review_bucket_counts,
            "transition_decision_counts": transition_counts,
        },
        "fields": entries,
    }


def build_governed_release_decision(
    *,
    manual_review_queue: dict[str, Any] | None,
    planner_action_queue: dict[str, Any] | None,
    stage_transition_decisions: dict[str, Any] | None,
    field_governance_registry: dict[str, Any] | None,
    interview_priority_plan: dict[str, Any] | None = None,
    translation_governance_alerts: dict[str, Any] | None = None,
    scenario_governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    review_summary = review_queue.get("summary", {}) if isinstance(review_queue.get("summary"), dict) else {}
    action_queue = planner_action_queue if isinstance(planner_action_queue, dict) else {}
    action_summary = action_queue.get("summary", {}) if isinstance(action_queue.get("summary"), dict) else {}
    transition_fields = stage_transition_decisions.get("fields", []) if isinstance(stage_transition_decisions, dict) and isinstance(stage_transition_decisions.get("fields"), list) else []
    governance_fields = field_governance_registry.get("fields", []) if isinstance(field_governance_registry, dict) and isinstance(field_governance_registry.get("fields"), list) else []
    interview_plan = interview_priority_plan if isinstance(interview_priority_plan, dict) else {}
    translation_alerts = translation_governance_alerts if isinstance(translation_governance_alerts, dict) else {}
    scenario_alerts = scenario_governance_alerts if isinstance(scenario_governance_alerts, dict) else {}

    transition_by_key: dict[str, dict[str, Any]] = {}
    for item in transition_fields:
        if not isinstance(item, dict):
            continue
        for key in (_clean_text(item.get("field_path")), _clean_text(item.get("field_id"))):
            if key and key not in transition_by_key:
                transition_by_key[key] = item

    blockers: list[dict[str, Any]] = []
    provisional_fields: list[dict[str, Any]] = []
    warning_notes: list[str] = []

    for item in governance_fields:
        if not isinstance(item, dict):
            continue
        field_id = _clean_text(item.get("field_id"))
        field_path = _clean_text(item.get("field_path"))
        if not field_id and not field_path:
            continue
        transition = transition_by_key.get(field_path) or transition_by_key.get(field_id) or {}
        label = _clean_text(item.get("field_label")) or field_id or field_path or "Unknown Field"
        accepted_status = _clean_text(item.get("accepted_status")) or "unresolved"
        review_bucket = _clean_text(item.get("review_bucket")) or "resolved"
        next_stage = _clean_text(item.get("next_escalation_target")) or _clean_text(transition.get("next_escalation_target")) or "planner_review"
        transition_decision = _clean_text(item.get("transition_decision")) or _clean_text(transition.get("transition_decision")) or "retain_current_stage"
        confidence_band = _clean_text(item.get("confidence_band")) or "LOW"
        planner_critical = bool(item.get("planner_critical", False))
        field_release_state = _clean_text(item.get("field_release_state")) or ""
        provisional_allowed = bool(transition.get("provisional_allowed", False) or item.get("weak_support_only", False) or transition_decision == "hold_as_provisional" or field_release_state == "PROVISIONAL")
        stage_reason = _clean_text(item.get("stage_reason")) or _clean_text(transition.get("rationale")) or "Governed release review required."
        unresolved = accepted_status in {"review_required", "conflicting", "missing", "unresolved"} or field_release_state in {"BLOCKED", "PROVISIONAL"}

        blocker_category = ""
        if planner_critical and unresolved:
            if next_stage == "applicant_interview" or review_bucket == "interview_dependency":
                blocker_category = "applicant_interview"
            elif next_stage == "evidence_resolution" and not provisional_allowed:
                blocker_category = "evidence_resolution"
            elif accepted_status == "conflicting" or review_bucket in {"conflict", "deterministic_override"} or next_stage == "planner_review":
                blocker_category = "planner_review"
            elif not provisional_allowed:
                blocker_category = "planner_review"

        entry = {
            "field_id": field_id,
            "field_path": field_path,
            "field_label": label,
            "accepted_status": accepted_status,
            "review_bucket": review_bucket,
            "confidence_band": confidence_band,
            "planner_critical": planner_critical,
            "field_release_state": field_release_state,
            "export_readiness_tier": _clean_text(item.get("export_readiness_tier")),
            "translation_use_policy": _clean_text(item.get("translation_use_policy")),
            "scenario_use_policy": _clean_text(item.get("scenario_use_policy")),
            "next_escalation_target": next_stage,
            "transition_decision": transition_decision,
            "reason": stage_reason,
        }
        if blocker_category:
            blockers.append({
                **entry,
                "blocking_category": blocker_category,
                "authoritative_source": "shared_governed_release_decision",
            })
        elif unresolved or provisional_allowed:
            provisional_fields.append({
                **entry,
                "provisional_reason": stage_reason,
                "authoritative_source": "shared_governed_release_decision",
            })

    blocker_field_paths = [item["field_path"] for item in blockers if item.get("field_path")]
    blocker_categories = sorted({str(item.get("blocking_category", "")).strip() for item in blockers if str(item.get("blocking_category", "")).strip()})
    provisional_field_paths = [item["field_path"] for item in provisional_fields if item.get("field_path")]

    if blockers:
        warning_notes.append("Planner-critical fields still block governed release and must remain unresolved in the packet rather than flattened into certainty.")
    if provisional_fields:
        warning_notes.append("Some governed fields may proceed only as provisional and should remain clearly review-tagged downstream.")
    if bool(translation_alerts.get("has_governance_attention", False)):
        warning_notes.append("Translation outputs are governance-gated by unresolved upstream field decisions.")
    if bool(scenario_alerts.get("has_governance_attention", False)) or int(scenario_alerts.get("scenario_needs_review_variant_count", 0) or 0) > 0:
        warning_notes.append("Scenario outputs are governance-gated by unresolved upstream field decisions.")

    interview_blocker_count = sum(1 for item in blockers if item.get("blocking_category") == "applicant_interview")
    evidence_blocker_count = sum(1 for item in blockers if item.get("blocking_category") == "evidence_resolution")
    planner_blocker_count = sum(1 for item in blockers if item.get("blocking_category") == "planner_review")

    interview_state = "BLOCKED" if interview_blocker_count > 0 else ("PENDING" if interview_plan.get("question_sequence") else "READY")
    translation_state = "BLOCKED" if blockers else ("PROVISIONAL" if bool(translation_alerts.get("has_governance_attention", False)) or provisional_fields else "READY")
    scenario_state = "BLOCKED" if blockers else ("PROVISIONAL" if bool(scenario_alerts.get("has_governance_attention", False)) or int(scenario_alerts.get("scenario_needs_review_variant_count", 0) or 0) > 0 or provisional_fields else "READY")
    planner_packet_state = "BLOCKED" if blockers else ("READY_WITH_WARNINGS" if provisional_fields or int(review_summary.get("total_count", 0) or 0) > 0 else "READY")
    final_export_state = "BLOCKED" if blockers else ("PROVISIONAL" if provisional_fields else "READY")

    return {
        "summary": {
            "release_state": final_export_state,
            "ready_for_final_export": final_export_state == "READY",
            "ready_for_planner_packet": planner_packet_state in {"READY", "READY_WITH_WARNINGS"},
            "blocking_field_count": len(blockers),
            "provisional_field_count": len(provisional_fields),
            "blocking_category_counts": {
                "applicant_interview": interview_blocker_count,
                "evidence_resolution": evidence_blocker_count,
                "planner_review": planner_blocker_count,
            },
            "blocking_categories": blocker_categories,
            "interview_state": interview_state,
            "translation_state": translation_state,
            "scenario_state": scenario_state,
            "planner_packet_state": planner_packet_state,
            "planner_action_total_count": int(action_summary.get("total_count", 0) or 0),
            "manual_review_total_count": int(review_summary.get("total_count", 0) or 0),
        },
        "blockers": blockers,
        "provisional_fields": provisional_fields,
        "blocker_field_paths": blocker_field_paths,
        "provisional_field_paths": provisional_field_paths,
        "warning_notes": warning_notes,
        "authoritative_source": "shared_governed_release_decision",
    }


def build_field_governance_core(
    *,
    canonical_state: dict[str, Any] | None,
    field_agent_consumption_audit: dict[str, Any] | None = None,
    translation_governance_alerts: dict[str, Any] | None = None,
    scenario_governance_alerts: dict[str, Any] | None = None,
    interview_priority_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manual_review_queue = build_manual_review_queue(canonical_state if isinstance(canonical_state, dict) else {}, field_agent_consumption_audit)
    planner_action_queue = build_planner_action_queue(
        manual_review_queue=manual_review_queue,
        interview_priority_plan=interview_priority_plan,
        translation_governance_alerts=translation_governance_alerts,
        scenario_governance_alerts=scenario_governance_alerts,
    )
    escalation_registry = build_escalation_registry(
        canonical_state=canonical_state,
        manual_review_queue=manual_review_queue,
        planner_action_queue=planner_action_queue,
    )
    stage_transition_decisions = build_stage_transition_decisions(
        canonical_state=canonical_state,
        escalation_registry=escalation_registry,
        planner_action_queue=planner_action_queue,
    )
    field_governance_registry = build_field_governance_registry(
        canonical_state=canonical_state,
        field_agent_consumption_audit=field_agent_consumption_audit,
        manual_review_queue=manual_review_queue,
        planner_action_queue=planner_action_queue,
        escalation_registry=escalation_registry,
        stage_transition_decisions=stage_transition_decisions,
    )
    governed_release_decision = build_governed_release_decision(
        manual_review_queue=manual_review_queue,
        planner_action_queue=planner_action_queue,
        stage_transition_decisions=stage_transition_decisions,
        field_governance_registry=field_governance_registry,
        interview_priority_plan=interview_priority_plan,
        translation_governance_alerts=translation_governance_alerts,
        scenario_governance_alerts=scenario_governance_alerts,
    )
    return {
        "manual_review_queue": manual_review_queue,
        "planner_action_queue": planner_action_queue,
        "escalation_registry": escalation_registry,
        "stage_transition_decisions": stage_transition_decisions,
        "field_governance_registry": field_governance_registry,
        "governed_release_decision": governed_release_decision,
        "summary": {
            "manual_review_total_count": int((manual_review_queue.get("summary") or {}).get("total_count", 0)),
            "planner_action_total_count": int((planner_action_queue.get("summary") or {}).get("total_count", 0)),
            "escalation_field_count": int((escalation_registry.get("summary") or {}).get("field_count", 0)),
            "transition_field_count": int((stage_transition_decisions.get("summary") or {}).get("field_count", 0)),
            "governance_field_count": int((field_governance_registry.get("summary") or {}).get("field_count", 0)),
            "release_blocking_field_count": int((governed_release_decision.get("summary") or {}).get("blocking_field_count", 0)),
            "release_state": _clean_text((governed_release_decision.get("summary") or {}).get("release_state")),
        },
    }
