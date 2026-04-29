import inspect

import shared.schemas.domain_registry as domain_registry


def test_registry_backed_domain_registry_no_longer_uses_legacy_fallbacks() -> None:
    domain_registry.load_extraction_blueprint.cache_clear()
    domain_registry.load_intake_question_specs.cache_clear()
    domain_registry.load_planner_document_specs.cache_clear()

    source = inspect.getsource(domain_registry)
    assert "_fallback_extraction_blueprint" not in source
    assert "_fallback_intake_question_specs" not in source
    assert "_fallback_planner_document_specs" not in source

    extraction_fields = domain_registry.load_extraction_blueprint()
    intake_questions = domain_registry.load_intake_question_specs()
    planner_documents = domain_registry.load_planner_document_specs()

    assert extraction_fields
    assert intake_questions
    assert planner_documents
    assert domain_registry.get_extraction_field("generator_model") is not None
    assert domain_registry.get_intake_question("generator_model") is not None

    domain_registry.load_extraction_blueprint.cache_clear()
    domain_registry.load_intake_question_specs.cache_clear()
    domain_registry.load_planner_document_specs.cache_clear()
