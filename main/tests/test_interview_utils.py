from __future__ import annotations

from services.interview_service.question_catalog import get_question_by_field_path, get_question_by_id
from services.interview_service.utils import parse_answer_value


def test_interview_catalog_preserves_legacy_question_ids() -> None:
    question = get_question_by_id("FACILITY_POI_VOLTAGE_KV")
    assert question is not None
    assert question.field_path == "facility.poi_voltage_kv"
    assert question.answer_type == "number"


def test_interview_catalog_loads_registry_backed_question_catalog() -> None:
    question = get_question_by_id("PEAK_DEMAND_MW")
    assert question is not None
    assert question.field_path == "facility.load_schedule.phase_1_mw"
    assert question.prompt

    same_question = get_question_by_field_path("facility.load_schedule.phase_1_mw")
    assert same_question is not None
    assert same_question.question_id == "PEAK_DEMAND_MW"


def test_interview_utils_parses_numeric_and_enum_answers() -> None:
    mw_question = get_question_by_id("PEAK_DEMAND_MW")
    assert mw_question is not None
    assert parse_answer_value(mw_question, "125 MW") == 125.0

    ups_question = get_question_by_field_path("facility.ups.topology")
    assert ups_question is not None
    assert parse_answer_value(ups_question, "double conversion") == "DOUBLE_CONVERSION"
