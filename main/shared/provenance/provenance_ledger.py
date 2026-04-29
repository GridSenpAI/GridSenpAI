from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from shared.provenance.provenance_record import ProvenanceRecord


@dataclass(slots=True)
class ProvenanceLedger:
    """
    Canonical provenance ledger for translated parameters.
    """

    records: List[ProvenanceRecord] = field(default_factory=list)

    def add_record(self, record: ProvenanceRecord) -> None:
        record.validate()
        self.records.append(record)

    def add_records(self, records: List[ProvenanceRecord]) -> None:
        for record in records:
            self.add_record(record)

    def get_by_parameter_path(self, parameter_path: str) -> List[ProvenanceRecord]:
        return [
            record
            for record in self.records
            if record.parameter_path == parameter_path
        ]

    def exists_for_parameter_path(self, parameter_path: str) -> bool:
        return any(
            record.parameter_path == parameter_path
            for record in self.records
        )

    def validate_unique_parameter_paths(self) -> None:
        seen: set[str] = set()

        for record in self.records:
            if record.parameter_path in seen:
                raise ValueError(
                    f"Duplicate provenance record detected for parameter_path "
                    f"'{record.parameter_path}'."
                )
            seen.add(record.parameter_path)

    def validate(self) -> None:
        for record in self.records:
            record.validate()

        self.validate_unique_parameter_paths()

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProvenanceLedger":
        raw_records = payload.get("records", [])

        if not isinstance(raw_records, list):
            raise TypeError(
                f"records must be a list, got {type(raw_records).__name__}."
            )

        ledger = cls()

        for item in raw_records:
            if not isinstance(item, dict):
                raise TypeError(
                    f"Each provenance record must be a dict, got {type(item).__name__}."
                )
            ledger.add_record(ProvenanceRecord.from_dict(item))

        ledger.validate()
        return ledger