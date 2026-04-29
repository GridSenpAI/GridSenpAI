#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

JsonObj = dict[str, Any]


def _read_json_any(path: Path | None) -> Any:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": str(exc), "_path": str(path)}


def _as_dict(value: Any) -> JsonObj:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _find_first(root: Path, *relative_candidates: str, name: str | None = None) -> Path | None:
    for rel in relative_candidates:
        candidate = root / rel
        if candidate.exists():
            return candidate
    if name:
        matches = sorted(root.rglob(name))
        return matches[0] if matches else None
    return None


def _status_from_bool(ok: bool, warn: bool = False) -> str:
    if ok:
        return "GREEN"
    if warn:
        return "YELLOW"
    return "RED"


def _load_pipeline_status(run_dir: Path) -> str:
    payload = _as_dict(_read_json_any(_find_first(run_dir, "pipeline_summary.json", name="pipeline_summary.json")))
    return str(payload.get("status") or payload.get("pipeline_status") or "UNKNOWN")


def _manifest_health(run_dir: Path) -> JsonObj:
    manifest = _as_dict(_read_json_any(_find_first(run_dir, "exports/run_manifest.json", "run_manifest.json", name="run_manifest.json")))
    summary = _as_dict(manifest.get("summary"))
    exports = _as_dict(manifest.get("exports"))
    packet_generated = summary.get("planner_packet_generated")
    if packet_generated is None:
        packet_generated = summary.get("planner_packet_ready")
    if packet_generated is None:
        packet_generated = bool(_find_first(run_dir, "exports/planner_packet.pdf", name="planner_packet.pdf"))
    return {
        "status": manifest.get("status", "UNKNOWN"),
        "planner_packet_generated": bool(packet_generated),
        "planner_packet_ready_for_review": bool(summary.get("planner_packet_ready_for_review", packet_generated)),
        "planner_packet_final_ready": bool(summary.get("planner_packet_final_ready") or summary.get("final_export_ready")),
        "planner_packet_release_state": summary.get("planner_packet_release_state") or summary.get("planner_readiness_state") or "UNKNOWN",
        "draft_outputs_allowed": bool(summary.get("draft_outputs_allowed", False)),
        "interview_state": summary.get("interview_completion_state") or summary.get("interview_state") or "UNKNOWN",
        "export_count": len(exports) if exports else 0,
    }


def _load_ocr_payload(run_dir: Path) -> JsonObj:
    extraction = _as_dict(_read_json_any(_find_first(run_dir, "stages/extraction.json", "extraction.json", "extraction_result.json", name="extraction.json")))
    for key in ("ocr_result", "ocr", "ocr_summary"):
        if isinstance(extraction.get(key), dict):
            return extraction[key]
    standalone = _as_dict(_read_json_any(_find_first(run_dir, "stages/extraction__ocr.json", "extraction__ocr.json", "ocr_result.json", name="extraction__ocr.json")))
    return standalone


def _page_char_count(document: JsonObj) -> int:
    direct = document.get("char_count")
    try:
        return int(direct or 0)
    except Exception:
        pass
    total = 0
    for page in _as_list(document.get("pages")):
        if isinstance(page, dict):
            try:
                total += int(page.get("char_count") or 0)
            except Exception:
                continue
    return total


def _ocr_health(run_dir: Path) -> JsonObj:
    ocr = _load_ocr_payload(run_dir)
    provider_health = _as_dict(ocr.get("provider_health"))
    documents = _as_list(ocr.get("document_results")) or _as_list(ocr.get("documents")) or _as_list(ocr.get("results"))
    failed = [item for item in documents if isinstance(item, dict) and "FAILED" in str(item.get("ocr_status") or item.get("status") or "").upper()]
    chars = sum(_page_char_count(item) for item in documents if isinstance(item, dict))
    status = str(provider_health.get("aggregate_status") or ocr.get("status") or "UNKNOWN")
    if documents and chars == 0 and len(failed) == len(documents):
        health = "RED"
    elif documents and failed:
        health = "YELLOW"
    else:
        health = _status_from_bool(chars > 0, warn=bool(documents))
    return {
        "status": status,
        "document_result_count": len(documents),
        "failed_document_count": len(failed),
        "char_count": chars,
        "provider_available": bool(ocr.get("provider_available", False)),
        "health": health,
    }


def _load_ledger_rows(run_dir: Path) -> list[JsonObj]:
    payload = _read_json_any(_find_first(run_dir, "exports/planner_field_ledger.json", "planner_field_ledger.json", "stages/canonical_state__planner_field_ledger.json", name="planner_field_ledger.json"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    payload_dict = _as_dict(payload)
    for key in ("rows", "planner_field_ledger", "ledger", "field_ledger"):
        rows = payload_dict.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _trace_text(row: JsonObj) -> str:
    trace = row.get("adjudication_trace")
    if isinstance(trace, dict):
        parts = [
            trace.get("accepted_value_text"),
            trace.get("planner_narrative"),
            trace.get("winner_summary"),
            trace.get("release_summary"),
        ]
        return " ".join(str(part) for part in parts if part not in (None, ""))
    return str(trace or "")


def _ledger_health(run_dir: Path) -> JsonObj:
    rows = _load_ledger_rows(run_dir)
    bad_confidence: list[str] = []
    trace_conflicts: list[str] = []
    contaminated_accepted: list[str] = []
    terminal_decision_count = 0
    for row in rows:
        field = str(row.get("field_path") or row.get("field_id") or "<unknown>")
        score = row.get("confidence_score")
        try:
            if score is not None and not (0.0 <= float(score) <= 1.0):
                bad_confidence.append(field)
        except Exception:
            bad_confidence.append(field)
        accepted = str(row.get("accepted_value", "")).strip()
        status = str(row.get("status", "")).strip().upper()
        if status:
            terminal_decision_count += 1
        if accepted and accepted.upper() not in {"UNRESOLVED", "NONE", "NULL", ""}:
            trace = _trace_text(row)
            accepted_text = accepted[:80]
            if "accepted" in trace.lower() and accepted_text not in trace:
                trace_conflicts.append(field)
            lowered = accepted.lower()
            if any(marker in lowered for marker in (" page 1", " revision", " drawn by", " checked by", " title block")):
                contaminated_accepted.append(field)
    health = _status_from_bool(
        not bad_confidence and not trace_conflicts and not contaminated_accepted and bool(rows),
        warn=bool(rows),
    )
    return {
        "row_count": len(rows),
        "terminal_decision_count": terminal_decision_count,
        "bad_confidence_count": len(bad_confidence),
        "trace_conflict_count": len(trace_conflicts),
        "contaminated_accepted_count": len(contaminated_accepted),
        "health": health,
        "bad_confidence_examples": bad_confidence[:10],
        "trace_conflict_examples": trace_conflicts[:10],
        "contaminated_accepted_examples": contaminated_accepted[:10],
    }


def _find_output_parameter(outputs: Iterable[Any], path: str) -> Any:
    for item in outputs:
        if isinstance(item, dict) and item.get("parameter_path") == path:
            return item.get("value")
    return None


def _translation_health(run_dir: Path) -> JsonObj:
    translated = _as_dict(_read_json_any(_find_first(run_dir, "exports/translated_parameters.json", "stages/translation.json", "translated_parameters.json", name="translated_parameters.json")))
    outputs = _as_dict(translated.get("model_outputs"))
    steady = _as_dict(outputs.get("steady_state"))
    output_parameters = _as_list(translated.get("output_parameters"))
    steady_p_mw = steady.get("p_mw")
    if steady_p_mw is None:
        steady_p_mw = _find_output_parameter(output_parameters, "steady_state.p_mw")
    zip_model = _as_dict(outputs.get("zip_model")) or _as_dict(outputs.get("load_model", {})).get("zip_model", {})
    if not isinstance(zip_model, dict):
        zip_model = {}
    zip_values = [zip_model.get("constant_power_fraction"), zip_model.get("constant_current_fraction"), zip_model.get("constant_impedance_fraction")]
    zip_numeric: list[float] = []
    for value in zip_values:
        try:
            zip_numeric.append(float(value))
        except Exception:
            pass
    zip_safe = len(zip_numeric) == 3 and all(0.0 <= value <= 1.0 for value in zip_numeric) and abs(sum(zip_numeric) - 1.0) <= 0.01
    return {
        "status": translated.get("status", "UNKNOWN"),
        "steady_state_p_mw": steady_p_mw,
        "zip_model_present": bool(zip_model),
        "zip_model_safe": zip_safe if zip_model else False,
        "health": _status_from_bool(steady_p_mw is not None and (not zip_model or zip_safe), warn=steady_p_mw is not None),
    }


def _agent_prompt_health(run_dir: Path) -> JsonObj:
    audit_dir = run_dir / "agent_audit"
    audit_files = sorted(audit_dir.glob("*.json")) if audit_dir.exists() else []
    oversized_failures: list[str] = []
    policy_blocked: list[str] = []
    chunked_calls = 0
    unchunked_large_calls = 0
    failed_chunks = 0
    deterministic_fallback_count = 0
    largest_prompt = 0
    examples: list[JsonObj] = []
    for path in audit_files:
        payload = _as_dict(_read_json_any(path))
        response = _as_dict(payload.get("response_payload"))
        prompt_payload = _as_dict(payload.get("prompt_payload"))
        runtime_payload = _as_dict(response.get("runtime_payload"))
        prompt_health = _as_dict(response.get("agent_prompt_health"))
        telemetry = _as_dict(prompt_payload.get("prompt_telemetry")) or _as_dict(payload.get("prompt_telemetry"))
        status_blob = " ".join(str(value) for value in (payload.get("status"), response.get("status"), payload.get("failure_reason"), response.get("failure_reason"))).upper()
        text_blob = json.dumps({"status": status_blob, "response": response, "telemetry": telemetry}, default=str)[:10000].upper()
        if "PROMPT_TOO_LARGE" in text_blob or "PROMPT_BUDGET_EXCEEDED" in text_blob:
            oversized_failures.append(path.name)
        if "POLICY_BLOCKED" in status_blob:
            policy_blocked.append(path.name)
        chunk_count = int(prompt_health.get("chunk_count", runtime_payload.get("chunk_count", telemetry.get("chunk_count", 0))) or 0)
        if chunk_count > 0:
            chunked_calls += 1
        failed_chunks += int(prompt_health.get("failed_chunk_count", runtime_payload.get("failed_chunk_count", telemetry.get("failed_chunk_count", 0))) or 0)
        largest = int(prompt_health.get("largest_chunk_chars", runtime_payload.get("largest_chunk_chars", telemetry.get("largest_chunk_chars", 0))) or 0)
        compacted = int(telemetry.get("total_prompt_chars_after_compaction", telemetry.get("prompt_size_chars", payload.get("prompt_size_chars", 0))) or 0)
        max_prompt = int(telemetry.get("max_prompt_chars", prompt_health.get("max_prompt_chars", payload.get("max_prompt_chars", 0))) or 0)
        largest_prompt = max(largest_prompt, largest, compacted)
        if max_prompt and compacted > max_prompt and chunk_count == 0 and bool(telemetry.get("chunking_enabled", False)):
            unchunked_large_calls += 1
            examples.append({"audit_file": path.name, "compacted_chars": compacted, "max_prompt_chars": max_prompt})
        if bool(prompt_health.get("fallback_used", runtime_payload.get("fallback_used", False))):
            deterministic_fallback_count += 1
    health = "GREEN"
    if oversized_failures or unchunked_large_calls:
        health = "RED"
    elif failed_chunks or deterministic_fallback_count or policy_blocked:
        health = "YELLOW"
    return {
        "audit_file_count": len(audit_files),
        "oversized_prompt_failures": len(oversized_failures),
        "policy_blocked_calls": len(policy_blocked),
        "chunked_agent_calls": chunked_calls,
        "unchunked_large_agent_calls": unchunked_large_calls,
        "failed_advisory_chunks": failed_chunks,
        "deterministic_fallback_count": deterministic_fallback_count,
        "largest_prompt_or_chunk_chars": largest_prompt,
        "oversized_failure_examples": oversized_failures[:10],
        "policy_blocked_examples": policy_blocked[:10],
        "unchunked_large_examples": examples[:10],
        "health": health,
    }


def audit_run(run_dir: Path) -> JsonObj:
    run_dir = run_dir.resolve()
    return {
        "run_dir": str(run_dir),
        "pipeline_status": _load_pipeline_status(run_dir),
        "manifest": _manifest_health(run_dir),
        "ocr": _ocr_health(run_dir),
        "ledger": _ledger_health(run_dir),
        "translation": _translation_health(run_dir),
        "agent_prompt_health": _agent_prompt_health(run_dir),
    }


def _print_report(report: JsonObj) -> None:
    print(f"Run: {report['run_dir']}")
    print(f"Pipeline status: {report['pipeline_status']}")
    for section in ("manifest", "ocr", "ledger", "translation", "agent_prompt_health"):
        payload = _as_dict(report[section])
        health = payload.get("health", "INFO")
        print(f"\n[{health}] {section}")
        for key, value in payload.items():
            if key != "health":
                print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a GridSenpAI run directory for planner-output quality risks.")
    parser.add_argument("run_dir", type=Path, help="Path to a single runs/<run_id> directory.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a compact text report.")
    args = parser.parse_args()
    if not args.run_dir.exists():
        print(f"ERROR: run directory does not exist: {args.run_dir}", file=sys.stderr)
        return 2
    if not args.run_dir.is_dir():
        print(f"ERROR: path is not a directory: {args.run_dir}", file=sys.stderr)
        return 2
    report = audit_run(args.run_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
