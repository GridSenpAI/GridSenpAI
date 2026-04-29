from services.agent_runtime_service.chunking import build_advisory_chunks, estimate_prompt_chars


def test_large_payload_is_split_into_bounded_domain_chunks() -> None:
    rows = [
        {
            "field_path": f"facility.load_schedule.phase_{idx}_mw",
            "accepted_value": idx,
            "evidence": "load demand evidence " * 200,
        }
        for idx in range(60)
    ]
    chunks = build_advisory_chunks(
        agent_id="translation_support_agent",
        agent_family_id="planner_support_agent",
        stage_name="translation",
        task_name="parameter_review",
        inputs={"output_parameters": rows, "canonical_state": "x" * 250000},
        max_prompt_chars=12000,
        max_evidence_chars=400,
    )
    assert len(chunks) > 1
    assert all(chunk.chunk_id for chunk in chunks)
    assert all(chunk.agent_id == "translation_support_agent" for chunk in chunks)
    assert all(chunk.estimated_chars < 12000 for chunk in chunks)
    assert any(chunk.domain == "load_and_demand" for chunk in chunks)


def test_chunk_payload_preserves_lineage_without_raw_giant_text() -> None:
    chunks = build_advisory_chunks(
        agent_id="packet_review_agent",
        agent_family_id="planner_support_agent",
        stage_name="export",
        task_name="planner_packet_review",
        inputs={"planner_packet_body": "A" * 50000, "registry_packet_summary": {"blocked": 10}},
        max_prompt_chars=10000,
        max_evidence_chars=500,
    )
    combined = "".join(str(chunk.to_dict()) for chunk in chunks)
    assert "planner_packet_body" in combined
    assert "A" * 2000 not in combined
    assert all(chunk.lineage for chunk in chunks)
