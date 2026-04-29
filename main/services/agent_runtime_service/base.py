from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from services.agent_models.models import AgentDefinition, AgentRequest


class BaseBoundedAgent(ABC):
    def __init__(self, definition: AgentDefinition) -> None:
        self.definition = definition

    @property
    def agent_id(self) -> str:
        return self.definition.agent_id

    def supports(self, stage_name: str, task_name: str) -> bool:
        return self.definition.supports(stage_name, task_name)

    @abstractmethod
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        raise NotImplementedError
