"""
Security identity and authorization models for GridSenpAI.

Phase 5 RBAC foundation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.security.permissions import Permission, Role


@dataclass(frozen=True)
class Actor:
    """
    Represents the identity performing an action in the system.
    """

    actor_id: str
    role: Role
    display_name: Optional[str] = None
    email: Optional[str] = None


@dataclass
class AuthorizationRequest:
    """
    Represents a request to perform an action against a resource.
    """

    actor: Actor
    permission: Permission
    resource_type: str
    resource_id: Optional[str] = None


@dataclass
class AuthorizationResult:
    """
    Result of an authorization decision.
    """

    allowed: bool
    reason: Optional[str] = None

    actor_id: Optional[str] = None
    role: Optional[Role] = None

    permission: Optional[Permission] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    metadata: dict = field(default_factory=dict)