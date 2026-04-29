from __future__ import annotations

from typing import Any, Dict, List

from shared.provenance.provenance_ledger import ProvenanceLedger
from shared.provenance.provenance_record import ProvenanceRecord


def build_provenance_record(
    parameter_path: str,
    provenance_type: str,
    provenance_ref: Any,
    confidence_score: float,
    confidence_tag: str,
) -> ProvenanceRecord:
    record = ProvenanceRecord(
        parameter_path=parameter_path,
        provenance_type=provenance_type,
        provenance_ref=provenance_ref,
        confidence_score=confidence_score,
        confidence_tag=confidence_tag,
    )
    record.validate()
    return record


def build_provenance_ledger(records: List[Dict[str, Any]]) -> ProvenanceLedger:
    ledger = ProvenanceLedger()

    for payload in records:
        record = ProvenanceRecord.from_dict(payload)
        ledger.add_record(record)

    ledger.validate()
    return ledger


def extract_provenance_from_parameters(
    parameters: List[Dict[str, Any]],
) -> ProvenanceLedger:
    ledger = ProvenanceLedger()

    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise TypeError(
                f"Parameter must be dict, got {type(parameter).__name__}"
            )

        record = ProvenanceRecord(
            parameter_path=str(parameter["parameter_path"]),
            provenance_type=str(parameter["provenance_type"]),
            provenance_ref=parameter["provenance_ref"],
            confidence_score=float(parameter["confidence_score"]),
            confidence_tag=str(parameter["confidence_tag"]),
        )
        ledger.add_record(record)

    ledger.validate()
    return ledger


def attach_provenance_to_parameters(
    parameters: List[Dict[str, Any]],
    ledger: ProvenanceLedger,
) -> List[Dict[str, Any]]:
    validated_parameters: List[Dict[str, Any]] = []

    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise TypeError(
                f"Parameter must be dict, got {type(parameter).__name__}"
            )

        path = str(parameter["parameter_path"])

        if not ledger.exists_for_parameter_path(path):
            raise ValueError(
                f"No provenance record exists for parameter '{path}'."
            )

        validated_parameters.append(parameter)

    return validated_parameters