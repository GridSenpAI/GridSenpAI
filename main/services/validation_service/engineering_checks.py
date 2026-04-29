from __future__ import annotations

import uuid
from typing import Any


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_issue(
    *,
    code: str,
    severity: str,
    message: str,
    field_path: str = "",
    recommendation: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "issue_id": f"engval_{uuid.uuid4().hex[:12]}",
        "code": code,
        "severity": severity,
        "message": message,
        "field_path": field_path,
        "source_stage": "validation",
        "recommendation": recommendation,
        "metadata": metadata or {},
    }


def _build_review_flag(
    *,
    category: str,
    severity: str,
    message: str,
    field_path: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "review_flag_id": f"rf_{uuid.uuid4().hex[:12]}",
        "category": category,
        "severity": severity,
        "status": "OPEN",
        "message": message,
        "field_path": field_path,
        "record_ids": [],
        "metadata": metadata or {},
    }


def _get_nested(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _unwrap_wrapped_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _get_engineering_model_value(engineering_model: dict[str, Any], path: str) -> Any:
    current: Any = engineering_model
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return _unwrap_wrapped_value(current)




def _normalize_truthy_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "present", "available"}:
            return True
        if normalized in {"false", "no", "n", "0", "absent", "missing", "not_present"}:
            return False
    return None


def _get_accepted_field_index(canonical_state: dict[str, Any]) -> dict[str, Any]:
    field_resolution = canonical_state.get("field_resolution")
    if isinstance(field_resolution, dict):
        accepted = field_resolution.get("accepted_field_index")
        if isinstance(accepted, dict):
            return accepted
    accepted = canonical_state.get("accepted_planner_field_index")
    if isinstance(accepted, dict):
        return accepted
    return {}


def _get_accepted_field_entry(canonical_state: dict[str, Any], field_id: str) -> dict[str, Any] | None:
    accepted_index = _get_accepted_field_index(canonical_state)
    entry = accepted_index.get(field_id)
    if isinstance(entry, dict):
        return entry
    return None


def _get_accepted_field_value(canonical_state: dict[str, Any], field_id: str) -> Any:
    entry = _get_accepted_field_entry(canonical_state, field_id)
    if not isinstance(entry, dict):
        return None
    if "accepted_value" in entry:
        return entry.get("accepted_value")
    if "value" in entry:
        return entry.get("value")
    return None


def _accepted_field_path(field_id: str) -> str:
    return f"field_resolution.accepted_field_index.{field_id}.accepted_value"

def _sum_numeric(values: list[Any]) -> float:
    total = 0.0
    for value in values:
        numeric = _safe_float(value)
        if numeric is not None:
            total += numeric
    return total


def _coerce_engineering_transformers(engineering_model: dict[str, Any]) -> list[dict[str, Any]]:
    transformers = _get_engineering_model_value(
        engineering_model,
        "facility_electrical_system.transformers",
    )
    if not isinstance(transformers, list):
        return []
    return [item for item in transformers if isinstance(item, dict)]


def _engineering_transformer_ratings(transformers: list[dict[str, Any]]) -> list[float]:
    ratings: list[float] = []
    for transformer in transformers:
        rating = _safe_float(_get_engineering_model_value(transformer, "rating_mva"))
        if rating is not None:
            ratings.append(rating)
    return ratings


def _resolve_frequency_hz(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
) -> tuple[float | None, str]:
    engineering_value = _safe_float(
        _get_engineering_model_value(
            engineering_model,
            "project_context.frequency_hz",
        )
    )
    if engineering_value is not None:
        return engineering_value, "engineering_model.project_context.frequency_hz"

    facility_value = _safe_float(facility.get("frequency_hz"))
    return facility_value, "facility.frequency_hz"


def _resolve_poi_voltage_kv(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
) -> tuple[float | None, str]:
    engineering_value = _safe_float(
        _get_engineering_model_value(
            engineering_model,
            "interconnection_context.point_of_interconnection.poi_voltage_kv",
        )
    )
    if engineering_value is not None:
        return (
            engineering_value,
            "engineering_model.interconnection_context.point_of_interconnection.poi_voltage_kv",
        )

    facility_value = _safe_float(facility.get("poi_voltage_kv"))
    return facility_value, "facility.poi_voltage_kv"


def _resolve_phase_loads(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
) -> list[tuple[str, float | None, str]]:
    load_blocks = _get_engineering_model_value(engineering_model, "load_system.load_blocks")

    if isinstance(load_blocks, list) and load_blocks:
        resolved: list[tuple[str, float | None, str]] = []
        for index, block in enumerate(load_blocks):
            if not isinstance(block, dict):
                continue

            block_name = _safe_str(block.get("name")) or f"block_{index + 1}"
            connected_load = _safe_float(
                _get_engineering_model_value(block, "connected_load_mw")
            )
            demand_load = _safe_float(
                _get_engineering_model_value(block, "demand_load_mw")
            )

            value = connected_load if connected_load is not None else demand_load
            field_path = (
                f"engineering_model.load_system.load_blocks[{index}].connected_load_mw"
                if connected_load is not None
                else f"engineering_model.load_system.load_blocks[{index}].demand_load_mw"
            )
            resolved.append((block_name, value, field_path))

        if resolved:
            return resolved

    phase_1_mw = _safe_float(_get_nested(facility, "load_schedule.phase_1_mw"))
    phase_2_mw = _safe_float(_get_nested(facility, "load_schedule.phase_2_mw"))
    phase_3_mw = _safe_float(_get_nested(facility, "load_schedule.phase_3_mw"))

    return [
        ("Phase 1", phase_1_mw, "facility.load_schedule.phase_1_mw"),
        ("Phase 2", phase_2_mw, "facility.load_schedule.phase_2_mw"),
        ("Phase 3", phase_3_mw, "facility.load_schedule.phase_3_mw"),
    ]


def _resolve_generator_present_and_count(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
) -> tuple[bool, float | None, str]:
    generator_units = _get_engineering_model_value(
        engineering_model,
        "backup_power_system.generator_units",
    )
    generator_plant_present = _get_engineering_model_value(
        engineering_model,
        "backup_power_system.generator_plant_present",
    )

    if isinstance(generator_units, list) and generator_units:
        unit_count_total = 0.0
        any_count = False

        for index, unit in enumerate(generator_units):
            if not isinstance(unit, dict):
                continue

            count_value = _safe_float(_get_engineering_model_value(unit, "count"))
            if count_value is not None:
                unit_count_total += count_value
                any_count = True

        if any_count:
            present = bool(generator_plant_present) if generator_plant_present is not None else unit_count_total > 0
            return present, unit_count_total, "engineering_model.backup_power_system.generator_units"

        present = bool(generator_plant_present) if generator_plant_present is not None else True
        return present, None, "engineering_model.backup_power_system.generator_units"

    present = bool(_get_nested(facility, "generators.present"))
    count = _safe_float(_get_nested(facility, "generators.count"))
    return present, count, "facility.generators.count"

def _validate_generator_capacity_against_load(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
    total_declared_load_mw: float,
    warnings: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    generator_units = _get_engineering_model_value(
        engineering_model,
        "backup_power_system.generator_units",
    )

    generator_capacity_total = 0.0
    capacity_found = False

    if isinstance(generator_units, list):
        for index, unit in enumerate(generator_units):
            if not isinstance(unit, dict):
                continue

            rating = _safe_float(_get_engineering_model_value(unit, "rating_mw"))
            count = _safe_float(_get_engineering_model_value(unit, "count"))

            if rating is not None and count is not None:
                generator_capacity_total += rating * count
                capacity_found = True

    if capacity_found and total_declared_load_mw > 0:
        if generator_capacity_total < total_declared_load_mw * 0.5:
            warnings.append(
                _build_issue(
                    code="GENERATOR_CAPACITY_SUSPICIOUS",
                    severity="warning",
                    message=(
                        "Total backup generator capacity appears significantly smaller "
                        "than declared facility load."
                    ),
                    field_path="engineering_model.backup_power_system.generator_units",
                    recommendation=(
                        "Verify generator sizing or confirm that generators are not intended "
                        "to support full facility load."
                    ),
                    metadata={
                        "generator_capacity_mw": generator_capacity_total,
                        "facility_load_mw": total_declared_load_mw,
                    },
                )
            )

            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Generator capacity appears inconsistent with facility load.",
                    field_path="engineering_model.backup_power_system.generator_units",
                    metadata={
                        "generator_capacity_mw": generator_capacity_total,
                        "facility_load_mw": total_declared_load_mw,
                    },
                )
            )

def _resolve_transformer_inputs(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
) -> tuple[float | None, list[float], float | None, float | None, str]:
    engineering_transformers = _coerce_engineering_transformers(engineering_model)
    if engineering_transformers:
        transformer_count = float(len(engineering_transformers))
        ratings = _engineering_transformer_ratings(engineering_transformers)

        first_transformer = engineering_transformers[0]
        hv_voltage = _safe_float(
            _get_engineering_model_value(first_transformer, "primary_voltage_kv")
        )
        lv_voltage = _safe_float(
            _get_engineering_model_value(first_transformer, "secondary_voltage_kv")
        )

        return (
            transformer_count,
            ratings,
            hv_voltage,
            lv_voltage,
            "engineering_model.facility_electrical_system.transformers",
        )

    transformers = facility.get("transformers", {})
    if not isinstance(transformers, dict):
        transformers = {}

    transformer_count = _safe_float(transformers.get("count"))

    transformer_ratings = transformers.get("ratings_mva")
    if not isinstance(transformer_ratings, list):
        transformer_ratings = []

    ratings = [
        rating
        for rating in (_safe_float(value) for value in transformer_ratings)
        if rating is not None
    ]

    hv_voltage = _safe_float(transformers.get("hv_voltage_kv"))
    lv_voltage = _safe_float(transformers.get("lv_voltage_kv"))

    return (
        transformer_count,
        ratings,
        hv_voltage,
        lv_voltage,
        "facility.transformers",
    )


def _validate_voltage_topology(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
    warnings: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    poi_voltage, poi_field_path = _resolve_poi_voltage_kv(
        facility=facility,
        engineering_model=engineering_model,
    )

    transformer_count, _ratings, hv_voltage, lv_voltage, transformer_base_path = _resolve_transformer_inputs(
        facility=facility,
        engineering_model=engineering_model,
    )

    generators = facility.get("generators", {})
    generator_voltage = _safe_float(generators.get("voltage_kv"))

    hv_field_path = (
        "engineering_model.facility_electrical_system.transformers[0].primary_voltage_kv"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.hv_voltage_kv"
    )
    lv_field_path = (
        "engineering_model.facility_electrical_system.transformers[0].secondary_voltage_kv"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.lv_voltage_kv"
    )

    if transformer_count is not None and transformer_count > 0 and poi_voltage and hv_voltage and abs(poi_voltage - hv_voltage) > 1.0:
        warnings.append(
            _build_issue(
                code="POI_TRANSFORMER_VOLTAGE_MISMATCH",
                severity="warning",
                message="POI voltage does not match transformer high-side voltage.",
                field_path=hv_field_path,
                recommendation="Verify transformer HV rating matches POI voltage.",
                metadata={
                    "poi_voltage_kv": poi_voltage,
                    "transformer_hv_voltage_kv": hv_voltage,
                    "poi_field_path": poi_field_path,
                },
            )
        )

        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Transformer HV voltage mismatch with POI.",
                field_path=hv_field_path,
            )
        )

    if generator_voltage and lv_voltage and abs(generator_voltage - lv_voltage) > 1.0:
        warnings.append(
            _build_issue(
                code="GENERATOR_BUS_VOLTAGE_MISMATCH",
                severity="warning",
                message="Generator voltage does not match transformer LV side.",
                field_path="facility.generators.voltage_kv",
                recommendation="Verify generator interconnection voltage.",
                metadata={
                    "generator_voltage_kv": generator_voltage,
                    "transformer_lv_voltage_kv": lv_voltage,
                },
            )
        )

        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Generator voltage mismatch with LV bus voltage.",
                field_path="facility.generators.voltage_kv",
            )
        )


def _validate_additional_engineering_rules(
    *,
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
    total_declared_load_mw: float,
    warnings: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    transformer_count, numeric_transformer_ratings, hv_voltage, lv_voltage, transformer_base_path = _resolve_transformer_inputs(
        facility=facility,
        engineering_model=engineering_model,
    )

    poi_voltage, poi_field_path = _resolve_poi_voltage_kv(
        facility=facility,
        engineering_model=engineering_model,
    )

    hv_field_path = (
        "engineering_model.facility_electrical_system.transformers[0].primary_voltage_kv"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.hv_voltage_kv"
    )
    lv_field_path = (
        "engineering_model.facility_electrical_system.transformers[0].secondary_voltage_kv"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.lv_voltage_kv"
    )
    ratings_field_path = (
        "engineering_model.facility_electrical_system.transformers"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.ratings_mva"
    )
    count_field_path = (
        "engineering_model.facility_electrical_system.transformers"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.count"
    )
    transformer_group_field_path = (
        "engineering_model.facility_electrical_system.transformers"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers"
    )

    if transformer_count is not None and transformer_count > 0:
        if hv_voltage is None:
            warnings.append(
                _build_issue(
                    code="MISSING_TRANSFORMER_HV_VOLTAGE",
                    severity="warning",
                    message="Transformer high-side voltage is missing.",
                    field_path=hv_field_path,
                    recommendation="Capture transformer HV voltage for engineering model validation.",
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Transformer HV voltage requires engineering confirmation.",
                    field_path=hv_field_path,
                )
            )

        if lv_voltage is None:
            warnings.append(
                _build_issue(
                    code="MISSING_TRANSFORMER_LV_VOLTAGE",
                    severity="warning",
                    message="Transformer low-side voltage is missing.",
                    field_path=lv_field_path,
                    recommendation="Capture transformer LV voltage for engineering model validation.",
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Transformer LV voltage requires engineering confirmation.",
                    field_path=lv_field_path,
                )
            )

    if hv_voltage is not None and lv_voltage is not None and hv_voltage <= lv_voltage:
        warnings.append(
            _build_issue(
                code="TRANSFORMER_VOLTAGE_RATIO_INVALID",
                severity="warning",
                message="Transformer high-side voltage is not greater than low-side voltage.",
                field_path=hv_field_path,
                recommendation="Verify transformer HV/LV voltages and confirm step-up or step-down orientation.",
                metadata={
                    "transformer_hv_voltage_kv": hv_voltage,
                    "transformer_lv_voltage_kv": lv_voltage,
                },
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Transformer HV/LV voltage ratio requires engineering review.",
                field_path=hv_field_path,
                metadata={
                    "transformer_hv_voltage_kv": hv_voltage,
                    "transformer_lv_voltage_kv": lv_voltage,
                },
            )
        )

    if hv_voltage is not None and lv_voltage is not None and hv_voltage > lv_voltage:
        ratio = hv_voltage / lv_voltage
        if ratio < 1.5:
            warnings.append(
                _build_issue(
                    code="TRANSFORMER_RATIO_SUSPICIOUS",
                    severity="warning",
                    message="Transformer HV/LV ratio appears unusually small.",
                    field_path=hv_field_path,
                    recommendation="Confirm transformer voltage ratio.",
                    metadata={
                        "hv_voltage_kv": hv_voltage,
                        "lv_voltage_kv": lv_voltage,
                        "ratio": ratio,
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Transformer HV/LV ratio appears unusually small.",
                    field_path=hv_field_path,
                    metadata={
                        "hv_voltage_kv": hv_voltage,
                        "lv_voltage_kv": lv_voltage,
                        "ratio": ratio,
                    },
                )
            )

    typical_transmission_voltages = {69, 115, 138, 230, 345, 500}
    if poi_voltage is not None and poi_voltage not in typical_transmission_voltages:
        warnings.append(
            _build_issue(
                code="UNUSUAL_POI_VOLTAGE",
                severity="warning",
                message="POI voltage is not a typical transmission interconnection class.",
                field_path=poi_field_path,
                recommendation="Verify POI voltage classification.",
                metadata={"poi_voltage_kv": poi_voltage},
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="POI voltage is outside the typical transmission interconnection set.",
                field_path=poi_field_path,
                metadata={"poi_voltage_kv": poi_voltage},
            )
        )

    if total_declared_load_mw > 0 and (transformer_count is None or transformer_count <= 0):
        warnings.append(
            _build_issue(
                code="LOAD_WITHOUT_TRANSFORMER_COUNT",
                severity="warning",
                message="Declared facility load exists but transformer count is missing or invalid.",
                field_path=count_field_path,
                recommendation="Confirm transformer count supporting facility load.",
                metadata={"declared_load_mw": total_declared_load_mw},
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Facility load exists without captured transformer count.",
                field_path=count_field_path,
                metadata={"declared_load_mw": total_declared_load_mw},
            )
        )

    if total_declared_load_mw > 0 and transformer_count is not None and transformer_count > 0:
        missing_voltage_fields: list[str] = []
        if hv_voltage is None:
            missing_voltage_fields.append("hv_voltage_kv")
        if lv_voltage is None:
            missing_voltage_fields.append("lv_voltage_kv")

        if missing_voltage_fields:
            warnings.append(
                _build_issue(
                    code="LOAD_WITHOUT_TRANSFORMER_VOLTAGES",
                    severity="warning",
                    message="Declared facility load exists but transformer voltage fields are incomplete.",
                    field_path=transformer_group_field_path,
                    recommendation="Capture transformer HV and LV voltages for model-ready validation.",
                    metadata={
                        "declared_load_mw": total_declared_load_mw,
                        "missing_voltage_fields": missing_voltage_fields,
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Transformer voltage fields are incomplete for declared facility load.",
                    field_path=transformer_group_field_path,
                    metadata={
                        "declared_load_mw": total_declared_load_mw,
                        "missing_voltage_fields": missing_voltage_fields,
                    },
                )
            )

    if total_declared_load_mw > 0 and transformer_count is not None and transformer_count > 0 and not numeric_transformer_ratings:
        warnings.append(
            _build_issue(
                code="LOAD_WITHOUT_TRANSFORMER_RATINGS",
                severity="warning",
                message="Declared facility load exists but transformer ratings are missing.",
                field_path=ratings_field_path,
                recommendation="Capture transformer ratings for model-ready validation.",
                metadata={"declared_load_mw": total_declared_load_mw},
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Transformer ratings are missing for declared facility load.",
                field_path=ratings_field_path,
                metadata={"declared_load_mw": total_declared_load_mw},
            )
        )

    critical_missing_fields: list[str] = []
    if total_declared_load_mw > 0:
        if transformer_count is None or transformer_count <= 0:
            critical_missing_fields.append(count_field_path)
        if hv_voltage is None:
            critical_missing_fields.append(hv_field_path)
        if lv_voltage is None:
            critical_missing_fields.append(lv_field_path)
        if transformer_count is not None and transformer_count > 0 and not numeric_transformer_ratings:
            critical_missing_fields.append(ratings_field_path)

    if critical_missing_fields:
        review_flags.append(
            _build_review_flag(
                category="MODEL_INPUTS_INCOMPLETE",
                severity="warning",
                message="Critical transformer modeling inputs are incomplete for declared facility load.",
                field_path=transformer_group_field_path,
                metadata={
                    "declared_load_mw": total_declared_load_mw,
                    "missing_fields": critical_missing_fields,
                },
            )
        )

    ramp_rate = _safe_float(
        _get_engineering_model_value(
            engineering_model,
            "buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
        )
    )
    if ramp_rate is not None:
        if ramp_rate < 0:
            warnings.append(
                _build_issue(
                    code="NEGATIVE_RAMP_RATE",
                    severity="warning",
                    message="Normal ramp rate is negative.",
                    field_path="engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
                    recommendation="Confirm the normal ramp rate value.",
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Ramp rate requires engineering confirmation.",
                    field_path="engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
                )
            )
        elif total_declared_load_mw > 0 and ramp_rate > total_declared_load_mw:
            warnings.append(
                _build_issue(
                    code="RAMP_RATE_EXCEEDS_DECLARED_LOAD",
                    severity="warning",
                    message="Normal ramp rate exceeds total declared load.",
                    field_path="engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
                    recommendation="Confirm whether ramp rate and load schedule are modeled consistently.",
                    metadata={
                        "normal_ramp_rate_mw_per_min": ramp_rate,
                        "total_declared_load_mw": total_declared_load_mw,
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Ramp rate exceeds declared load and requires engineering review.",
                    field_path="engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
                    metadata={
                        "normal_ramp_rate_mw_per_min": ramp_rate,
                        "total_declared_load_mw": total_declared_load_mw,
                    },
                )
            )

    peak_demand_mw = _safe_float(
        _get_engineering_model_value(
            engineering_model,
            "load_system.peak_demand_mw",
        )
    )
    if peak_demand_mw is not None and peak_demand_mw <= 0:
        warnings.append(
            _build_issue(
                code="NONPOSITIVE_ENGINEERING_PEAK_DEMAND",
                severity="warning",
                message="Engineering model peak demand is non-positive.",
                field_path="engineering_model.load_system.peak_demand_mw",
                recommendation="Confirm engineering model peak demand.",
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Engineering model peak demand requires engineering confirmation.",
                field_path="engineering_model.load_system.peak_demand_mw",
            )
        )

    ups_systems = _get_engineering_model_value(
        engineering_model,
        "power_conversion_and_ups.ups_systems",
    )
    if isinstance(ups_systems, list) and ups_systems:
        allowed_topologies = {"N", "N+1", "2N", "2(N+1)", "N+N"}
        for index, ups_system in enumerate(ups_systems):
            if not isinstance(ups_system, dict):
                continue

            topology = _safe_str(_get_engineering_model_value(ups_system, "topology"))
            module_count = _safe_float(_get_engineering_model_value(ups_system, "module_count"))
            ups_base_path = f"engineering_model.power_conversion_and_ups.ups_systems[{index}]"

            if topology and topology.upper() not in allowed_topologies:
                warnings.append(
                    _build_issue(
                        code="UPS_TOPOLOGY_UNKNOWN",
                        severity="warning",
                        message=f"UPS topology '{topology}' is not recognized.",
                        field_path=f"{ups_base_path}.topology",
                        recommendation="Confirm UPS redundancy topology.",
                        metadata={"topology": topology},
                    )
                )
                review_flags.append(
                    _build_review_flag(
                        category="ENGINEERING_REVIEW_REQUIRED",
                        severity="warning",
                        message="UPS topology requires engineering confirmation.",
                        field_path=f"{ups_base_path}.topology",
                        metadata={"topology": topology},
                    )
                )

            if module_count is not None and module_count <= 0:
                warnings.append(
                    _build_issue(
                        code="UPS_MODULE_COUNT_INVALID",
                        severity="warning",
                        message="UPS module count is non-positive.",
                        field_path=f"{ups_base_path}.module_count",
                        recommendation="Confirm UPS module count.",
                        metadata={"module_count": module_count},
                    )
                )
                review_flags.append(
                    _build_review_flag(
                        category="ENGINEERING_REVIEW_REQUIRED",
                        severity="warning",
                        message="UPS module count requires engineering confirmation.",
                        field_path=f"{ups_base_path}.module_count",
                        metadata={"module_count": module_count},
                    )
                )




def _validate_zip_and_power_factor_consistency(
    *,
    canonical_state: dict[str, Any],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    power_factor = _safe_float(_get_accepted_field_value(canonical_state, "net_power_factor_at_poi"))
    if power_factor is not None:
        field_path = _accepted_field_path("net_power_factor_at_poi")
        if power_factor <= 0 or power_factor > 1.0:
            errors.append(
                _build_issue(
                    code="INVALID_NET_POWER_FACTOR_AT_POI",
                    severity="error",
                    message="Net power factor at POI must be greater than zero and no more than 1.0.",
                    field_path=field_path,
                    recommendation="Correct the resolved POI power factor before translation/export.",
                    metadata={"net_power_factor_at_poi": power_factor},
                )
            )
        elif power_factor < 0.8:
            warnings.append(
                _build_issue(
                    code="LOW_NET_POWER_FACTOR_AT_POI",
                    severity="warning",
                    message="Resolved net power factor at POI is unusually low for a planner-ready baseline.",
                    field_path=field_path,
                    recommendation="Confirm reactive support assumptions and POI power factor target.",
                    metadata={"net_power_factor_at_poi": power_factor},
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="POI power factor requires engineering review.",
                    field_path=field_path,
                    metadata={"net_power_factor_at_poi": power_factor},
                )
            )

    zip_fields = {
        "steady_state_zip_fraction_z": _safe_float(_get_accepted_field_value(canonical_state, "steady_state_zip_fraction_z")),
        "steady_state_zip_fraction_i": _safe_float(_get_accepted_field_value(canonical_state, "steady_state_zip_fraction_i")),
        "steady_state_zip_fraction_p": _safe_float(_get_accepted_field_value(canonical_state, "steady_state_zip_fraction_p")),
    }
    present_zip = {field_id: value for field_id, value in zip_fields.items() if value is not None}
    for field_id, value in present_zip.items():
        field_path = _accepted_field_path(field_id)
        if value < 0 or value > 1.0:
            errors.append(
                _build_issue(
                    code="INVALID_ZIP_FRACTION_VALUE",
                    severity="error",
                    message="Resolved ZIP fractions must stay between 0.0 and 1.0.",
                    field_path=field_path,
                    recommendation="Correct the ZIP fraction value or mark the field unresolved.",
                    metadata={"field_id": field_id, "value": value},
                )
            )
    if len(present_zip) == 3:
        zip_sum = sum(present_zip.values())
        if abs(zip_sum - 1.0) > 0.05:
            warnings.append(
                _build_issue(
                    code="ZIP_FRACTIONS_DO_NOT_SUM_TO_ONE",
                    severity="warning",
                    message="Resolved ZIP fractions do not sum to approximately 1.0.",
                    field_path=_accepted_field_path("steady_state_zip_fraction_p"),
                    recommendation="Confirm ZIP load composition before planner export.",
                    metadata={"zip_sum": zip_sum, **present_zip},
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="MODEL_INPUTS_INCOMPLETE",
                    severity="warning",
                    message="ZIP composition requires review before planner export.",
                    field_path=_accepted_field_path("steady_state_zip_fraction_p"),
                    metadata={"zip_sum": zip_sum, **present_zip},
                )
            )


def _validate_redundancy_and_rating_basis(
    *,
    canonical_state: dict[str, Any],
    engineering_model: dict[str, Any],
    warnings: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    redundancy = _safe_str(_get_accepted_field_value(canonical_state, "redundancy_architecture")).upper()
    ups_topology = _safe_str(_get_accepted_field_value(canonical_state, "ups_topology")).upper()
    if redundancy and ups_topology:
        mismatch = False
        if redundancy in {"2N", "2(N+1)"} and ups_topology not in {"2N", "2(N+1)", "N+N"}:
            mismatch = True
        elif redundancy == "N+1" and ups_topology in {"N", "NONE"}:
            mismatch = True
        if mismatch:
            warnings.append(
                _build_issue(
                    code="UPS_TOPOLOGY_REDUNDANCY_MISMATCH",
                    severity="warning",
                    message="Resolved UPS topology is inconsistent with resolved redundancy architecture.",
                    field_path=_accepted_field_path("ups_topology"),
                    recommendation="Confirm facility redundancy architecture and UPS topology alignment.",
                    metadata={"redundancy_architecture": redundancy, "ups_topology": ups_topology},
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="UPS topology and redundancy architecture require engineering review.",
                    field_path=_accepted_field_path("ups_topology"),
                    metadata={"redundancy_architecture": redundancy, "ups_topology": ups_topology},
                )
            )

    generator_basis = _safe_str(_get_accepted_field_value(canonical_state, "generator_prime_or_standby_rating_basis")).lower()
    if generator_basis and generator_basis not in {"prime", "standby", "none", "not_applicable"}:
        warnings.append(
            _build_issue(
                code="GENERATOR_RATING_BASIS_UNRECOGNIZED",
                severity="warning",
                message="Resolved generator rating basis is not a recognized planner-facing value.",
                field_path=_accepted_field_path("generator_prime_or_standby_rating_basis"),
                recommendation="Normalize generator rating basis to prime or standby.",
                metadata={"generator_prime_or_standby_rating_basis": generator_basis},
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Generator rating basis requires engineering confirmation.",
                field_path=_accepted_field_path("generator_prime_or_standby_rating_basis"),
                metadata={"generator_prime_or_standby_rating_basis": generator_basis},
            )
        )

    generator_units = _get_engineering_model_value(engineering_model, "backup_power_system.generator_units")
    if generator_basis == "standby" and isinstance(generator_units, list) and generator_units:
        for index, unit in enumerate(generator_units):
            if not isinstance(unit, dict):
                continue
            rating_mw = _safe_float(_get_engineering_model_value(unit, "rating_mw"))
            standby_rating_mw = _safe_float(_get_engineering_model_value(unit, "standby_rating_mw"))
            if rating_mw is not None and standby_rating_mw is not None and standby_rating_mw < rating_mw:
                path = f"engineering_model.backup_power_system.generator_units[{index}]"
                warnings.append(
                    _build_issue(
                        code="GENERATOR_STANDBY_RATING_BELOW_PRIME",
                        severity="warning",
                        message="Generator standby rating is lower than prime/base rating while standby basis is selected.",
                        field_path=path,
                        recommendation="Confirm generator prime vs standby rating mapping.",
                        metadata={"rating_mw": rating_mw, "standby_rating_mw": standby_rating_mw},
                    )
                )
                review_flags.append(
                    _build_review_flag(
                        category="ENGINEERING_REVIEW_REQUIRED",
                        severity="warning",
                        message="Generator prime/standby rating mapping requires engineering review.",
                        field_path=path,
                        metadata={"rating_mw": rating_mw, "standby_rating_mw": standby_rating_mw},
                    )
                )


def _resolve_peak_demand_for_consistency(
    *,
    canonical_state: dict[str, Any],
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
    total_declared_load_mw: float,
) -> tuple[float | None, str]:
    accepted_peak = _safe_float(_get_accepted_field_value(canonical_state, "accepted_peak_demand_mw"))
    if accepted_peak is not None:
        return accepted_peak, _accepted_field_path("accepted_peak_demand_mw")

    peak_demand = _safe_float(_get_accepted_field_value(canonical_state, "peak_demand_mw"))
    if peak_demand is not None:
        return peak_demand, _accepted_field_path("peak_demand_mw")

    engineering_peak = _safe_float(
        _get_engineering_model_value(
            engineering_model,
            "load_system.peak_demand_mw",
        )
    )
    if engineering_peak is not None:
        return engineering_peak, "engineering_model.load_system.peak_demand_mw"

    if total_declared_load_mw > 0:
        return total_declared_load_mw, "facility.load_schedule"
    return None, ""


def _validate_telemetry_and_protection_dependencies(
    *,
    canonical_state: dict[str, Any],
    warnings: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    telemetry_fields = {
        "mw_mvar_telemetry_present": _normalize_truthy_bool(_get_accepted_field_value(canonical_state, "mw_mvar_telemetry_present")),
        "voltage_frequency_telemetry_present": _normalize_truthy_bool(_get_accepted_field_value(canonical_state, "voltage_frequency_telemetry_present")),
        "breaker_status_telemetry_present": _normalize_truthy_bool(_get_accepted_field_value(canonical_state, "breaker_status_telemetry_present")),
        "telemetry_points_list_present": _normalize_truthy_bool(_get_accepted_field_value(canonical_state, "telemetry_points_list_present")),
    }
    protection_summary = _safe_str(_get_accepted_field_value(canonical_state, "protection_scheme_summary"))
    telemetry_present = any(value is True for key, value in telemetry_fields.items() if key != "telemetry_points_list_present")
    telemetry_points_present = telemetry_fields["telemetry_points_list_present"]

    if telemetry_present and telemetry_points_present is False:
        warnings.append(
            _build_issue(
                code="TELEMETRY_PRESENT_WITHOUT_POINTS_LIST",
                severity="warning",
                message="Telemetry is marked present but the telemetry points list is not confirmed present.",
                field_path=_accepted_field_path("telemetry_points_list_present"),
                recommendation="Provide telemetry point list support before planner export.",
                metadata=telemetry_fields,
            )
        )
        review_flags.append(
            _build_review_flag(
                category="MODEL_INPUTS_INCOMPLETE",
                severity="warning",
                message="Telemetry evidence is incomplete for planner-facing operations review.",
                field_path=_accepted_field_path("telemetry_points_list_present"),
                metadata=telemetry_fields,
            )
        )

    if telemetry_present and not protection_summary:
        warnings.append(
            _build_issue(
                code="TELEMETRY_WITHOUT_PROTECTION_SUMMARY",
                severity="warning",
                message="Telemetry/supporting SCADA fields are present but protection scheme summary is unresolved.",
                field_path=_accepted_field_path("protection_scheme_summary"),
                recommendation="Capture a protection scheme summary for planner review and telemetry context.",
                metadata=telemetry_fields,
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Telemetry and protection context require engineering review.",
                field_path=_accepted_field_path("protection_scheme_summary"),
                metadata=telemetry_fields,
            )
        )


def _validate_planner_cross_field_consistency(
    *,
    canonical_state: dict[str, Any],
    facility: dict[str, Any],
    engineering_model: dict[str, Any],
    total_declared_load_mw: float,
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    review_flags: list[dict[str, Any]],
) -> None:
    peak_demand_mw, peak_demand_path = _resolve_peak_demand_for_consistency(
        canonical_state=canonical_state,
        facility=facility,
        engineering_model=engineering_model,
        total_declared_load_mw=total_declared_load_mw,
    )

    generator_unit_count = _safe_float(_get_accepted_field_value(canonical_state, "generator_unit_count"))
    generator_kw_per_unit = _safe_float(_get_accepted_field_value(canonical_state, "generator_rated_kw_per_unit"))
    redundancy = _safe_str(_get_accepted_field_value(canonical_state, "redundancy_architecture")).upper()
    if generator_unit_count is not None and generator_kw_per_unit is not None:
        total_generator_capacity_mw = (generator_unit_count * generator_kw_per_unit) / 1000.0
        if peak_demand_mw is not None and peak_demand_mw > 0 and total_generator_capacity_mw + 1e-6 < peak_demand_mw:
            warnings.append(
                _build_issue(
                    code="GENERATOR_CAPACITY_BELOW_PEAK_DEMAND",
                    severity="warning",
                    message="Resolved generator capacity is below the resolved peak demand baseline.",
                    field_path=_accepted_field_path("generator_rated_kw_per_unit"),
                    recommendation="Confirm generator sizing, unit count, and whether non-generator support is assumed.",
                    metadata={
                        "generator_unit_count": generator_unit_count,
                        "generator_rated_kw_per_unit": generator_kw_per_unit,
                        "total_generator_capacity_mw": total_generator_capacity_mw,
                        "peak_demand_mw": peak_demand_mw,
                        "peak_demand_field_path": peak_demand_path,
                        "related_field_ids": ["generator_unit_count", "generator_rated_kw_per_unit", "peak_demand_mw"],
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Generator capacity and peak demand require engineering review.",
                    field_path=_accepted_field_path("generator_rated_kw_per_unit"),
                    metadata={
                        "generator_unit_count": generator_unit_count,
                        "generator_rated_kw_per_unit": generator_kw_per_unit,
                        "total_generator_capacity_mw": total_generator_capacity_mw,
                        "peak_demand_mw": peak_demand_mw,
                        "related_field_ids": ["generator_unit_count", "generator_rated_kw_per_unit", "peak_demand_mw"],
                    },
                )
            )

    if redundancy in {"N+1", "2N", "2(N+1)", "N+N"} and generator_unit_count is not None and generator_unit_count < 2:
        warnings.append(
            _build_issue(
                code="REDUNDANCY_ARCHITECTURE_UNIT_COUNT_TENSION",
                severity="warning",
                message="Resolved redundancy architecture implies multi-unit support, but generator unit count is less than two.",
                field_path=_accepted_field_path("redundancy_architecture"),
                recommendation="Confirm whether the redundancy architecture or generator unit count is incomplete.",
                metadata={
                    "redundancy_architecture": redundancy,
                    "generator_unit_count": generator_unit_count,
                    "related_field_ids": ["redundancy_architecture", "generator_unit_count"],
                },
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Redundancy architecture and unit count require engineering review.",
                field_path=_accepted_field_path("redundancy_architecture"),
                metadata={
                    "redundancy_architecture": redundancy,
                    "generator_unit_count": generator_unit_count,
                    "related_field_ids": ["redundancy_architecture", "generator_unit_count"],
                },
            )
        )

    main_bus_kv = _safe_float(_get_accepted_field_value(canonical_state, "main_bus_nominal_voltage_kv"))
    transformer_lv_kv = _safe_float(_get_accepted_field_value(canonical_state, "interconnection_transformer_lv_kv"))
    generator_terminal_kv = _safe_float(_get_accepted_field_value(canonical_state, "generator_terminal_voltage_kv"))

    if main_bus_kv is not None and transformer_lv_kv is not None and main_bus_kv > 0:
        relative_delta = abs(main_bus_kv - transformer_lv_kv) / max(main_bus_kv, transformer_lv_kv)
        if relative_delta > 0.15:
            warnings.append(
                _build_issue(
                    code="MAIN_BUS_TRANSFORMER_LV_MISMATCH",
                    severity="warning",
                    message="Resolved main bus nominal voltage is inconsistent with interconnection transformer LV voltage.",
                    field_path=_accepted_field_path("main_bus_nominal_voltage_kv"),
                    recommendation="Confirm the main bus voltage and transformer LV side alignment.",
                    metadata={
                        "main_bus_nominal_voltage_kv": main_bus_kv,
                        "interconnection_transformer_lv_kv": transformer_lv_kv,
                        "related_field_ids": ["main_bus_nominal_voltage_kv", "interconnection_transformer_lv_kv"],
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Main bus voltage and transformer LV voltage require engineering review.",
                    field_path=_accepted_field_path("main_bus_nominal_voltage_kv"),
                    metadata={
                        "main_bus_nominal_voltage_kv": main_bus_kv,
                        "interconnection_transformer_lv_kv": transformer_lv_kv,
                        "related_field_ids": ["main_bus_nominal_voltage_kv", "interconnection_transformer_lv_kv"],
                    },
                )
            )

    if generator_terminal_kv is not None and main_bus_kv is not None and main_bus_kv > 0:
        relative_delta = abs(generator_terminal_kv - main_bus_kv) / max(generator_terminal_kv, main_bus_kv)
        if relative_delta > 0.15:
            warnings.append(
                _build_issue(
                    code="GENERATOR_TERMINAL_MAIN_BUS_MISMATCH",
                    severity="warning",
                    message="Resolved generator terminal voltage is inconsistent with main bus nominal voltage.",
                    field_path=_accepted_field_path("generator_terminal_voltage_kv"),
                    recommendation="Confirm generator terminal voltage and associated bus voltage alignment.",
                    metadata={
                        "generator_terminal_voltage_kv": generator_terminal_kv,
                        "main_bus_nominal_voltage_kv": main_bus_kv,
                        "related_field_ids": ["generator_terminal_voltage_kv", "main_bus_nominal_voltage_kv"],
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Generator terminal voltage and main bus voltage require engineering review.",
                    field_path=_accepted_field_path("generator_terminal_voltage_kv"),
                    metadata={
                        "generator_terminal_voltage_kv": generator_terminal_kv,
                        "main_bus_nominal_voltage_kv": main_bus_kv,
                        "related_field_ids": ["generator_terminal_voltage_kv", "main_bus_nominal_voltage_kv"],
                    },
                )
            )

    cooling_share = _safe_float(_get_accepted_field_value(canonical_state, "cooling_load_share_percent_of_total"))
    cooling_summary = _safe_str(_get_accepted_field_value(canonical_state, "cooling_architecture_summary"))
    ramp_summary = _safe_str(_get_accepted_field_value(canonical_state, "load_ramp_profile_summary"))
    if not ramp_summary:
        ramp_summary = _safe_str(_get_accepted_field_value(canonical_state, "maximum_daily_weekly_monthly_ramp_summary"))

    if cooling_share is not None:
        if cooling_share < 0 or cooling_share > 100:
            errors.append(
                _build_issue(
                    code="INVALID_COOLING_LOAD_SHARE_PERCENT",
                    severity="error",
                    message="Cooling load share percent must stay between 0 and 100.",
                    field_path=_accepted_field_path("cooling_load_share_percent_of_total"),
                    recommendation="Correct the cooling load share percentage before planner export.",
                    metadata={
                        "cooling_load_share_percent_of_total": cooling_share,
                        "related_field_ids": ["cooling_load_share_percent_of_total"],
                    },
                )
            )
        elif cooling_share >= 40 and not cooling_summary:
            warnings.append(
                _build_issue(
                    code="HIGH_COOLING_SHARE_WITHOUT_ARCHITECTURE_SUMMARY",
                    severity="warning",
                    message="Cooling load share is materially high but cooling architecture summary is unresolved.",
                    field_path=_accepted_field_path("cooling_architecture_summary"),
                    recommendation="Capture cooling architecture details supporting the modeled cooling load share.",
                    metadata={
                        "cooling_load_share_percent_of_total": cooling_share,
                        "related_field_ids": ["cooling_load_share_percent_of_total", "cooling_architecture_summary"],
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="MODEL_INPUTS_INCOMPLETE",
                    severity="warning",
                    message="Cooling architecture support is incomplete for the resolved cooling load share.",
                    field_path=_accepted_field_path("cooling_architecture_summary"),
                    metadata={
                        "cooling_load_share_percent_of_total": cooling_share,
                        "related_field_ids": ["cooling_load_share_percent_of_total", "cooling_architecture_summary"],
                    },
                )
            )

    if peak_demand_mw is not None and peak_demand_mw >= 100 and not ramp_summary:
        warnings.append(
            _build_issue(
                code="LARGE_LOAD_WITHOUT_RAMP_SUMMARY",
                severity="warning",
                message="Resolved large-load baseline is missing a planner-facing ramp summary.",
                field_path=_accepted_field_path("load_ramp_profile_summary"),
                recommendation="Provide a ramp profile summary or maximum ramp summary for planner review.",
                metadata={
                    "peak_demand_mw": peak_demand_mw,
                    "peak_demand_field_path": peak_demand_path,
                    "related_field_ids": ["peak_demand_mw", "load_ramp_profile_summary", "maximum_daily_weekly_monthly_ramp_summary"],
                },
            )
        )
        review_flags.append(
            _build_review_flag(
                category="MODEL_INPUTS_INCOMPLETE",
                severity="warning",
                message="Large-load ramp information is incomplete for planner export.",
                field_path=_accepted_field_path("load_ramp_profile_summary"),
                metadata={
                    "peak_demand_mw": peak_demand_mw,
                    "peak_demand_field_path": peak_demand_path,
                    "related_field_ids": ["peak_demand_mw", "load_ramp_profile_summary", "maximum_daily_weekly_monthly_ramp_summary"],
                },
            )
        )

def run_engineering_validation(
    *,
    canonical_state: dict[str, Any],
) -> dict[str, Any]:
    normalized_input = canonical_state.get("normalized_input", {})
    if not isinstance(normalized_input, dict):
        normalized_input = {}

    engineering_model = canonical_state.get("engineering_model", {})
    if not isinstance(engineering_model, dict):
        engineering_model = {}

    facility = normalized_input.get("facility", {})
    if not isinstance(facility, dict):
        facility = {}

    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    review_flags: list[dict[str, Any]] = []

    frequency_hz, frequency_field_path = _resolve_frequency_hz(
        facility=facility,
        engineering_model=engineering_model,
    )
    if frequency_hz is None:
        warnings.append(
            _build_issue(
                code="MISSING_FREQUENCY",
                severity="warning",
                message="Facility frequency is missing.",
                field_path=frequency_field_path,
                recommendation="Populate facility frequency for interconnection modeling.",
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Facility frequency requires engineering confirmation.",
                field_path=frequency_field_path,
            )
        )
    elif frequency_hz not in {50.0, 60.0}:
        errors.append(
            _build_issue(
                code="INVALID_FREQUENCY",
                severity="error",
                message=f"Facility frequency '{frequency_hz}' is outside expected engineering values.",
                field_path=frequency_field_path,
                recommendation="Correct the facility frequency to a valid operating frequency.",
            )
        )

    poi_voltage_kv, poi_field_path = _resolve_poi_voltage_kv(
        facility=facility,
        engineering_model=engineering_model,
    )
    if poi_voltage_kv is None:
        warnings.append(
            _build_issue(
                code="MISSING_POI_VOLTAGE",
                severity="warning",
                message="POI voltage is missing.",
                field_path=poi_field_path,
                recommendation="Populate POI voltage for export and model translation.",
            )
        )
    elif poi_voltage_kv <= 0:
        errors.append(
            _build_issue(
                code="NONPOSITIVE_POI_VOLTAGE",
                severity="error",
                message="POI voltage must be greater than zero.",
                field_path=poi_field_path,
                recommendation="Provide a valid positive POI voltage.",
            )
        )

    phase_loads = _resolve_phase_loads(
        facility=facility,
        engineering_model=engineering_model,
    )

    for _phase_label, phase_value, field_path in phase_loads:
        if phase_value is not None and phase_value < 0:
            errors.append(
                _build_issue(
                    code="NEGATIVE_LOAD_VALUE",
                    severity="error",
                    message=f"{_phase_label} MW load cannot be negative.",
                    field_path=field_path,
                    recommendation="Correct the phase load value.",
                )
            )

    total_declared_load_mw = _sum_numeric([value for _label, value, _path in phase_loads])

    _validate_voltage_topology(
        facility=facility,
        engineering_model=engineering_model,
        warnings=warnings,
        review_flags=review_flags,
    )

    _validate_additional_engineering_rules(
        facility=facility,
        engineering_model=engineering_model,
        total_declared_load_mw=total_declared_load_mw,
        warnings=warnings,
        review_flags=review_flags,
    )
    _validate_generator_capacity_against_load(
        facility=facility,
        engineering_model=engineering_model,
        total_declared_load_mw=total_declared_load_mw,
        warnings=warnings,
        review_flags=review_flags,
    )
    generator_present, generator_count, generator_count_field_path = _resolve_generator_present_and_count(
        facility=facility,
        engineering_model=engineering_model,
    )
    if generator_present and (generator_count is None or generator_count <= 0):
        warnings.append(
            _build_issue(
                code="GENERATOR_PRESENT_WITHOUT_COUNT",
                severity="warning",
                message="Generators are marked present but generator count is missing or invalid.",
                field_path=generator_count_field_path,
                recommendation="Confirm generator count.",
            )
        )
        review_flags.append(
            _build_review_flag(
                category="ENGINEERING_REVIEW_REQUIRED",
                severity="warning",
                message="Generator count requires engineering confirmation.",
                field_path=generator_count_field_path,
            )
        )

    transformer_count, numeric_transformer_ratings, _hv_voltage, _lv_voltage, transformer_base_path = _resolve_transformer_inputs(
        facility=facility,
        engineering_model=engineering_model,
    )

    ratings_field_path = (
        "engineering_model.facility_electrical_system.transformers"
        if transformer_base_path.startswith("engineering_model")
        else "facility.transformers.ratings_mva"
    )

    if transformer_count is not None and transformer_count > 0 and not numeric_transformer_ratings:
        warnings.append(
            _build_issue(
                code="TRANSFORMERS_WITHOUT_RATINGS",
                severity="warning",
                message="Transformer count exists but no transformer ratings were captured.",
                field_path=ratings_field_path,
                recommendation="Capture transformer ratings for engineering validation.",
            )
        )

    if numeric_transformer_ratings and any(rating <= 0 for rating in numeric_transformer_ratings):
        errors.append(
            _build_issue(
                code="INVALID_TRANSFORMER_RATING",
                severity="error",
                message="One or more transformer ratings are non-positive.",
                field_path=ratings_field_path,
                recommendation="Correct transformer ratings to positive MVA values.",
            )
        )

    total_transformer_capacity_mva = _sum_numeric(numeric_transformer_ratings)
    if total_declared_load_mw > 0 and total_transformer_capacity_mva > 0:
        if total_declared_load_mw > total_transformer_capacity_mva:
            warnings.append(
                _build_issue(
                    code="LOAD_EXCEEDS_TRANSFORMER_CAPACITY",
                    severity="warning",
                    message=(
                        f"Declared facility load of {total_declared_load_mw:.2f} MW exceeds "
                        f"captured transformer capacity of {total_transformer_capacity_mva:.2f} MVA."
                    ),
                    field_path=ratings_field_path,
                    recommendation=(
                        "Confirm transformer sizing, load schedule, and whether additional transformer "
                        "capacity exists in supporting documents."
                    ),
                    metadata={
                        "total_declared_load_mw": total_declared_load_mw,
                        "total_transformer_capacity_mva": total_transformer_capacity_mva,
                    },
                )
            )
            review_flags.append(
                _build_review_flag(
                    category="ENGINEERING_REVIEW_REQUIRED",
                    severity="warning",
                    message="Declared load exceeds captured transformer capacity and requires engineering review.",
                    field_path=ratings_field_path,
                    metadata={
                        "total_declared_load_mw": total_declared_load_mw,
                        "total_transformer_capacity_mva": total_transformer_capacity_mva,
                    },
                )
            )

    _validate_zip_and_power_factor_consistency(
        canonical_state=canonical_state,
        warnings=warnings,
        errors=errors,
        review_flags=review_flags,
    )
    _validate_redundancy_and_rating_basis(
        canonical_state=canonical_state,
        engineering_model=engineering_model,
        warnings=warnings,
        review_flags=review_flags,
    )
    _validate_telemetry_and_protection_dependencies(
        canonical_state=canonical_state,
        warnings=warnings,
        review_flags=review_flags,
    )
    _validate_planner_cross_field_consistency(
        canonical_state=canonical_state,
        facility=facility,
        engineering_model=engineering_model,
        total_declared_load_mw=total_declared_load_mw,
        warnings=warnings,
        errors=errors,
        review_flags=review_flags,
    )

    if not errors:
        info.append(
            _build_issue(
                code="ENGINEERING_VALIDATION_EXECUTED",
                severity="info",
                message="Engineering validation checks executed.",
                recommendation="Review warnings and review flags if present.",
            )
        )

    status = "PASSED"
    if errors:
        status = "FAILED"
    elif warnings:
        status = "REVIEW_REQUIRED"

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "review_flags": review_flags,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "info_count": len(info),
            "review_flag_count": len(review_flags),
            "is_blocked": bool(errors),
        },
    }


def run_service(
    *,
    context: Any,
    canonical_state: dict[str, Any],
) -> dict[str, Any]:
    run_id = _safe_str(getattr(context, "run_id", None))
    if not run_id:
        raise ValueError("context.run_id must be a non-empty string.")

    payload = run_engineering_validation(canonical_state=canonical_state)
    payload["run_id"] = run_id
    return payload