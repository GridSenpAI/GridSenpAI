from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from shared.planner_registry import worker_routing_table


@dataclass(slots=True)
class ExtractionRoute:
    worker: str
    normalized_fields: list[str]


class ExtractionRouter:
    """Registry-governed routing policy for extraction-domain worker selection."""

    def __init__(self) -> None:
        routing = worker_routing_table()
        self._field_to_worker: dict[str, str] = {}
        for worker_name, field_paths in routing.items():
            if not isinstance(field_paths, tuple):
                field_paths = tuple(field_paths)
            for field_path in field_paths:
                normalized = self.normalize_field_path(field_path)
                if normalized and normalized not in self._field_to_worker:
                    self._field_to_worker[normalized] = worker_name

    def route_fields(self, field_paths: Iterable[str]) -> list[ExtractionRoute]:
        grouped: dict[str, list[str]] = {}
        for field_path in field_paths:
            normalized = self.normalize_field_path(field_path)
            if not normalized:
                continue
            worker = self.resolve_worker(normalized)
            grouped.setdefault(worker, []).append(normalized)
        return [ExtractionRoute(worker=worker, normalized_fields=fields) for worker, fields in grouped.items()]

    def resolve_worker(self, field_path: str) -> str:
        return self._field_to_worker.get(field_path, "spec_worker")

    def normalize_field_path(self, field_path: str) -> str:
        normalized = str(field_path or "").strip()
        if normalized.endswith(".configuration") and normalized.startswith("facility.substation"):
            return "facility.substation.configuration"
        return normalized
