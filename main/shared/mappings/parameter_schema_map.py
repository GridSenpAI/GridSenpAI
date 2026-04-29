"""
GridSenpAI Parameter → Canonical Schema Mapping

Maps extraction candidate parameters to canonical facility schema paths.
This prevents schema drift and keeps normalization deterministic.
"""

PARAMETER_SCHEMA_MAP = {

    "voltage": {
        "schema_path": "facility_electrical_system.poi_voltage_kv",
        "expected_unit": "kV",
        "type": "float"
    },

    "power_rating": {
        "schema_path": "load_system.total_facility_load_mw",
        "expected_unit": "MW",
        "type": "float"
    },

    "current_rating": {
        "schema_path": "protection_system.breaker_current_rating_a",
        "expected_unit": "A",
        "type": "float"
    },

    "frequency": {
        "schema_path": "facility_electrical_system.system_frequency_hz",
        "expected_unit": "Hz",
        "type": "float"
    },

    "ups_presence": {
        "schema_path": "power_conversion_and_ups.ups_system_present",
        "expected_unit": None,
        "type": "boolean"
    },

    "generator_presence": {
        "schema_path": "backup_generation.generators_present",
        "expected_unit": None,
        "type": "boolean"
    },

    "transformer_presence": {
        "schema_path": "transformers.transformers_present",
        "expected_unit": None,
        "type": "boolean"
    }

}