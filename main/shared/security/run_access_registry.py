from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set

from shared.security.models import Actor
from shared.security.permissions import Role


@dataclass
class RunAccessRecord:
    """
    Tracks access permissions for a specific pipeline run.
    """

    run_id: str
    owner_actor_id: str
    collaborators: Set[str] = field(default_factory=set)


class RunAccessRegistry:
    """
    Maintains ownership and collaborator access for pipeline runs.

    Phase-5 security requirement:
    Prevent actors from operating on runs they do not own or have access to.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, RunAccessRecord] = {}

    # -------------------------------------------------------------
    # Run registration
    # -------------------------------------------------------------

    def register_run(self, run_id: str, actor: Actor) -> None:
        """
        Register a newly created run and record the owner.
        """

        if run_id in self._runs:
            return

        self._runs[run_id] = RunAccessRecord(
            run_id=run_id,
            owner_actor_id=actor.actor_id,
        )

    # -------------------------------------------------------------
    # Collaborator management
    # -------------------------------------------------------------

    def add_collaborator(self, run_id: str, actor_id: str) -> None:
        record = self._runs.get(run_id)
        if not record:
            raise KeyError(f"Run not registered: {run_id}")

        record.collaborators.add(actor_id)

    # -------------------------------------------------------------
    # Access validation
    # -------------------------------------------------------------

    def can_access_run(self, actor: Actor, run_id: str) -> bool:
        """
        Determine whether an actor can access a run.
        """

        # Admin always allowed
        if actor.role == Role.ADMIN:
            return True

        record = self._runs.get(run_id)
        if not record:
            return False

        if actor.actor_id == record.owner_actor_id:
            return True

        if actor.actor_id in record.collaborators:
            return True

        return False