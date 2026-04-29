from __future__ import annotations

from shared.security.models import Actor, AuthorizationRequest
from shared.security.permissions import Permission, Role
from shared.security.run_access_registry import RunAccessRegistry
from services.authorization_service.service import (
    AuthorizationError,
    AuthorizationService,
)


def _build_actor(actor_id: str, role: Role) -> Actor:
    return Actor(
        actor_id=actor_id,
        role=role,
        display_name=actor_id,
        email=None,
    )


def test_authorization_allows_run_owner_for_pipeline_execution() -> None:
    actor = _build_actor("engineer_owner", Role.ENGINEER)
    registry = RunAccessRegistry()
    registry.register_run("run_001", actor)

    service = AuthorizationService(run_access_registry=registry)

    result = service.authorize(
        AuthorizationRequest(
            actor=actor,
            permission=Permission.EXECUTE_PIPELINE,
            resource_type="pipeline_run",
            resource_id="run_001",
        )
    )

    assert result.allowed is True
    assert result.reason is None
    assert result.metadata.get("run_scope_checked") is True
    assert result.metadata.get("run_scope_allowed") is True


def test_authorization_denies_non_owner_for_pipeline_execution() -> None:
    owner = _build_actor("engineer_owner", Role.ENGINEER)
    other_actor = _build_actor("engineer_other", Role.ENGINEER)

    registry = RunAccessRegistry()
    registry.register_run("run_001", owner)

    service = AuthorizationService(run_access_registry=registry)

    result = service.authorize(
        AuthorizationRequest(
            actor=other_actor,
            permission=Permission.EXECUTE_PIPELINE,
            resource_type="pipeline_run",
            resource_id="run_001",
        )
    )

    assert result.allowed is False
    assert "does not have access to run" in str(result.reason)
    assert result.metadata.get("run_scope_checked") is True
    assert result.metadata.get("run_scope_allowed") is False


def test_authorization_allows_collaborator_for_export() -> None:
    owner = _build_actor("engineer_owner", Role.ENGINEER)
    collaborator = _build_actor("reviewer_collab", Role.REVIEWER)

    registry = RunAccessRegistry()
    registry.register_run("run_001", owner)
    registry.add_collaborator("run_001", collaborator.actor_id)

    service = AuthorizationService(run_access_registry=registry)

    result = service.authorize(
        AuthorizationRequest(
            actor=collaborator,
            permission=Permission.EXPORT_RESULTS,
            resource_type="export_artifacts",
            resource_id="run_001",
        )
    )

    assert result.allowed is False
    assert "does not have permission" in str(result.reason)


def test_authorization_allows_admin_for_any_run_scope() -> None:
    owner = _build_actor("engineer_owner", Role.ENGINEER)
    admin = _build_actor("admin_user", Role.ADMIN)

    registry = RunAccessRegistry()
    registry.register_run("run_001", owner)

    service = AuthorizationService(run_access_registry=registry)

    result = service.authorize(
        AuthorizationRequest(
            actor=admin,
            permission=Permission.EXPORT_RESULTS,
            resource_type="export_artifacts",
            resource_id="run_001",
        )
    )

    assert result.allowed is True
    assert result.reason is None
    assert result.metadata.get("run_scope_checked") is True
    assert result.metadata.get("run_scope_allowed") is True


def test_authorization_require_raises_for_non_owner_run_scope() -> None:
    owner = _build_actor("engineer_owner", Role.ENGINEER)
    other_actor = _build_actor("engineer_other", Role.ENGINEER)

    registry = RunAccessRegistry()
    registry.register_run("run_001", owner)

    service = AuthorizationService(run_access_registry=registry)

    try:
        service.require(
            AuthorizationRequest(
                actor=other_actor,
                permission=Permission.MODIFY_CANONICAL_STATE,
                resource_type="canonical_state",
                resource_id="run_001",
            )
        )
        raise AssertionError("Expected AuthorizationError to be raised.")
    except AuthorizationError as exc:
        assert "does not have access to run" in str(exc)


def test_authorization_denies_when_run_scope_required_but_registry_missing() -> None:
    actor = _build_actor("engineer_owner", Role.ENGINEER)
    service = AuthorizationService(run_access_registry=None)

    result = service.authorize(
        AuthorizationRequest(
            actor=actor,
            permission=Permission.EXPORT_RESULTS,
            resource_type="export_artifacts",
            resource_id="run_001",
        )
    )

    assert result.allowed is False
    assert "no run access registry was provided" in str(result.reason)


def test_authorization_does_not_require_run_scope_for_non_run_resource() -> None:
    actor = _build_actor("engineer_owner", Role.ENGINEER)
    service = AuthorizationService(run_access_registry=None)

    result = service.authorize(
        AuthorizationRequest(
            actor=actor,
            permission=Permission.VIEW_ARTIFACT,
            resource_type="artifact_catalog",
            resource_id="artifact_001",
        )
    )

    assert result.allowed is True
    assert result.reason is None
    assert result.metadata == {}