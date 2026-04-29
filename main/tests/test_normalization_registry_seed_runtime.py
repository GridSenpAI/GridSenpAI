from types import SimpleNamespace
from services.normalization_service.service import normalize_inputs

class _Config(SimpleNamespace):
    project_name: str = "Runtime Seed Project"
    schema_version_input: str = "1.0.0"

def test_normalization_seed_payload_includes_registry_requested_paths() -> None:
    context = SimpleNamespace(run_id="run-normalization-seed", config=_Config())
    result = normalize_inputs(context=context, extraction_result={"entities": [], "topology_cues": [], "canonical_state": {}}, interview_result=None, retrieval_result=None)
    facility = result["normalized_input"]["facility"]
    assert "substation" in facility
    assert isinstance(facility["substation"], dict)
    assert "modeling" in facility
    assert isinstance(facility["modeling"], dict)
    assert facility["frequency_hz"] == 60
