"""Tenant & Organization management service for CloudPulse-AI.

Handles organization lifecycle, member roles (OWNER, ADMIN, MEMBER, VIEWER),
RBAC permission verification, and multi-tenant isolation.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any
from uuid import UUID

from audit_service import AuditActions, log_audit_event
from database import (
    create_organization,
    get_organization_by_id,
    get_organization_by_slug,
    list_organizations_for_user,
    update_organization,
    delete_organization,
    create_organization_member,
    get_organization_member,
    list_organization_members,
    update_organization_member_role,
    delete_organization_member,
    get_organization_counts,
)

logger = logging.getLogger("cloudpulse.tenant")


# Role Hierarchy: OWNER > ADMIN > MEMBER > VIEWER
ROLE_HIERARCHY = {
    "OWNER": 4,
    "ADMIN": 3,
    "MEMBER": 2,
    "VIEWER": 1,
}

# Role Permission Mapping
PERMISSIONS = {
    # Organization settings & billing
    "manage_org_settings": ["OWNER"],
    "delete_org": ["OWNER"],
    "manage_members": ["OWNER", "ADMIN"],
    "change_member_role": ["OWNER"],
    "view_audit_logs": ["OWNER", "ADMIN", "MEMBER"],

    # AWS Connection management
    "connect_aws": ["OWNER", "ADMIN"],
    "disconnect_aws": ["OWNER", "ADMIN"],
    "sync_aws": ["OWNER", "ADMIN", "MEMBER"],
    "view_aws_connections": ["OWNER", "ADMIN", "MEMBER", "VIEWER"],

    # Resources & Servers
    "manage_resources": ["OWNER", "ADMIN"],
    "view_resources": ["OWNER", "ADMIN", "MEMBER", "VIEWER"],

    # Alerts & Incidents
    "manage_alerts": ["OWNER", "ADMIN"],
    "investigate_incidents": ["OWNER", "ADMIN", "MEMBER"],
    "resolve_incidents": ["OWNER", "ADMIN", "MEMBER"],
    "view_alerts": ["OWNER", "ADMIN", "MEMBER", "VIEWER"],

    # Costs
    "view_costs": ["OWNER", "ADMIN", "MEMBER", "VIEWER"],
}


def slugify(text: str) -> str:
    """Generate a clean URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    if not text:
        text = "workspace"
    suffix = secrets.token_hex(3)
    return f"{text}-{suffix}"


def verify_permission(user_role: str | None, permission: str) -> bool:
    """Checks whether a given role holds the requested capability."""
    if not user_role:
        return False
    allowed_roles = PERMISSIONS.get(permission, [])
    return user_role.upper() in allowed_roles


def get_or_create_default_workspace(user_id: str | UUID, user_email: str | None = None) -> dict:
    """Ensures a user has at least one active workspace. If none exists, creates their default one."""
    user_id_str = str(user_id)
    orgs = list_organizations_for_user(user_id_str)
    if orgs:
        return orgs[0]

    # Create personal workspace for the user
    name = f"{user_email.split('@')[0].capitalize()}'s Workspace" if user_email else "My Workspace"
    slug = slugify(name)
    org = create_organization({
        "name": name,
        "slug": slug,
        "plan_tier": "free",
        "max_aws_connections": 5,
        "retention_days": 30,
    })

    if not org:
        raise RuntimeError("Failed to provision default workspace for user")

    # Add user as OWNER
    create_organization_member({
        "organization_id": org["id"],
        "user_id": user_id_str,
        "role": "OWNER",
        "invited_email": user_email,
    })

    log_audit_event(
        organization_id=org["id"],
        action=AuditActions.SETTINGS_UPDATED,
        resource_type="ORGANIZATION",
        actor_id=user_id_str,
        actor_email=user_email,
        resource_id=org["id"],
        metadata={"event": "workspace_created", "initial": True},
    )

    org["user_role"] = "OWNER"
    return org


def provision_organization(
    name: str,
    user_id: str | UUID,
    user_email: str | None = None,
    plan_tier: str = "free",
) -> dict:
    """Creates a new organization and assigns the creator as OWNER."""
    slug = slugify(name)
    org = create_organization({
        "name": name.strip(),
        "slug": slug,
        "plan_tier": plan_tier,
        "max_aws_connections": 5 if plan_tier == "free" else 20,
        "retention_days": 30 if plan_tier == "free" else 90,
    })

    if not org:
        raise RuntimeError(f"Could not create organization '{name}'")

    create_organization_member({
        "organization_id": org["id"],
        "user_id": str(user_id),
        "role": "OWNER",
        "invited_email": user_email,
    })

    log_audit_event(
        organization_id=org["id"],
        action=AuditActions.SETTINGS_UPDATED,
        resource_type="ORGANIZATION",
        actor_id=str(user_id),
        actor_email=user_email,
        resource_id=org["id"],
        metadata={"name": name, "plan_tier": plan_tier},
    )

    org["user_role"] = "OWNER"
    return org


def invite_member_to_org(
    organization_id: str | UUID,
    email: str,
    role: str,
    inviter_id: str | UUID,
    inviter_email: str | None = None,
) -> dict:
    """Invites a new member to an organization."""
    role = role.upper()
    if role not in ROLE_HIERARCHY or role == "OWNER":
        raise ValueError(f"Invalid invitation role: {role}")

    # Create invitation / member stub
    member_record = create_organization_member({
        "organization_id": str(organization_id),
        "user_id": str(secrets.token_hex(16)),  # Stub or real auth uid if existing
        "role": role,
        "invited_email": email.strip().lower(),
    })

    log_audit_event(
        organization_id=organization_id,
        action=AuditActions.MEMBER_INVITED,
        resource_type="MEMBER",
        actor_id=str(inviter_id),
        actor_email=inviter_email,
        resource_id=member_record.get("id") if member_record else None,
        metadata={"invited_email": email, "role": role},
    )

    return member_record or {}


def change_member_role(
    organization_id: str | UUID,
    member_id: str | UUID,
    new_role: str,
    actor_id: str | UUID,
    actor_email: str | None = None,
) -> dict:
    """Updates a member's role within an organization."""
    new_role = new_role.upper()
    if new_role not in ROLE_HIERARCHY:
        raise ValueError(f"Invalid role: {new_role}")

    updated = update_organization_member_role(str(organization_id), str(member_id), new_role)
    if not updated:
        raise RuntimeError("Member update failed")

    log_audit_event(
        organization_id=organization_id,
        action=AuditActions.MEMBER_ROLE_UPDATED,
        resource_type="MEMBER",
        actor_id=str(actor_id),
        actor_email=actor_email,
        resource_id=str(member_id),
        metadata={"new_role": new_role},
    )

    return updated


def remove_member_from_org(
    organization_id: str | UUID,
    member_id: str | UUID,
    actor_id: str | UUID,
    actor_email: str | None = None,
) -> bool:
    """Removes a member from an organization."""
    ok = delete_organization_member(str(organization_id), str(member_id))
    if ok:
        log_audit_event(
            organization_id=organization_id,
            action=AuditActions.MEMBER_REMOVED,
            resource_type="MEMBER",
            actor_id=str(actor_id),
            actor_email=actor_email,
            resource_id=str(member_id),
            metadata={},
        )
    return ok
