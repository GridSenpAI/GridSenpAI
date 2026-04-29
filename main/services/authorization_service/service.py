"""
Authorization service for GridSenpAI.

Evaluates RBAC permissions and emits audit-compatible decision results.

Phase 5 Security Foundation
"""

from __future__ import annotations

from typing import Optional

from shared.security.models import (
    Actor,
    AuthorizationRequest,
    AuthorizationResult,
)
from shared.security.permissions import ROLE_PERMISSION_MAP, Permission
from shared.security.run_access_registry import RunAccessRegistry


class AuthorizationError(Exception):
    """Raised when authorization fails."""


class AuthorizationService:
    """
    Central RBAC authorization evaluator with optional run-scope enforcement.
    """

    def __init__(
        self,
        audit_service: Optional[object] = None,
        run_access_registry: Optional[RunAccessRegistry] = None,
    ) -> None:
        """
        Parameters
        ----------
        audit_service:
            Optional audit logging service. If provided, authorization
            decisions will be emitted to the audit log.
        run_access_registry:
            Optional registry used to enforce run ownership / collaborator scope.
        """
        self.audit_service = audit_service
        self.run_access_registry = run_access_registry

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        """
        Evaluate whether an actor may perform a permission on a resource.
        """

        actor: Actor = request.actor
        permission: Permission = request.permission

        allowed_permissions = ROLE_PERMISSION_MAP.get(actor.role, set())
        allowed = permission in allowed_permissions

        reason = None
        metadata: dict[str, object] = {}

        if not allowed:
            reason = (
                f"Role '{actor.role.value}' does not have permission "
                f"'{permission.value}'."
            )
        elif self._requires_run_scope_check(request):
            if self.run_access_registry is None:
                allowed = False
                reason = (
                    "Run scope enforcement required but no run access registry "
                    "was provided."
                )
            else:
                has_scope_access = self.run_access_registry.can_access_run(
                    actor=actor,
                    run_id=str(request.resource_id),
                )
                metadata["run_scope_checked"] = True
                metadata["run_scope_allowed"] = has_scope_access

                if not has_scope_access:
                    allowed = False
                    reason = (
                        f"Actor '{actor.actor_id}' does not have access to run "
                        f"'{request.resource_id}'."
                    )

        result = AuthorizationResult(
            allowed=allowed,
            reason=reason,
            actor_id=actor.actor_id,
            role=actor.role,
            permission=permission,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            metadata=metadata,
        )

        self._emit_audit_event(result)

        return result

    def require(self, request: AuthorizationRequest) -> None:
        """
        Enforce authorization and raise if denied.
        """

        result = self.authorize(request)

        if not result.allowed:
            raise AuthorizationError(
                f"Authorization denied: {result.reason}"
            )

    def _requires_run_scope_check(self, request: AuthorizationRequest) -> bool:
        """
        Determine whether the request should also be constrained by run access.
        """

        if request.resource_id is None:
            return False

        return request.resource_type in {
            "pipeline_run",
            "canonical_state",
            "export_artifacts",
        }

    def _emit_audit_event(self, result: AuthorizationResult) -> None:
        """
        Emit authorization decision to audit service if configured.
        """

        if self.audit_service is None:
            return

        log_event = getattr(self.audit_service, "log_event", None)

        if not callable(log_event):
            return

        try:
            log_event(
                event_type="authorization_decision",
                payload={
                    "actor_id": result.actor_id,
                    "role": result.role.value if result.role else None,
                    "permission": result.permission.value
                    if result.permission
                    else None,
                    "resource_type": result.resource_type,
                    "resource_id": result.resource_id,
                    "allowed": result.allowed,
                    "reason": result.reason,
                    "metadata": result.metadata,
                },
            )
        except Exception:
            # Authorization must never break the pipeline
            pass