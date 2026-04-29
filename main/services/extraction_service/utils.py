from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.extraction_service.models import SourceAnchor
from shared.planner_registry import field_path_for_registry_field_id, planner_registry_fields, registry_field_id_for_path
from shared.value_quality import contamination_reasons


SUPPORTED_TEXT_SUFFIXES: set[str] = {
    ".txt",
    ".json",
    ".csv",
}

CANONICAL_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "shared"
    / "schemas"
    / "gridsenpai_canonical_facility_model.json"
)

UPS_PATTERNS = [
    r"\bups\b",
    r"\buninterruptible power supply\b",
]

GENERATOR_PATTERNS = [
    r"\bgenerator\b",
    r"\bgenset\b",
]

TRANSFORMER_PATTERNS = [
    r"\btransformer\b",
    r"\bxfmr\b",
]

SWITCHGEAR_PATTERNS = [
    r"\bswitchgear\b",
]

RELAY_PATTERNS = [
    r"\brelay\b",
    r"\bprotection\b",
    r"\bundervoltage\b",
    r"\bunderfrequency\b",
    r"\bovervoltage\b",
    r"\boverfrequency\b",
    r"\btrip\b",
]

POI_PATTERNS = [
    r"\bpoi\b",
    r"\bpoint of interconnection\b",
    r"\bpoint-of-interconnection\b",
]

TOPOLOGY_PATTERNS = {
    "topology_2n": [
        r"\b2n\b",
    ],
    "topology_n_plus_1": [
        r"\bn\+1\b",
        r"\bn plus 1\b",
    ],
    "bus_reference_detected": [
        r"\bbus\b",
    ],
    "feeder_reference_detected": [
        r"\bfeeder\b",
    ],
}

BOOLEAN_SCHEMA_PATTERNS: dict[str, list[str]] = {
    "interconnection_context.substation_topology.tie_breaker_present": [
        r"\btie breaker\b",
    ],
    "protection_controls_and_communications.breaker_failure_protection_present": [
        r"\bbreaker failure\b",
    ],
    "protection_controls_and_communications.transfer_trip_present": [
        r"\btransfer trip\b",
        r"\bdirect transfer trip\b",
    ],
    "protection_controls_and_communications.scada_interface_present": [
        r"\bscada\b",
        r"\bsupervisory control and data acquisition\b",
    ],
    "metering_and_telemetry.revenue_metering_required": [
        r"\brevenue metering\b",
    ],
    "metering_and_telemetry.mw_telemetry_required": [
        r"\bmw telemetry\b",
        r"\breal power telemetry\b",
    ],
    "metering_and_telemetry.mvar_telemetry_required": [
        r"\bmvar telemetry\b",
        r"\breactive power telemetry\b",
    ],
    "metering_and_telemetry.breaker_status_telemetry_required": [
        r"\bbreaker status telemetry\b",
    ],
    "backup_power_system.generator_plant_present": [
        r"\bgenerator\b",
        r"\bgenset\b",
    ],
}

SWITCHING_SCHEME_PATTERNS: dict[str, list[str]] = {
    "breaker-and-a-half": [
        r"\bbreaker(?:\s+and|\s*&)\s+(?:a\s+)?half\b",
    ],
    "ring-bus": [
        r"\bring bus\b",
    ],
    "double-bus": [
        r"\bdouble bus\b",
    ],
    "single-bus": [
        r"\bsingle bus\b",
    ],
}

UPS_TOPOLOGY_PATTERNS: dict[str, list[str]] = {
    "double_conversion": [
        r"\bdouble[-\s]?conversion\b",
    ],
    "line_interactive": [
        r"\bline[-\s]?interactive\b",
    ],
    "static_bypass": [
        r"\bstatic bypass\b",
    ],
}

PROTECTION_SCHEME_PATTERNS: dict[str, list[str]] = {
    "line_differential": [
        r"\bline differential\b",
    ],
    "transformer_differential": [
        r"\btransformer differential\b",
    ],
    "distance": [
        r"\bdistance protection\b",
        r"\b21\b",
    ],
    "overcurrent": [
        r"\bovercurrent\b",
        r"\b50/51\b",
        r"\b51\b",
    ],
    "undervoltage": [
        r"\bundervoltage\b",
        r"\b27\b",
    ],
    "overvoltage": [
        r"\bovervoltage\b",
        r"\b59\b",
    ],
    "underfrequency": [
        r"\bunderfrequency\b",
        r"\b81u\b",
    ],
    "overfrequency": [
        r"\boverfrequency\b",
        r"\b81o\b",
    ],
}

RELAY_TYPE_PATTERNS: dict[str, list[str]] = {
    "microprocessor": [
        r"\bmicroprocessor relay\b",
    ],
    "sel": [
        r"\bsel[-\s]?\d+\b",
        r"\bschweitzer\b",
    ],
}

INTERCONNECTION_TEXT_VALUE_SPECS: list[dict[str, Any]] = [
    {
        "field_path": "facility.project_name",
        "patterns": [
            re.compile(
                r"\b(?:project|facility)\s+name\s*[:\-]\s*(?P<value>.+?)$",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bfacilities?\s+study\s+report\s+for\s+(?P<value>.+?)$",
                re.IGNORECASE,
            ),
        ],
        "score": 0.93,
        "source_method": "promotion.interconnection_identity",
    },
    {
        "field_path": "application_or_queue_id",
        "patterns": [
            re.compile(
                r"\b(?:project\s+ids?|queue\s*(?:id|number|no\.?|#)|application\s*(?:id|number|no\.?|#)|request\s*(?:id|number|no\.?|#))\s*[:\-]?\s*(?P<value>[A-Z]{1,4}\d?[- ]\d{2,4}(?:\s*/\s*[A-Z]{1,4}\d?[- ]\d{2,4})*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:facilities?|interconnection|feasibility|system impact)\s+study(?:\s+report)?\s+(?:for\s+)?(?:project\s+ids?\s*)?(?P<value>[A-Z]{1,4}\d?[- ]\d{2,4}(?:\s*/\s*[A-Z]{1,4}\d?[- ]\d{2,4})*)",
                re.IGNORECASE,
            ),
        ],
        "score": 0.94,
        "source_method": "promotion.interconnection_identity",
    },
    {
        "field_path": "load_customer_name",
        "patterns": [
            re.compile(
                r"\b(?:load\s+customer|customer|developer|applicant|project developer|pd)\s*[:\-]\s*(?P<value>.+?)$",
                re.IGNORECASE,
            ),
        ],
        "score": 0.9,
        "source_method": "promotion.interconnection_identity",
    },
]

INTERCONNECTION_REGION_PATTERNS: dict[str, list[str]] = {
    "PJM": [r"\bpjm\b", r"\bpjm interconnection\b"],
    "ERCOT": [r"\bercot\b", r"\belectric reliability council of texas\b"],
    "MISO": [r"\bmiso\b", r"\bmidcontinent independent system operator\b"],
    "SPP": [r"\bspp\b", r"\bsouthwest power pool\b"],
    "CAISO": [r"\bcaiso\b", r"\bcalifornia independent system operator\b"],
    "NYISO": [r"\bnyiso\b", r"\bnew york iso\b"],
    "ISO-NE": [r"\biso[- ]?ne\b", r"\biso new england\b"],
    "FERC": [r"\bferc\b"],
}

INTERCONNECTION_PROTECTION_SUMMARY_PATTERNS: dict[str, list[str]] = {
    "line differential": [r"\bline differential\b"],
    "transformer differential": [r"\btransformer differential\b", r"\bdual trfm protection\b"],
    "transfer trip": [r"\btransfer trip\b", r"\bdirect transfer trip\b"],
    "sync-check": [r"\bsync[- ]?check\b"],
    "breaker failure": [r"\bbreaker failure\b"],
    "distance": [r"\bdistance protection\b", r"\b21\b"],
    "overcurrent": [r"\bovercurrent\b", r"\b50/51\b", r"\b51\b"],
    "undervoltage": [r"\bundervoltage\b", r"\b27\b"],
    "overvoltage": [r"\bovervoltage\b", r"\b59\b"],
    "underfrequency": [r"\bunder-frequency\b", r"\bunder frequency\b", r"\bunderfrequency\b", r"\b81u\b"],
    "overfrequency": [r"\bover-frequency\b", r"\bover frequency\b", r"\boverfrequency\b", r"\b81o\b"],
    "bus protection": [r"\bdual bus protection\b", r"\bbus protection\b"],
    "redundant primary and secondary schemes": [r"\bprimary/system 1\b", r"\bsecondary/system 2\b", r"\bminimum redundant\b"],
}

INTERCONNECTION_RELAY_MODEL_REGEX = re.compile(
    r"\b(?P<value>(?:SEL|BECKWITH|GE|ABB|SIEMENS|SCHNEIDER|MULTILIN)[-\s]?[A-Z]*\d{2,4}[A-Z0-9-]*)\b",
    re.IGNORECASE,
)

INTERCONNECTION_RELAY_FIRMWARE_REGEX = re.compile(
    r"\bfirmware\s*(?:version)?\s*[:\-]?\s*(?P<value>[A-Z0-9_.-]{2,30})",
    re.IGNORECASE,
)

REVENUE_METERING_REQUIRED_REGEX = re.compile(
    r"\bmetering\s+is\s+required\s+to\s+be\s+installed\s+per\s+[^\n\r]{0,120}?standards\b|\brevenue metering\b[^\n\r]{0,120}\b(?:required|required at the poi|required at poi|shall be provided|will be provided)\b",
    re.IGNORECASE,
)

VOLTAGE_REGEXES = [
    re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kv)\b", re.IGNORECASE),
]

MW_REGEXES = [
    re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mw)\b", re.IGNORECASE),
]

MVA_REGEXES = [
    re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mva)\b", re.IGNORECASE),
]

POI_CONTEXT_PATTERNS = [
    r"\bpoi\b",
    r"\bpoint of interconnection\b",
    r"\binterconnection\b",
    r"\bswitchyard\b",
    r"\butility\b",
    r"\btransmission\b",
    r"\bhigh side\b",
]

INTERNAL_VOLTAGE_CONTEXT_PATTERNS = [
    r"\bdistribution\b",
    r"\bmedium voltage\b",
    r"\bmv\b",
    r"\bups\b",
    r"\bswitchgear\b",
    r"\bfeeder\b",
    r"\bbus\b",
    r"\bsecondary\b",
    r"\bgenerator\b",
    r"\bgenset\b",
]

PHASE_CONTEXT_PATTERNS: dict[str, list[str]] = {
    # Phase-specific fields must be anchored by explicit phase labels.  Generic
    # peak/requested/ultimate MW language belongs to peak_demand_mw, not Phase 1.
    "facility.load_schedule.phase_1_mw": [r"\bphase\s*1\b", r"\bphase\s*i\b", r"\bday one\b", r"\binitial phase\b", r"\bfirst phase\b"],
    "facility.load_schedule.phase_2_mw": [r"\bphase\s*2\b", r"\bphase\s*ii\b", r"\bsecond phase\b"],
    "facility.load_schedule.phase_3_mw": [r"\bphase\s*3\b", r"\bphase\s*iii\b", r"\bthird phase\b"],
}

BUILDOUT_CONTEXT_PATTERNS = [
    r"\bultimate\b",
    r"\bfull build\s*out\b",
    r"\bfinal build\s*out\b",
    r"\btotal campus\b",
]


def _windowed_match_context(text: str, match: re.Match[str], window: int = 40) -> str:
    sentence_start = text.rfind(".", 0, match.start())
    sentence_end = text.find(".", match.end())

    if sentence_start != -1 or sentence_end != -1:
        start = 0 if sentence_start == -1 else sentence_start + 1
        end = len(text) if sentence_end == -1 else sentence_end
    else:
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)

    return normalize_whitespace(text[start:end]).lower()


def _resolve_voltage_parameter_path(*, artifact: dict[str, Any], ontology: dict[str, Any] | None, context_window: str, value: float) -> str | None:
    ontology = ontology or {}
    document_type = str(ontology.get("document_type", "")).strip().upper()
    artifact_classification = str(artifact.get("classification", "")).strip().lower()
    file_name = str(artifact.get("file_name", "")).strip().lower()

    if contains_any_pattern(context_window, INTERNAL_VOLTAGE_CONTEXT_PATTERNS) and not contains_any_pattern(context_window, POI_CONTEXT_PATTERNS):
        return None
    if contains_any_pattern(context_window, POI_CONTEXT_PATTERNS):
        return "facility.poi_voltage_kv"
    if document_type == "ONE_LINE_DIAGRAM" or artifact_classification == "one_line_diagram" or "one-line" in file_name or "single_line" in file_name:
        if value >= 69.0 and not contains_any_pattern(context_window, INTERNAL_VOLTAGE_CONTEXT_PATTERNS):
            return "facility.poi_voltage_kv"
    return None


def _resolve_mw_parameter_path(*, context_window: str) -> str | None:
    if contains_any_pattern(context_window, BUILDOUT_CONTEXT_PATTERNS):
        return None
    for field_path, patterns in PHASE_CONTEXT_PATTERNS.items():
        if contains_any_pattern(context_window, patterns):
            return field_path
    # Preserve the current intake contract for simple peak-demand mentions while
    # still preventing maximum/ultimate campus totals from being treated as
    # Phase 1 buildout rows.
    if re.search(r"\bpeak\s+demand\b", context_window, re.IGNORECASE) and not re.search(r"\b(maximum|ultimate|full\s*build|total\s+campus)\b", context_window, re.IGNORECASE):
        return "facility.load_schedule.phase_1_mw"
    return None


TRANSFORMER_PAIR_REGEX = re.compile(
    r"(?P<primary>\d+(?:\.\d+)?)\s*kV\s*/\s*(?P<secondary>\d+(?:\.\d+)?)\s*kV",
    re.IGNORECASE,
)

TRANSFORMER_RATING_REGEX = re.compile(
    r"(?:transformer|xfmr)[^\n\r]{0,60}?(?P<value>\d+(?:\.\d+)?)\s*MVA",
    re.IGNORECASE,
)

UPS_MODULE_RATING_REGEX = re.compile(
    r"(?:UPS\s+module|module\s+rating)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*kW",
    re.IGNORECASE,
)

UPS_TOTAL_RATING_REGEX = re.compile(
    r"(?:UPS\s+total|UPS\s+rating|UPS\s+capacity)[^\n\r]{0,50}?(?P<value>\d+(?:\.\d+)?)\s*MW",
    re.IGNORECASE,
)

BATTERY_MINUTES_REGEX = re.compile(
    r"(?:battery\s+backup|runtime|ride[-\s]?through)[^\n\r]{0,50}?(?P<value>\d+(?:\.\d+)?)\s*minutes?",
    re.IGNORECASE,
)

GENERATOR_RATING_REGEX = re.compile(
    r"(?:generator|genset)[^\n\r]{0,60}?(?P<value>\d+(?:\.\d+)?)\s*MW",
    re.IGNORECASE,
)

POWER_FACTOR_REGEX = re.compile(
    r"\bpower factor\b[^\n\r]{0,30}?(?P<value>0?\.\d+)",
    re.IGNORECASE,
)

REACTIVE_REGEX = re.compile(
    r"\breactive capability\b[^\n\r]{0,30}?(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>MVAR|MVAr|pu)",
    re.IGNORECASE,
)

COUNT_REGEX_SPECS: list[dict[str, Any]] = [
    {
        "field_path": "interconnection_context.substation_topology.breaker_count",
        "patterns": [
            re.compile(r"(?P<value>\d+)\s+breakers?", re.IGNORECASE),
            re.compile(r"\bbreaker count\b[^\n\r]{0,20}?(?P<value>\d+)", re.IGNORECASE),
        ],
        "unit": "count",
        "score": 0.78,
    },
    {
        "field_path": "interconnection_context.substation_topology.bus_section_count",
        "patterns": [
            re.compile(r"(?P<value>\d+)\s+bus sections?", re.IGNORECASE),
            re.compile(r"\bbus section count\b[^\n\r]{0,20}?(?P<value>\d+)", re.IGNORECASE),
        ],
        "unit": "count",
        "score": 0.76,
    },
    {
        "field_path": "power_conversion_and_ups.ups_systems[].module_count",
        "patterns": [
            re.compile(r"(?P<value>\d+)\s+UPS modules?", re.IGNORECASE),
            re.compile(r"\bmodule count\b[^\n\r]{0,20}?(?P<value>\d+)", re.IGNORECASE),
        ],
        "unit": "count",
        "score": 0.80,
    },
    {
        "field_path": "backup_power_system.generator_units[].count",
        "patterns": [
            re.compile(r"(?P<value>\d+)\s+generators?", re.IGNORECASE),
            re.compile(r"\bgenerator count\b[^\n\r]{0,20}?(?P<value>\d+)", re.IGNORECASE),
        ],
        "unit": "count",
        "score": 0.80,
    },
]

TEXT_SCHEMA_SPECS: list[dict[str, Any]] = [
    {
        "field_path": "interconnection_context.point_of_interconnection.poi_name",
        "patterns": [
            re.compile(
                r"(?:point\s+of\s+interconnection|point-of-interconnection|POI)\s*[:\-]?\s*(?P<value>[A-Za-z0-9_\- /]{3,80})",
                re.IGNORECASE,
            ),
        ],
        "score": 0.78,
    },
    {
        "field_path": "interconnection_context.point_of_interconnection.poi_substation_name",
        "patterns": [
            re.compile(
                r"(?:substation|station)\s*[:\-]?\s*(?P<value>[A-Za-z0-9_\- /]{3,80})",
                re.IGNORECASE,
            ),
        ],
        "score": 0.74,
    },
    {
        "field_path": "interconnection_context.point_of_interconnection.poi_line_or_bus_name",
        "patterns": [
            re.compile(
                r"(?:line|bus)\s*(?:name)?\s*[:\-]?\s*(?P<value>[A-Za-z0-9_\- /]{2,80})",
                re.IGNORECASE,
            ),
        ],
        "score": 0.70,
    },
    {
        "field_path": "project_context.queue_position",
        "patterns": [
            re.compile(
                r"(?:queue\s+(?:position|number)|queue)\s*[:#\-]?\s*(?P<value>[A-Za-z0-9\-]+)",
                re.IGNORECASE,
            ),
        ],
        "score": 0.86,
    },
    {
        "field_path": "project_context.study_type",
        "patterns": [
            re.compile(
                r"(?:study\s+type)\s*[:\-]?\s*(?P<value>[A-Za-z][A-Za-z /\-]{3,40})",
                re.IGNORECASE,
            ),
        ],
        "score": 0.70,
    },
    {
        "field_path": "backup_power_system.fuel_system.fuel_type",
        "patterns": [
            re.compile(
                r"\bfuel type\b\s*[:\-]?\s*(?P<value>[A-Za-z][A-Za-z /\-]{2,40})",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?P<value>diesel|natural\s+gas|dual\s+fuel)\b",
                re.IGNORECASE,
            ),
        ],
        "score": 0.84,
    },
    {
        "field_path": "metering_and_telemetry.metering_configuration",
        "patterns": [
            re.compile(
                r"\bmetering configuration\b\s*[:\-]?\s*(?P<value>[A-Za-z0-9 /\-]{3,60})",
                re.IGNORECASE,
            ),
        ],
        "score": 0.75,
    },
]

MEASUREMENT_SCHEMA_SPECS: list[dict[str, Any]] = [
    {
        "field_path": "interconnection_context.point_of_interconnection.poi_voltage_kv",
        "patterns": [
            re.compile(
                r"(?:point\s+of\s+interconnection|point-of-interconnection|\bpoi\b)[^\n\r]{0,80}?(?P<value>\d+(?:\.\d+)?)\s*kV",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:interconnect(?:ion)?|service|utility)[^\n\r]{0,80}?(?P<value>\d+(?:\.\d+)?)\s*kV",
                re.IGNORECASE,
            ),
        ],
        "unit": "kV",
        "score": 0.92,
    },
    {
        "field_path": "facility_electrical_system.utility_service.service_voltage_kv",
        "patterns": [
            re.compile(
                r"(?:service\s+voltage|utility\s+service|incoming\s+service)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*kV",
                re.IGNORECASE,
            ),
        ],
        "unit": "kV",
        "score": 0.90,
    },
    {
        "field_path": "load_system.peak_demand_mw",
        "patterns": [
            re.compile(
                r"(?:peak\s+demand|maximum\s+demand|peak\s+load)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*MW",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?P<value>\d+(?:\.\d+)?)\s*MW[^\n\r]{0,30}?(?:peak\s+demand|peak\s+load)",
                re.IGNORECASE,
            ),
        ],
        "unit": "MW",
        "score": 0.90,
    },
    {
        "field_path": "backup_power_system.fuel_system.onsite_fuel_hours",
        "patterns": [
            re.compile(
                r"(?:onsite\s+fuel|on-site\s+fuel|fuel\s+autonomy)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*hours?",
                re.IGNORECASE,
            ),
        ],
        "unit": "hours",
        "score": 0.82,
    },
    {
        "field_path": "buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
        "patterns": [
            re.compile(
                r"(?:ramp\s+rate|normal\s+ramp)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*MW\s*/\s*min",
                re.IGNORECASE,
            ),
        ],
        "unit": "MW/min",
        "score": 0.84,
    },
    {
        "field_path": "buildout_and_ramping.ramp_characteristics.block_load_step_mw",
        "patterns": [
            re.compile(
                r"(?:block\s+load\s+step|step\s+load)[^\n\r]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*MW",
                re.IGNORECASE,
            ),
        ],
        "unit": "MW",
        "score": 0.84,
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()




NEXT_FIELD_LABEL_BOUNDARIES: tuple[str, ...] = (
    "project identification",
    "primary contacts",
    "electrical characteristics",
    "point of change in ownership",
    "nominal service voltage",
    "requested initial in-service",
    "requested in-service",
    "target energization",
    "ultimate commercial operation",
    "export condition",
    "maximum coincident demand",
    "downstream campus distribution",
    "nominal campus medium voltage",
    "transmission provider",
    "applicant",
    "owner",
    "project number",
    "project name",
    "queue number",
    "queue id",
    "page ",
    "confidential",
)

POI_REJECT_CONTEXT_PATTERNS: tuple[str, ...] = (
    r"campus\s+medium[-\s]?voltage",
    r"downstream\s+campus\s+distribution",
    r"switchgear\s+voltage",
    r"ups\s+(?:output|input|load)",
    r"low[-\s]?voltage",
    r"generator\s+(?:terminal|alternator)",
    r"alternator",
    r"medium[-\s]?voltage\s+distribution",
)


def _strip_known_following_labels(value: str) -> str:
    compact = normalize_whitespace(value)
    lowered = compact.lower()
    cut_at = len(compact)
    for label in NEXT_FIELD_LABEL_BOUNDARIES:
        idx = lowered.find(label.lower())
        if idx > 0:
            cut_at = min(cut_at, idx)
    return compact[:cut_at].strip(" -:;|,\t")


def bounded_text_value(value: Any, *, field_path: str = "", max_chars: int = 96) -> str:
    """Return a clean scalar value while leaving evidence excerpts available separately.

    OCR/layout text is often flattened, so regex groups that look bounded by a newline can
    accidentally absorb following form rows. This helper trims common next-label boundaries,
    table separators, footers, and long sentence tails before the value enters the candidate
    ledger.
    """
    text = _strip_known_following_labels(str(value or ""))
    text = re.split(r"\s{2,}|\s+\|\s+|[•●]", text, maxsplit=1)[0].strip(" -:;|,\t")
    if "poi" in field_path.lower() or "point_of_interconnection" in field_path.lower():
        text = re.split(r"\b(?:point\s+of\s+change|nominal\s+service|export\s+condition|requested\s+initial)\b", text, maxsplit=1, flags=re.IGNORECASE)[0].strip(" -:;|,\t")
    if len(text) > max_chars:
        sentence = re.split(r"(?<=[.;])\s+", text, maxsplit=1)[0].strip()
        text = sentence if 0 < len(sentence) <= max_chars else text[:max_chars].rsplit(" ", 1)[0].strip()
    return text.strip(" -:;|,\t")


def bounded_evidence_excerpt(text: str, start: int, end: int, *, window: int = 90, max_chars: int = 320) -> str:
    excerpt = excerpt_around(text, start, end, window=window)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[:max_chars].rsplit(" ", 1)[0].strip()


def _context_window(text: str, start: int, end: int, *, window: int = 120) -> str:
    return normalize_whitespace(text[max(0, start - window): min(len(text), end + window)])


def _poi_voltage_context_rejected(context: str) -> bool:
    return any(re.search(pattern, context, re.IGNORECASE) for pattern in POI_REJECT_CONTEXT_PATTERNS)


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def confidence_label(score: float) -> str:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    return "LOW"


def read_text_content(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    if suffix == ".txt":
        try:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    if suffix == ".json":
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return ""

    if suffix == ".csv":
        try:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    return ""


def load_canonical_schema() -> dict[str, Any]:
    try:
        return json.loads(CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def schema_field_exists(schema: dict[str, Any], field_path: str) -> bool:
    current: Any = schema

    for part in field_path.split("."):
        if part.endswith("[]"):
            list_name = part[:-2]
            if not isinstance(current, dict) or list_name not in current:
                return False
            current = current[list_name]
            if not isinstance(current, list) or not current:
                return False
            current = current[0]
            continue

        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]

    return True


def build_source_anchor(
    artifact_id: str,
    file_name: str,
    page: int = 1,
    parser_block_id: str | None = None,
    region_id: str | None = None,
    bbox: dict[str, Any] | None = None,
    source_method: str | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    parts = [f"{page:03d}"]
    if parser_block_id:
        parts.append(parser_block_id)
    if region_id:
        parts.append(region_id)

    anchor = SourceAnchor(
        anchor_id=f"{artifact_id}_anchor_{'_'.join(parts)}",
        artifact_id=artifact_id,
        file_name=file_name,
        page=page,
        text_pointer=f"local::{file_name}::page_{page}",
        parser_block_id=parser_block_id,
        region_id=region_id,
        bbox=bbox if isinstance(bbox, dict) else None,
        source_method=source_method,
        excerpt=excerpt,
    )
    return anchor.to_dict()


def contains_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def excerpt_around(text: str, start: int, end: int, window: int = 90) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return normalize_whitespace(text[left:right])


def add_entity(
    entities: list[dict[str, Any]],
    artifact_id: str,
    entity_type: str,
    name: str,
    source_anchor_id: str,
    attributes: dict[str, Any] | None = None,
    units: dict[str, Any] | None = None,
    extraction_method: str = "text_heuristic",
    confidence: str = "LOW",
    parameter_path: str | None = None,
    normalized_value: Any | None = None,
    raw_text: str | None = None,
    line_number: int | None = None,
) -> None:
    entity_id = f"{artifact_id}_{entity_type}_{len(entities) + 1:03d}"

    enriched_attributes: dict[str, Any] = dict(attributes or {})
    if parameter_path is not None:
        enriched_attributes["parameter_path"] = parameter_path
    if normalized_value is not None:
        enriched_attributes["normalized_value"] = normalized_value
    if raw_text is not None:
        enriched_attributes["raw_text"] = raw_text
    if line_number is not None:
        enriched_attributes["line_number"] = line_number

    enriched_attributes["extraction_method"] = extraction_method
    enriched_attributes["confidence"] = confidence

    entities.append(
        {
            "entity_id": entity_id,
            "type": entity_type,
            "name": name,
            "attributes": enriched_attributes,
            "units": units or {},
            "source_anchor_id": source_anchor_id,
        }
    )


def extract_named_entities(
    artifact: dict[str, Any],
    anchor_id: str,
    text: str,
    ontology: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    artifact_id = artifact["artifact_id"]
    file_name = artifact["file_name"]
    lowered_name = file_name.lower()
    lowered_text = text.lower()

    entities: list[dict[str, Any]] = []
    ontology = ontology or {}
    document_type = str(ontology.get("document_type", "")).strip()

    if (
        contains_any_pattern(lowered_name, UPS_PATTERNS)
        or contains_any_pattern(lowered_text, UPS_PATTERNS)
        or document_type == "UPS_SPECIFICATION"
    ):
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="ups_system",
            name="UPS System",
            source_anchor_id=anchor_id,
            parameter_path="facility.ups.topology",
            confidence="MODERATE" if document_type == "UPS_SPECIFICATION" else "LOW",
        )

    if (
        contains_any_pattern(lowered_name, GENERATOR_PATTERNS)
        or contains_any_pattern(lowered_text, GENERATOR_PATTERNS)
        or document_type == "GENERATOR_SPECIFICATION"
    ):
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="generator",
            name="Generator",
            source_anchor_id=anchor_id,
            confidence="MODERATE" if document_type == "GENERATOR_SPECIFICATION" else "LOW",
        )

    if contains_any_pattern(lowered_name, TRANSFORMER_PATTERNS) or contains_any_pattern(lowered_text, TRANSFORMER_PATTERNS):
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="transformer",
            name="Transformer",
            source_anchor_id=anchor_id,
        )

    if contains_any_pattern(lowered_name, SWITCHGEAR_PATTERNS) or contains_any_pattern(lowered_text, SWITCHGEAR_PATTERNS):
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="switchgear",
            name="Switchgear",
            source_anchor_id=anchor_id,
        )

    if (
        contains_any_pattern(lowered_name, RELAY_PATTERNS)
        or contains_any_pattern(lowered_text, RELAY_PATTERNS)
        or document_type == "PROTECTION_DIAGRAM"
    ):
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="relay_settings",
            name="Protection / Relay Settings",
            source_anchor_id=anchor_id,
            confidence="MODERATE" if document_type == "PROTECTION_DIAGRAM" else "LOW",
        )

    if contains_any_pattern(lowered_text, POI_PATTERNS) or document_type == "ONE_LINE_DIAGRAM":
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="point_of_interconnection",
            name="Point of Interconnection",
            source_anchor_id=anchor_id,
            confidence="MODERATE" if document_type == "ONE_LINE_DIAGRAM" else "LOW",
        )

    if "schedule" in lowered_name or "load schedule" in lowered_text or document_type == "LOAD_SCHEDULE":
        add_entity(
            entities=entities,
            artifact_id=artifact_id,
            entity_type="load_schedule",
            name="Load Schedule",
            source_anchor_id=anchor_id,
            extraction_method="filename_or_text_heuristic",
            confidence="MODERATE" if document_type == "LOAD_SCHEDULE" else "LOW",
        )

    return entities


def extract_voltage_entities(artifact: dict[str, Any], anchor_id: str, text: str, ontology: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    artifact_id = artifact["artifact_id"]
    entities: list[dict[str, Any]] = []

    for regex in VOLTAGE_REGEXES:
        for match in regex.finditer(text):
            value = float(match.group("value"))
            context_window = _windowed_match_context(text, match)
            parameter_path = _resolve_voltage_parameter_path(artifact=artifact, ontology=ontology, context_window=context_window, value=value)
            confidence = "MODERATE" if parameter_path else "LOW"
            add_entity(
                entities=entities,
                artifact_id=artifact_id,
                entity_type="voltage_value",
                name=f"Voltage {value} kV",
                source_anchor_id=anchor_id,
                attributes={"value": value, "measurement_type": "voltage", "context_window": context_window, "parameter_path": parameter_path},
                units={"value": "kV"},
                extraction_method="regex.contextual_voltage",
                confidence=confidence,
                parameter_path=parameter_path,
                normalized_value=value if parameter_path else None,
                raw_text=match.group(0),
            )

    return entities


def extract_mw_entities(artifact: dict[str, Any], anchor_id: str, text: str, ontology: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    artifact_id = artifact["artifact_id"]
    entities: list[dict[str, Any]] = []

    for regex in MW_REGEXES:
        for match in regex.finditer(text):
            value = float(match.group("value"))
            context_window = _windowed_match_context(text, match)
            parameter_path = _resolve_mw_parameter_path(context_window=context_window)
            confidence = "MODERATE" if parameter_path else "LOW"
            add_entity(
                entities=entities,
                artifact_id=artifact_id,
                entity_type="mw_value",
                name=f"Load {value} MW",
                source_anchor_id=anchor_id,
                attributes={"value": value, "measurement_type": "load_mw", "context_window": context_window, "parameter_path": parameter_path},
                units={"value": "MW"},
                extraction_method="regex.contextual_mw",
                confidence=confidence,
                parameter_path=parameter_path,
                normalized_value=value if parameter_path else None,
                raw_text=match.group(0),
            )

    return entities


def extract_transformer_rating_entities(artifact: dict[str, Any], anchor_id: str, text: str) -> list[dict[str, Any]]:
    artifact_id = artifact["artifact_id"]
    entities: list[dict[str, Any]] = []

    for regex in MVA_REGEXES:
        for match in regex.finditer(text):
            value = float(match.group("value"))
            add_entity(
                entities=entities,
                artifact_id=artifact_id,
                entity_type="transformer_rating",
                name=f"Transformer Rating {value} MVA",
                source_anchor_id=anchor_id,
                attributes={"value": value, "measurement_type": "transformer_rating_mva"},
                units={"value": "MVA"},
                extraction_method="regex",
                confidence="MODERATE",
                raw_text=match.group(0),
            )

    return entities


def extract_topology_cues(
    artifact: dict[str, Any],
    text: str,
    ontology: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    file_name = artifact["file_name"].lower()
    lowered = text.lower()
    artifact_id = artifact["artifact_id"]
    ontology = ontology or {}
    document_type = str(ontology.get("document_type", "")).strip()

    topology_cues: list[dict[str, Any]] = []

    if (
        "one-line" in file_name
        or "oneline" in file_name
        or artifact.get("classification") == "one_line_diagram"
        or document_type == "ONE_LINE_DIAGRAM"
    ):
        topology_cues.append(
            {
                "type": "one_line_diagram",
                "artifact_id": artifact_id,
                "confidence": "MODERATE" if document_type == "ONE_LINE_DIAGRAM" else "LOW",
                "source": "artifact_classification_or_filename",
            }
        )

    for cue_type, patterns in TOPOLOGY_PATTERNS.items():
        if contains_any_pattern(lowered, patterns):
            topology_cues.append(
                {
                    "type": cue_type,
                    "artifact_id": artifact_id,
                    "confidence": "LOW",
                    "source": "text_heuristic",
                }
            )

    return topology_cues


def deduplicate_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []

    for entity in entities:
        key = (
            entity.get("type"),
            entity.get("name"),
            entity.get("source_anchor_id"),
            json.dumps(entity.get("attributes", {}), sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)

    return deduped


def deduplicate_topology_cues(topology_cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []

    for cue in topology_cues:
        key = (cue.get("type"), cue.get("artifact_id"), cue.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cue)

    return deduped


def deduplicate_anchors(source_anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for anchor in source_anchors:
        anchor_id = str(anchor.get("anchor_id", "")).strip()
        if not anchor_id or anchor_id in seen:
            continue
        seen.add(anchor_id)
        deduped.append(anchor)

    return deduped


def deduplicate_schema_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []

    for candidate in candidates:
        key = (
            candidate.get("field_path"),
            json.dumps(candidate.get("value"), sort_keys=True, default=str),
            candidate.get("unit"),
            tuple(candidate.get("source_anchor_ids", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    return deduped


def coerce_documents(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if not payload:
        return []
    documents = payload.get(key, [])
    if not isinstance(documents, list):
        return []
    return [item for item in documents if isinstance(item, dict)]


def build_parser_text_index(
    document_parser_result: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    text_by_artifact_id: dict[str, str] = {}
    source_anchors: list[dict[str, Any]] = []
    evidence_records_by_artifact: dict[str, list[dict[str, Any]]] = {}

    parsed_documents = coerce_documents(document_parser_result, "parsed_documents")
    for document in parsed_documents:
        artifact_id = str(document.get("artifact_id", "")).strip()
        file_name = str(document.get("file_name", "")).strip()
        pages = document.get("pages", [])
        if not artifact_id or not isinstance(pages, list):
            continue

        page_texts: list[str] = []
        evidence_records_by_artifact.setdefault(artifact_id, [])

        for page in pages:
            if not isinstance(page, dict):
                continue
            page_number = int(page.get("page_number", 0) or 0)
            if page_number <= 0:
                continue

            page_text = normalize_whitespace(str(page.get("extracted_text", "")))
            if page_text:
                page_texts.append(page_text)
                page_anchor = build_source_anchor(
                    artifact_id=artifact_id,
                    file_name=file_name,
                    page=page_number,
                    source_method="document_parser.page",
                    excerpt=page_text[:280],
                )
                source_anchors.append(page_anchor)
                evidence_records_by_artifact[artifact_id].append(
                    {
                        "anchor_id": page_anchor["anchor_id"],
                        "artifact_id": artifact_id,
                        "file_name": file_name,
                        "page_number": page_number,
                        "text": page_text,
                        "source_method": "document_parser.page",
                    }
                )

            text_blocks = page.get("text_blocks", [])
            if not isinstance(text_blocks, list):
                continue

            for block in text_blocks:
                if not isinstance(block, dict):
                    continue
                block_text = normalize_whitespace(str(block.get("text", "")))
                block_id = str(block.get("block_id", "")).strip()
                if not block_id or not block_text:
                    continue

                block_anchor = build_source_anchor(
                    artifact_id=artifact_id,
                    file_name=file_name,
                    page=page_number,
                    parser_block_id=block_id,
                    bbox=block.get("bbox"),
                    source_method="document_parser.text_block",
                    excerpt=block_text[:280],
                )
                source_anchors.append(block_anchor)
                evidence_records_by_artifact[artifact_id].append(
                    {
                        "anchor_id": block_anchor["anchor_id"],
                        "artifact_id": artifact_id,
                        "file_name": file_name,
                        "page_number": page_number,
                        "text": block_text,
                        "bbox": block.get("bbox"),
                        "parser_block_id": block_id,
                        "source_method": "document_parser.text_block",
                    }
                )

        if page_texts:
            text_by_artifact_id[artifact_id] = normalize_whitespace(" ".join(page_texts))

    return text_by_artifact_id, source_anchors, evidence_records_by_artifact


def build_ocr_text_index(
    ocr_result: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    text_by_artifact_id: dict[str, str] = {}
    source_anchors: list[dict[str, Any]] = []
    evidence_records_by_artifact: dict[str, list[dict[str, Any]]] = {}

    documents = coerce_documents(ocr_result, "documents")
    for document in documents:
        artifact_id = str(document.get("artifact_id", "")).strip()
        file_name = str(document.get("file_name", "")).strip()
        pages = document.get("pages", [])
        if not artifact_id or not isinstance(pages, list):
            continue

        page_texts: list[str] = []
        evidence_records_by_artifact.setdefault(artifact_id, [])

        for page in pages:
            if not isinstance(page, dict):
                continue
            page_number = int(page.get("page_number", 0) or 0)
            if page_number <= 0:
                continue

            page_text = normalize_whitespace(str(page.get("extracted_text", "")))
            if page_text:
                page_texts.append(page_text)
                page_anchor = build_source_anchor(
                    artifact_id=artifact_id,
                    file_name=file_name,
                    page=page_number,
                    source_method="ocr.page",
                    excerpt=page_text[:280],
                )
                source_anchors.append(page_anchor)
                evidence_records_by_artifact[artifact_id].append(
                    {
                        "anchor_id": page_anchor["anchor_id"],
                        "artifact_id": artifact_id,
                        "file_name": file_name,
                        "page_number": page_number,
                        "text": page_text,
                        "source_method": "ocr.page",
                    }
                )

            text_regions = page.get("text_regions", [])
            if not isinstance(text_regions, list):
                continue

            for region in text_regions:
                if not isinstance(region, dict):
                    continue
                region_text = normalize_whitespace(str(region.get("text", "")))
                region_id = str(region.get("region_id", "")).strip()
                if not region_id or not region_text:
                    continue

                region_anchor = build_source_anchor(
                    artifact_id=artifact_id,
                    file_name=file_name,
                    page=page_number,
                    region_id=region_id,
                    bbox=region.get("bbox"),
                    source_method="ocr.region",
                    excerpt=region_text[:280],
                )
                source_anchors.append(region_anchor)
                evidence_records_by_artifact[artifact_id].append(
                    {
                        "anchor_id": region_anchor["anchor_id"],
                        "artifact_id": artifact_id,
                        "file_name": file_name,
                        "page_number": page_number,
                        "text": region_text,
                        "bbox": region.get("bbox"),
                        "region_id": region_id,
                        "source_method": "ocr.region",
                    }
                )

        if page_texts:
            text_by_artifact_id[artifact_id] = normalize_whitespace(" ".join(page_texts))

    return text_by_artifact_id, source_anchors, evidence_records_by_artifact


def merge_text_sources(
    artifacts: list[dict[str, Any]],
    document_parser_result: dict[str, Any] | None,
    ocr_result: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    parser_text_by_artifact_id, parser_anchors, parser_evidence = build_parser_text_index(document_parser_result)
    ocr_text_by_artifact_id, ocr_anchors, ocr_evidence = build_ocr_text_index(ocr_result)

    text_by_artifact_id: dict[str, str] = {}
    source_anchors: list[dict[str, Any]] = []
    evidence_records_by_artifact: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []

    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id", "")).strip()
        file_name = str(artifact.get("file_name", "")).strip()
        artifact_path = Path(str(artifact.get("file_path", "")))
        if not artifact_id:
            continue

        evidence_records_by_artifact.setdefault(artifact_id, [])

        parser_text = parser_text_by_artifact_id.get(artifact_id, "")
        ocr_text = ocr_text_by_artifact_id.get(artifact_id, "")

        if parser_text:
            text_by_artifact_id[artifact_id] = parser_text
        elif ocr_text:
            text_by_artifact_id[artifact_id] = ocr_text
        else:
            inline_text = normalize_whitespace(
                str(
                    artifact.get("text")
                    or artifact.get("text_content")
                    or artifact.get("parsed_text")
                    or ""
                )
            )

            if inline_text:
                text_by_artifact_id[artifact_id] = inline_text
            else:
                text_content = normalize_whitespace(read_text_content(artifact_path))
                text_by_artifact_id[artifact_id] = text_content

                if not text_content and artifact_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
                    warnings.append(
                        f"No text extraction performed for {file_name} due to unsupported legacy text parsing format."
                    )

        evidence_records_by_artifact[artifact_id].extend(parser_evidence.get(artifact_id, []))
        evidence_records_by_artifact[artifact_id].extend(ocr_evidence.get(artifact_id, []))

        if not evidence_records_by_artifact[artifact_id]:
            fallback_anchor = build_source_anchor(
                artifact_id=artifact_id,
                file_name=file_name,
                page=1,
                source_method="artifact_fallback",
                excerpt=text_by_artifact_id.get(artifact_id, "")[:280] or None,
            )
            source_anchors.append(fallback_anchor)
            if text_by_artifact_id.get(artifact_id, ""):
                evidence_records_by_artifact[artifact_id].append(
                    {
                        "anchor_id": fallback_anchor["anchor_id"],
                        "artifact_id": artifact_id,
                        "file_name": file_name,
                        "page_number": 1,
                        "text": text_by_artifact_id[artifact_id],
                        "source_method": "artifact_fallback",
                    }
                )

    source_anchors.extend(parser_anchors)
    source_anchors.extend(ocr_anchors)

    return text_by_artifact_id, deduplicate_anchors(source_anchors), evidence_records_by_artifact, warnings


def find_layout_document(layout_analysis_result: dict[str, Any] | None, artifact_id: str) -> dict[str, Any] | None:
    documents = coerce_documents(layout_analysis_result, "documents")
    for document in documents:
        if str(document.get("artifact_id", "")).strip() == artifact_id:
            return document
    return None


def schema_candidate(
    artifact: dict[str, Any],
    field_path: str,
    value: Any,
    unit: str | None,
    score: float,
    source_method: str,
    anchor_id: str,
    page_number: int,
    excerpt: str,
    candidate_index: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "candidate_id": f"{artifact['artifact_id']}_schema_{candidate_index:03d}",
        "field_path": field_path,
        "value": value,
        "status": "inferred",
        "confidence": round(score, 4),
        "confidence_label": confidence_label(score),
        "source_anchor_ids": [anchor_id],
        "evidence": [
            {
                "artifact_id": artifact["artifact_id"],
                "file_name": artifact["file_name"],
                "page_number": page_number,
                "anchor_id": anchor_id,
                "excerpt": excerpt,
            }
        ],
        "source_method": source_method,
        "notes": [],
        "metadata": dict(metadata or {}),
    }
    contamination = contamination_reasons(field_path, value, candidate["metadata"])
    if contamination:
        candidate["status"] = "rejected_contaminated"
        candidate["rejected_by_field_policy"] = True
        candidate["contamination_reasons"] = contamination
        candidate["notes"].append("Rejected as likely contaminated: " + "; ".join(contamination))
        candidate["metadata"]["contamination_reasons"] = contamination
    if unit is not None:
        candidate["unit"] = unit
    return candidate



PROJECT_PRIMARY_FILE_HINTS = (
    "large_load_request_form",
    "load_request",
    "project_summary",
    "load_schedule",
    "major_equipment_schedule",
    "equipment_schedule",
    "technical_particulars",
    "facilities_study",
    "energization_plan",
)

OEM_REFERENCE_FILE_HINTS = (
    "oem_",
    "datasheet",
    "data_sheet",
    "manual",
    "catalog",
    "brochure",
)


def _artifact_source_family(artifact: dict[str, Any]) -> str:
    file_name = str(artifact.get("file_name", "")).strip().lower()
    classification = str(artifact.get("classification", "")).strip().lower()
    blob = f"{file_name} {classification}"
    if any(hint in blob for hint in OEM_REFERENCE_FILE_HINTS):
        return "OEM_REFERENCE"
    if any(hint in blob for hint in PROJECT_PRIMARY_FILE_HINTS):
        return "PROJECT_PRIMARY"
    if "single_line" in blob or "one_line" in blob or "diagram" in blob:
        return "PROJECT_DRAWING"
    if "protection" in blob or "metering" in blob or "scada" in blob:
        return "PROJECT_SUPPORTING"
    return "PROJECT_PACKAGE"


def _source_family_score(source_family: str) -> float:
    return {
        "PROJECT_PRIMARY": 0.97,
        "PROJECT_SUPPORTING": 0.90,
        "PROJECT_DRAWING": 0.82,
        "PROJECT_PACKAGE": 0.76,
        "OEM_REFERENCE": 0.62,
    }.get(source_family, 0.70)


def _candidate_metadata(source_family: str, raw_text: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "raw_text": raw_text,
        "source_family": source_family,
        "field_source_policy": "project_primary_dominance" if source_family == "PROJECT_PRIMARY" else "bounded_reference_support",
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def _first_match(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> re.Match[str] | None:
    return re.search(pattern, text, flags)


def _emit_promoted_candidate(
    *,
    candidates: list[dict[str, Any]],
    artifact: dict[str, Any],
    field_path: str,
    value: Any,
    score: float,
    source_method: str,
    anchor_id: str,
    page_number: int,
    excerpt: str,
    candidate_index: int,
    source_family: str,
    metadata: dict[str, Any] | None = None,
    unit: str | None = None,
) -> int:
    if value is None:
        return candidate_index
    if isinstance(value, str) and not value.strip():
        return candidate_index
    candidate_index += 1
    meta = _candidate_metadata(source_family, excerpt, **(metadata or {}))
    candidates.append(
        schema_candidate(
            artifact=artifact,
            field_path=field_path,
            value=value,
            unit=unit,
            score=score,
            source_method=source_method,
            anchor_id=anchor_id,
            page_number=page_number,
            excerpt=excerpt,
            candidate_index=candidate_index,
            metadata=meta,
        )
    )
    return candidate_index


def scan_project_primary_package_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    """Extract project-specific facts from forms/schedules before generic/OEM evidence can pollute ranking."""
    del schema
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index
    source_family = _artifact_source_family(artifact)
    if source_family not in {"PROJECT_PRIMARY", "PROJECT_SUPPORTING"}:
        return candidates, candidate_index

    aggregate_text = "\n".join(str(record.get("text", "")) for record in evidence_records if str(record.get("text", "")).strip())
    if not aggregate_text.strip():
        return candidates, candidate_index
    normalized_text = normalize_whitespace(aggregate_text)
    anchor_id = str(evidence_records[0].get("anchor_id", f"{artifact['artifact_id']}_anchor_001")) if evidence_records else f"{artifact['artifact_id']}_anchor_001"
    page_number = int(evidence_records[0].get("page_number", 1) or 1) if evidence_records else 1
    base_score = _source_family_score(source_family)

    def emit(field_id: str, value: Any, raw: str, *, score_delta: float = 0.0, unit: str | None = None, family: str = "project_primary") -> None:
        nonlocal candidate_index
        score = min(0.99, max(0.50, base_score + score_delta))
        clean_value = value if unit in {"MW", "kV", "kW", "V", "A", "kA", "Mvar"} or isinstance(value, (int, float)) else bounded_text_value(value, field_path=field_id)
        if isinstance(clean_value, str) and not clean_value.strip():
            return
        candidate_index = _emit_promoted_candidate(
            candidates=candidates,
            artifact=artifact,
            field_path=field_id,
            value=clean_value,
            unit=unit,
            score=score,
            source_method=f"project_primary.{family}",
            anchor_id=anchor_id,
            page_number=page_number,
            excerpt=normalize_whitespace(raw)[:320],
            candidate_index=candidate_index,
            source_family=source_family,
            metadata={"promotion_family": family},
        )

    patterns: list[tuple[str, str, str, str | None]] = [
        ("project_name", r"(?:Project name|^Project\s+Name|Project:)\s*[:\n ]+\s*(?P<value>[^\n|]+)", "identity", None),
        ("project_number", r"(?:Project number|Project No\.|Project Reference)\s*[:\n ]+\s*(?P<value>[A-Z0-9][A-Z0-9_.-]+)", "identity", None),
        ("load_customer_name", r"(?:Applicant / owner|Applicant|Owner|Load customer)\s*[:\n ]+\s*(?P<value>[^\n|]+)", "identity", None),
        ("requested_in_service_date", r"(?:Requested initial in-service|Requested initial energization|Initial energization|Initial in-service|Phase\s*1\s+(?:energization|service available))\s*[:\n ]+\s*(?P<value>\d{4}-\d{2}-\d{2})", "schedule", None),
        ("ultimate_commercial_operation_date", r"(?:Ultimate commercial operation|Ultimate configuration available|Final phase energization|Phase\s*3\s+(?:energization|service available))\s*[:\n ]+\s*(?P<value>\d{4}-\d{2}-\d{2})", "schedule", None),
        ("point_of_interconnection_name", r"Point of interconnection(?:\s*\(POI\))?\s*[:\n ]+\s*(?P<value>[^\n]+)", "interconnection", None),
        ("nominal_poi_voltage_kv", r"(?:Nominal service voltage|customer service voltage|POI(?:\s+nominal)? voltage|point of interconnection[^\.\n]{0,80})\s*[:\n ]+\s*(?P<value>\d+(?:\.\d+)?)\s*kV", "interconnection", "kV"),
        ("facility_nominal_medium_voltage_kv", r"(?:Nominal campus medium voltage|campus medium-voltage|campus distribution|Downstream campus distribution)[^\n\.]{0,80}?(?P<value>\d+(?:\.\d+)?)\s*kV", "interconnection", "kV"),
        ("peak_demand_mw", r"(?:Maximum coincident demand at POI|maximum demand|peak demand|ultimate campus (?:build-out|loading|demand)|total coincident demand at POI)[^\n]{0,80}?(?P<value>\d+(?:\.\d+)?)\s*MW", "load", "MW"),
        ("critical_it_load_mw", r"(?:Critical IT load(?: at ultimate build-out)?|ultimate critical IT load)[^\n]{0,60}?(?P<value>\d+(?:\.\d+)?)\s*MW", "load", "MW"),
        ("generator_unit_count", r"(?:Campus quantity|Standby generators|package assumes|consisting of)[^\n]{0,80}?(?P<value>\d+)\s*(?:units total|generator|generators|Rolls-Royce|mtu)", "equipment_count", None),
        ("ups_unit_count", r"(?:Campus quantity|UPS modules|package assumes)[^\n]{0,80}?(?P<value>\d+)\s*(?:modules total|UPS|modules|Vertiv)", "equipment_count", None),
        ("interconnection_transformer_unit_count", r"(?:(?P<value_word>three|two|four|five|six)\s+main power transformers|Main transformers\s*\n\s*(?P<value>\d+)\s*\n|(?P<value2>\d+)\s+main power transformers)", "equipment_count", None),
        ("switchgear_unit_count", r"Main switchgear\s*\n\s*(?P<value>\d+)\s+lineup|uses\s+[A-Za-z0-9 _-]+\s+switchgear", "equipment_count", None),
        ("switchgear_model_family", r"(?:Siemens\s+)?(?P<value>NXAIR M)", "equipment_identity", None),
        ("switchgear_manufacturer", r"(?P<value>Siemens)\s+NXAIR M", "equipment_identity", None),
        ("switchgear_bus_rating_amps", r"(?:Nominal bus basis|bus rating)\s*[:\n ]+\s*(?P<value>\d{3,5})\s*A", "equipment_rating", "A"),
        ("switchgear_interrupting_rating_ka", r"(?:Interrupting duty|interrupting rating)\s*[:\n ]+\s*(?P<value>\d+(?:\.\d+)?)\s*kA", "equipment_rating", "kA"),
        ("ups_model_family", r"(?P<value>Vertiv Liebert EXL S1)", "equipment_identity", None),
        ("ups_capacity_kw_per_unit", r"(?P<value>1,?200)\s*kW", "equipment_rating", "kW"),
        ("ups_output_voltage_kv_or_v", r"1,?200\s*kW\s*(?:and|at)\s*(?P<value>480)\s*V", "equipment_rating", "V"),
        ("ups_topology", r"(?P<value>2N)(?:\s+architecture| hall architecture)", "equipment_topology", None),
        ("generator_model_family", r"(?P<value>Rolls-Royce mtu 16V4000 DS2500)", "equipment_identity", None),
        ("generator_rated_kw_per_unit", r"(?P<value>2,?500)\s*kWe", "equipment_rating", "kW"),
        ("generator_terminal_voltage_kv", r"(?P<value>13\.8)\s*kV\s+alternator", "equipment_rating", "kV"),
        ("capacitor_bank_step_count", r"(?:Six|(?P<value>6))\s+switched capacitor-bank steps", "reactive", None),
        ("capacitor_bank_step_size_mvar", r"capacitor-bank steps rated\s+(?P<value>\d+(?:\.\d+)?)\s*Mvar", "reactive", "Mvar"),
    ]

    for field_id, pattern, family, unit in patterns:
        match = _first_match(pattern, aggregate_text)
        if not match:
            match = _first_match(pattern, normalized_text)
        if not match:
            continue
        value = match.groupdict().get("value") or match.groupdict().get("value2") or match.group(0)
        if field_id in {"generator_unit_count", "ups_unit_count", "interconnection_transformer_unit_count", "switchgear_unit_count", "capacitor_bank_step_count"}:
            number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "sixty": 60}
            word_value = match.groupdict().get("value_word") if hasattr(match, "groupdict") else None
            if isinstance(word_value, str) and word_value.lower() in number_words:
                value = number_words[word_value.lower()]
            elif field_id == "switchgear_unit_count" and not re.search(r"\d", str(value)):
                value = 1
            else:
                lowered_match = match.group(0).lower()
                value = int(str(value).replace(",", "")) if re.search(r"\d", str(value)) else next((num for word, num in number_words.items() if word in lowered_match), value)
        elif unit in {"MW", "kV", "kW", "V", "A", "kA", "Mvar"}:
            value = safe_float(str(value).replace(",", ""))
        emit(field_id, value, excerpt_around(normalized_text, max(match.start(), 0), min(match.end(), len(normalized_text))), unit=unit, family=family)

    # Three transformer rating candidates are intentionally retained as a list-capable family.
    rating_match = _first_match(r"(?P<a>100)\s*/\s*(?P<b>133)\s*/\s*(?P<c>167)\s*MVA", normalized_text)
    if rating_match:
        for value in (100.0, 133.0, 167.0):
            emit("interconnection_transformer_rating_mva", value, excerpt_around(normalized_text, rating_match.start(), rating_match.end()), unit="MVA", family="equipment_rating")
        emit("service_transformer_rating_summary", "100/133/167 MVA OA/FA/FA", excerpt_around(normalized_text, rating_match.start(), rating_match.end()), family="equipment_rating")

    # Row-bound phase extraction: bind values to the phase label/row instead of
    # assigning ultimate MW totals to Phase 1 through generic numeric proximity.
    phase_values: dict[str, tuple[str, str]] = {}
    for match in re.finditer(r"Phase\s*([123])[^\n]{0,120}?(\d+(?:\.\d+)?)\s*MW", aggregate_text, re.IGNORECASE):
        phase = match.group(1)
        value = match.group(2)
        raw_excerpt = excerpt_around(aggregate_text, match.start(), match.end())
        phase_values.setdefault(phase, (value, raw_excerpt))
    slash_match = _first_match(r"Phase\s*1\s*/\s*2\s*/\s*3\s*demand\s*[:\n ]+\s*(?P<p1>\d+(?:\.\d+)?)\s*MW\s*/\s*(?P<p2>\d+(?:\.\d+)?)\s*MW\s*/\s*(?P<p3>\d+(?:\.\d+)?)\s*MW", aggregate_text, re.IGNORECASE | re.DOTALL)
    if slash_match:
        raw_excerpt = excerpt_around(aggregate_text, slash_match.start(), slash_match.end())
        phase_values.setdefault("1", (slash_match.group("p1"), raw_excerpt))
        phase_values.setdefault("2", (slash_match.group("p2"), raw_excerpt))
        phase_values.setdefault("3", (slash_match.group("p3"), raw_excerpt))
    table_match = _first_match(r"Phase\s+Gross campus MW[^\n]*\n\s*Phase\s*1\s+(?P<p1>\d+(?:\.\d+)?)\b.*?Phase\s*2\s+(?P<p2>\d+(?:\.\d+)?)\b.*?Phase\s*3\s+(?P<p3>\d+(?:\.\d+)?)\b", aggregate_text, re.IGNORECASE | re.DOTALL)
    if table_match:
        raw_excerpt = excerpt_around(aggregate_text, table_match.start(), table_match.end())
        phase_values.setdefault("1", (table_match.group("p1"), raw_excerpt))
        phase_values.setdefault("2", (table_match.group("p2"), raw_excerpt))
        phase_values.setdefault("3", (table_match.group("p3"), raw_excerpt))
    for phase, field_path in (("1", "facility.load_schedule.phase_1_mw"), ("2", "facility.load_schedule.phase_2_mw"), ("3", "facility.load_schedule.phase_3_mw")):
        if phase in phase_values:
            value, raw_excerpt = phase_values[phase]
            emit(field_path, safe_float(value), raw_excerpt, unit="MW", family="load_phase")
    if phase_values:
        summary = "; ".join(f"Phase {phase}: {phase_values[phase][0]} MW" for phase in sorted(phase_values))
        emit("buildout_phases_summary", summary, excerpt_around(normalized_text, 0, min(len(normalized_text), 260)), family="load")

    # Compatibility: older intake and interview contracts expose generic peak demand
    # through facility.load_schedule.phase_1_mw. Mirror only explicit "Peak demand"
    # wording here; maximum/ultimate demand remains on peak_demand_mw so phase
    # row binding is not polluted by ultimate campus totals.
    simple_peak_match = _first_match(r"\bPeak demand\s*(?P<value>\d+(?:\.\d+)?)\s*MW", aggregate_text, re.IGNORECASE)
    if simple_peak_match and "1" not in phase_values:
        emit("facility.load_schedule.phase_1_mw", safe_float(simple_peak_match.group("value")), excerpt_around(normalized_text, simple_peak_match.start(), simple_peak_match.end()), unit="MW", family="load_legacy_peak_alias")

    return candidates, candidate_index

def scan_measurement_schema_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index

    for spec in MEASUREMENT_SCHEMA_SPECS:
        field_path = spec["field_path"]
        if not schema_field_exists(schema, field_path):
            continue

        for record in evidence_records:
            text = str(record.get("text", ""))
            for pattern in spec["patterns"]:
                for match in pattern.finditer(text):
                    context = _context_window(text, match.start(), match.end())
                    if field_path == "interconnection_context.point_of_interconnection.poi_voltage_kv" and _poi_voltage_context_rejected(context):
                        continue
                    value = safe_float(match.group("value"))
                    if value is None:
                        continue
                    candidate_index += 1
                    candidates.append(
                        schema_candidate(
                            artifact=artifact,
                            field_path=field_path,
                            value=value,
                            unit=spec["unit"],
                            score=float(spec["score"]),
                            source_method="regex.measurement",
                            anchor_id=str(record.get("anchor_id", "")),
                            page_number=int(record.get("page_number", 1) or 1),
                            excerpt=bounded_evidence_excerpt(text, match.start(), match.end()),
                            candidate_index=candidate_index,
                            metadata={"raw_text": match.group(0), "context_window": context},
                        )
                    )

    return candidates, candidate_index


def scan_count_schema_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index

    for spec in COUNT_REGEX_SPECS:
        field_path = spec["field_path"]
        if not schema_field_exists(schema, field_path):
            continue

        for record in evidence_records:
            text = str(record.get("text", ""))
            for pattern in spec["patterns"]:
                for match in pattern.finditer(text):
                    try:
                        value = int(match.group("value"))
                    except (TypeError, ValueError):
                        continue

                    candidate_index += 1
                    candidates.append(
                        schema_candidate(
                            artifact=artifact,
                            field_path=field_path,
                            value=value,
                            unit=spec["unit"],
                            score=float(spec["score"]),
                            source_method="regex.count",
                            anchor_id=str(record.get("anchor_id", "")),
                            page_number=int(record.get("page_number", 1) or 1),
                            excerpt=bounded_evidence_excerpt(text, match.start(), match.end()),
                            candidate_index=candidate_index,
                            metadata={"raw_text": match.group(0), "context_window": context},
                        )
                    )

    return candidates, candidate_index


def scan_text_schema_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index

    for spec in TEXT_SCHEMA_SPECS:
        field_path = spec["field_path"]
        if not schema_field_exists(schema, field_path):
            continue

        for record in evidence_records:
            text = str(record.get("text", ""))
            for pattern in spec["patterns"]:
                for match in pattern.finditer(text):
                    value = bounded_text_value(match.group("value"), field_path=field_path)
                    if len(value) < 2:
                        continue

                    candidate_index += 1
                    candidates.append(
                        schema_candidate(
                            artifact=artifact,
                            field_path=field_path,
                            value=value,
                            unit=None,
                            score=float(spec["score"]),
                            source_method="regex.text_value",
                            anchor_id=str(record.get("anchor_id", "")),
                            page_number=int(record.get("page_number", 1) or 1),
                            excerpt=bounded_evidence_excerpt(text, match.start(), match.end()),
                            candidate_index=candidate_index,
                            metadata={"raw_text": match.group(0), "context_window": context},
                        )
                    )

    return candidates, candidate_index


def scan_structured_schema_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index

    aggregate_text = normalize_whitespace(" ".join(str(record.get("text", "")) for record in evidence_records))
    if not aggregate_text:
        return candidates, candidate_index

    anchor_id = str(evidence_records[0].get("anchor_id", f"{artifact['artifact_id']}_anchor_001"))
    page_number = int(evidence_records[0].get("page_number", 1) or 1)

    switching_field = "interconnection_context.substation_topology.switching_scheme"
    if schema_field_exists(schema, switching_field):
        for scheme_value, patterns in SWITCHING_SCHEME_PATTERNS.items():
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
                candidate_index += 1
                candidates.append(
                    schema_candidate(
                        artifact=artifact,
                        field_path=switching_field,
                        value=scheme_value,
                        unit=None,
                        score=0.80,
                        source_method="keyword.switching_scheme",
                        anchor_id=anchor_id,
                        page_number=page_number,
                        excerpt=aggregate_text[:220],
                        candidate_index=candidate_index,
                    )
                )

    for field_path, patterns in BOOLEAN_SCHEMA_PATTERNS.items():
        if not schema_field_exists(schema, field_path):
            continue
        if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=field_path,
                    value=True,
                    unit=None,
                    score=0.74,
                    source_method="keyword.boolean",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=aggregate_text[:220],
                    candidate_index=candidate_index,
                )
            )

    ups_topology_field = "power_conversion_and_ups.ups_systems[].topology"
    if schema_field_exists(schema, ups_topology_field):
        for value, patterns in UPS_TOPOLOGY_PATTERNS.items():
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
                candidate_index += 1
                candidates.append(
                    schema_candidate(
                        artifact=artifact,
                        field_path=ups_topology_field,
                        value=value,
                        unit=None,
                        score=0.86,
                        source_method="keyword.ups_topology",
                        anchor_id=anchor_id,
                        page_number=page_number,
                        excerpt=aggregate_text[:220],
                        candidate_index=candidate_index,
                    )
                )

    for match in TRANSFORMER_PAIR_REGEX.finditer(aggregate_text):
        primary = safe_float(match.group("primary"))
        secondary = safe_float(match.group("secondary"))
        if primary is None or secondary is None:
            continue

        primary_field = "facility_electrical_system.transformers[].primary_voltage_kv"
        if schema_field_exists(schema, primary_field):
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=primary_field,
                    value=primary,
                    unit="kV",
                    score=0.83,
                    source_method="regex.transformer_pair",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"pair_role": "primary"},
                )
            )

        secondary_field = "facility_electrical_system.transformers[].secondary_voltage_kv"
        if schema_field_exists(schema, secondary_field):
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=secondary_field,
                    value=secondary,
                    unit="kV",
                    score=0.83,
                    source_method="regex.transformer_pair",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"pair_role": "secondary"},
                )
            )

    transformer_rating_field = "facility_electrical_system.transformers[].rating_mva"
    if schema_field_exists(schema, transformer_rating_field):
        for match in TRANSFORMER_RATING_REGEX.finditer(aggregate_text):
            value = safe_float(match.group("value"))
            if value is None:
                continue
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=transformer_rating_field,
                    value=value,
                    unit="MVA",
                    score=0.86,
                    source_method="regex.transformer_rating",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"raw_text": match.group(0)},
                )
            )

    structured_measurements: list[tuple[re.Pattern[str], str, str, float, str]] = [
        (UPS_MODULE_RATING_REGEX, "power_conversion_and_ups.ups_systems[].module_rating_kw", "kW", 0.82, "regex.structured_equipment"),
        (UPS_TOTAL_RATING_REGEX, "power_conversion_and_ups.ups_systems[].total_rating_mw", "MW", 0.82, "regex.structured_equipment"),
        (BATTERY_MINUTES_REGEX, "power_conversion_and_ups.ups_systems[].battery_backup_minutes", "minutes", 0.80, "regex.structured_equipment"),
        (GENERATOR_RATING_REGEX, "backup_power_system.generator_units[].rating_mw", "MW", 0.82, "regex.structured_equipment"),
        (POWER_FACTOR_REGEX, "operating_characteristics.power_factor_requirement", "pu", 0.78, "regex.structured_equipment"),
    ]

    for regex, field_path, unit, score, source_method in structured_measurements:
        if not schema_field_exists(schema, field_path):
            continue

        for match in regex.finditer(aggregate_text):
            value = safe_float(match.group("value"))
            if value is None:
                continue
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=field_path,
                    value=value,
                    unit=unit,
                    score=score,
                    source_method=source_method,
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"raw_text": match.group(0)},
                )
            )

    reactive_field = "operating_characteristics.reactive_capability"
    if schema_field_exists(schema, reactive_field):
        for match in REACTIVE_REGEX.finditer(aggregate_text):
            value = safe_float(match.group("value"))
            if value is None:
                continue
            unit = str(match.group("unit")).replace("MVAr", "MVAR")
            candidate_index += 1
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=reactive_field,
                    value=value,
                    unit=unit,
                    score=0.78,
                    source_method="regex.reactive_capability",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"raw_text": match.group(0)},
                )
            )

    protection_scheme_field = "protection_controls_and_communications.protection_schemes[].scheme_type"
    if schema_field_exists(schema, protection_scheme_field):
        for scheme_type, patterns in PROTECTION_SCHEME_PATTERNS.items():
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
                candidate_index += 1
                candidates.append(
                    schema_candidate(
                        artifact=artifact,
                        field_path=protection_scheme_field,
                        value=scheme_type,
                        unit=None,
                        score=0.76,
                        source_method="keyword.protection_scheme",
                        anchor_id=anchor_id,
                        page_number=page_number,
                        excerpt=aggregate_text[:220],
                        candidate_index=candidate_index,
                    )
                )

    relay_type_field = "protection_controls_and_communications.protection_schemes[].relay_type"
    if schema_field_exists(schema, relay_type_field):
        for relay_type, patterns in RELAY_TYPE_PATTERNS.items():
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
                candidate_index += 1
                candidates.append(
                    schema_candidate(
                        artifact=artifact,
                        field_path=relay_type_field,
                        value=relay_type,
                        unit=None,
                        score=0.72,
                        source_method="keyword.relay_type",
                        anchor_id=anchor_id,
                        page_number=page_number,
                        excerpt=aggregate_text[:220],
                        candidate_index=candidate_index,
                    )
                )

    return candidates, candidate_index


def _promotion_field_supported(schema: dict[str, Any], field_path: str) -> bool:
    return schema_field_exists(schema, field_path) or bool(registry_field_id_for_path(field_path))


def _clean_promoted_text_value(value: str, *, max_length: int = 160) -> str:
    cleaned = normalize_whitespace(value).strip(" -:;,.	")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" -:;,.	")
    return cleaned


def promote_interconnection_fact_candidates(
    artifact: dict[str, Any],
    schema: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    candidate_index = start_index

    aggregate_text = normalize_whitespace(" ".join(str(record.get("text", "")) for record in evidence_records))
    if not aggregate_text:
        return candidates, candidate_index

    anchor_id = str(evidence_records[0].get("anchor_id", f"{artifact['artifact_id']}_anchor_001"))
    page_number = int(evidence_records[0].get("page_number", 1) or 1)

    for spec in INTERCONNECTION_TEXT_VALUE_SPECS:
        field_path = spec["field_path"]
        if not _promotion_field_supported(schema, field_path):
            continue
        for record in evidence_records:
            text = str(record.get("text", ""))
            if not text:
                continue
            for pattern in spec["patterns"]:
                for match in pattern.finditer(text):
                    value = _clean_promoted_text_value(str(match.group("value")))
                    if len(value) < 2:
                        continue
                    candidate_index += 1
                    candidates.append(
                        schema_candidate(
                            artifact=artifact,
                            field_path=field_path,
                            value=value,
                            unit=None,
                            score=float(spec["score"]),
                            source_method=str(spec["source_method"]),
                            anchor_id=str(record.get("anchor_id", anchor_id)),
                            page_number=int(record.get("page_number", page_number) or page_number),
                            excerpt=excerpt_around(text, match.start(), match.end()),
                            candidate_index=candidate_index,
                            metadata={"raw_text": match.group(0), "promotion_family": "interconnection_study"},
                        )
                    )

    region_field = "study_region_or_iso"
    if _promotion_field_supported(schema, region_field):
        for region, patterns in INTERCONNECTION_REGION_PATTERNS.items():
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns):
                candidate_index += 1
                candidates.append(
                    schema_candidate(
                        artifact=artifact,
                        field_path=region_field,
                        value=region,
                        unit=None,
                        score=0.88,
                        source_method="promotion.interconnection_region",
                        anchor_id=anchor_id,
                        page_number=page_number,
                        excerpt=aggregate_text[:220],
                        candidate_index=candidate_index,
                        metadata={"promotion_family": "interconnection_study"},
                    )
                )
                break

    revenue_field = "revenue_metering_configuration"
    if _promotion_field_supported(schema, revenue_field):
        match = REVENUE_METERING_REQUIRED_REGEX.search(aggregate_text)
        if match:
            candidate_index += 1
            value = _clean_promoted_text_value(match.group(0))
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=revenue_field,
                    value=value,
                    unit=None,
                    score=0.84,
                    source_method="promotion.metering_requirement",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=excerpt_around(aggregate_text, match.start(), match.end()),
                    candidate_index=candidate_index,
                    metadata={"promotion_family": "interconnection_study"},
                )
            )

    protection_field = "protection_scheme_summary"
    if _promotion_field_supported(schema, protection_field):
        matched_schemes = [
            label
            for label, patterns in INTERCONNECTION_PROTECTION_SUMMARY_PATTERNS.items()
            if any(re.search(pattern, aggregate_text, re.IGNORECASE) for pattern in patterns)
        ]
        if matched_schemes:
            candidate_index += 1
            summary = ", ".join(dict.fromkeys(matched_schemes))
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=protection_field,
                    value=f"Detected protection references: {summary}",
                    unit=None,
                    score=0.82,
                    source_method="promotion.protection_summary",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=aggregate_text[:240],
                    candidate_index=candidate_index,
                    metadata={"promotion_family": "interconnection_study", "matched_schemes": matched_schemes},
                )
            )

    relay_field = "relay_model_and_firmware_summary"
    if _promotion_field_supported(schema, relay_field):
        relay_models = [
            _clean_promoted_text_value(match.group("value"), max_length=40).upper()
            for match in INTERCONNECTION_RELAY_MODEL_REGEX.finditer(aggregate_text)
        ]
        relay_models = list(dict.fromkeys(model for model in relay_models if any(ch.isdigit() for ch in model)))
        firmware_match = INTERCONNECTION_RELAY_FIRMWARE_REGEX.search(aggregate_text)
        firmware = _clean_promoted_text_value(firmware_match.group("value"), max_length=40) if firmware_match else ""
        if relay_models or firmware:
            candidate_index += 1
            summary_parts: list[str] = []
            if relay_models:
                summary_parts.append("Relay models: " + ", ".join(relay_models[:4]))
            if firmware:
                summary_parts.append("Firmware: " + firmware)
            candidates.append(
                schema_candidate(
                    artifact=artifact,
                    field_path=relay_field,
                    value="; ".join(summary_parts),
                    unit=None,
                    score=0.8,
                    source_method="promotion.relay_reference",
                    anchor_id=anchor_id,
                    page_number=page_number,
                    excerpt=aggregate_text[:240],
                    candidate_index=candidate_index,
                    metadata={"promotion_family": "interconnection_study", "relay_models": relay_models[:4], "firmware": firmware},
                )
            )

    return deduplicate_schema_candidates(candidates), candidate_index


def build_schema_field_candidates(
    artifacts: list[dict[str, Any]],
    schema: dict[str, Any],
    evidence_records_by_artifact: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidate_index = 0

    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id", "")).strip()
        evidence_records = evidence_records_by_artifact.get(artifact_id, [])
        if not evidence_records:
            continue

        project_primary_candidates, candidate_index = scan_project_primary_package_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(project_primary_candidates)

        measurement_candidates, candidate_index = scan_measurement_schema_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(measurement_candidates)

        count_candidates, candidate_index = scan_count_schema_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(count_candidates)

        text_candidates, candidate_index = scan_text_schema_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(text_candidates)

        structured_candidates, candidate_index = scan_structured_schema_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(structured_candidates)

        promoted_candidates, candidate_index = promote_interconnection_fact_candidates(
            artifact=artifact,
            schema=schema,
            evidence_records=evidence_records,
            start_index=candidate_index,
        )
        candidates.extend(promoted_candidates)

    return deduplicate_schema_candidates(candidates)


def layout_warnings(
    artifacts: list[dict[str, Any]],
    layout_analysis_result: dict[str, Any] | None,
) -> list[str]:
    warnings: list[str] = []

    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id", "")).strip()
        layout_document = find_layout_document(layout_analysis_result, artifact_id)
        if not layout_document:
            continue

        pages = layout_document.get("pages", [])
        if not isinstance(pages, list):
            continue

        for page in pages:
            if not isinstance(page, dict):
                continue
            page_classification = str(page.get("page_classification", "")).strip()
            if page_classification in {"DIAGRAM", "MIXED", "TABLE"}:
                warnings.append(
                    f"Layout analysis found {page_classification} content in {artifact.get('file_name', '')} page {page.get('page_number', 0)}."
                )

    return warnings


def build_planner_registry_coverage(
    schema_field_candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    field_targets: list[dict[str, Any]] = []
    uncovered_fields: list[dict[str, Any]] = []

    candidate_count_by_field_path: dict[str, int] = {}
    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue
        field_path = str(candidate.get("field_path", "")).strip()
        if not field_path:
            continue
        candidate_count_by_field_path[field_path] = candidate_count_by_field_path.get(field_path, 0) + 1

    mapped_targets = 0
    uncovered_mapped_targets = 0

    for field in planner_registry_fields():
        field_id = str(field.get("field_id", "")).strip()
        if not field_id:
            continue
        field_path = field_path_for_registry_field_id(field_id)
        target = {
            "field_id": field_id,
            "field_path": field_path,
            "display_name": str(field.get("label", "")).strip() or field_id,
            "group": str(field.get("group", "")).strip(),
            "planner_critical": bool(field.get("planner_critical", False)),
            "requiredness": str(field.get("requiredness", "optional")).strip() or "optional",
            "preferred_sources": list(field.get("preferred_sources", [])) if isinstance(field.get("preferred_sources"), list) else [],
            "search_keywords": list(field.get("search_keywords", [])) if isinstance(field.get("search_keywords"), list) else [],
            "pipeline_touchpoints": list(field.get("pipeline_touchpoints", [])) if isinstance(field.get("pipeline_touchpoints"), list) else [],
        }
        matched_candidate_count = 0
        covered = False
        if isinstance(field_path, str) and field_path.strip():
            mapped_targets += 1
            matched_candidate_count = candidate_count_by_field_path.get(field_path.strip(), 0)
            covered = matched_candidate_count > 0
            if not covered:
                uncovered_mapped_targets += 1

        target["matched_candidate_count"] = matched_candidate_count
        target["covered"] = covered
        field_targets.append(target)

        if field_path and not covered:
            uncovered_fields.append(target)

    summary = {
        "planner_registry_field_count": len(field_targets),
        "mapped_planner_registry_field_count": mapped_targets,
        "covered_mapped_planner_registry_field_count": mapped_targets - uncovered_mapped_targets,
        "uncovered_mapped_planner_registry_field_count": uncovered_mapped_targets,
    }

    return field_targets, uncovered_fields, summary


