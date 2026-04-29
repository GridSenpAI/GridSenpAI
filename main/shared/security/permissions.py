"""
RBAC permission and role definitions for GridSenpAI.

This module defines the canonical permission set and role mappings used
throughout the system for authorization enforcement.

Phase 5 Security Foundation
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Set


class Permission(str, Enum):
    """
    System actions that require authorization checks.
    """

    CREATE_RUN = "create_run"
    EXECUTE_PIPELINE = "execute_pipeline"
    REPLAY_PIPELINE = "replay_pipeline"

    VIEW_RUN = "view_run"
    VIEW_ARTIFACT = "view_artifact"

    VIEW_CANONICAL_STATE = "view_canonical_state"
    MODIFY_CANONICAL_STATE = "modify_canonical_state"

    APPROVE_VALIDATION = "approve_validation"

    EXPORT_RESULTS = "export_results"


class Role(str, Enum):
    """
    System user roles.
    """

    ADMIN = "admin"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    READ_ONLY = "read_only"


ROLE_PERMISSION_MAP: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.CREATE_RUN,
        Permission.EXECUTE_PIPELINE,
        Permission.REPLAY_PIPELINE,
        Permission.VIEW_RUN,
        Permission.VIEW_ARTIFACT,
        Permission.VIEW_CANONICAL_STATE,
        Permission.MODIFY_CANONICAL_STATE,
        Permission.APPROVE_VALIDATION,
        Permission.EXPORT_RESULTS,
    },
    Role.ENGINEER: {
        Permission.CREATE_RUN,
        Permission.EXECUTE_PIPELINE,
        Permission.VIEW_RUN,
        Permission.VIEW_ARTIFACT,
        Permission.VIEW_CANONICAL_STATE,
        Permission.MODIFY_CANONICAL_STATE,
        Permission.EXPORT_RESULTS,
    },
    Role.REVIEWER: {
        Permission.VIEW_RUN,
        Permission.VIEW_ARTIFACT,
        Permission.VIEW_CANONICAL_STATE,
        Permission.APPROVE_VALIDATION,
    },
    Role.READ_ONLY: {
        Permission.VIEW_RUN,
        Permission.VIEW_ARTIFACT,
        Permission.VIEW_CANONICAL_STATE,
    },
}