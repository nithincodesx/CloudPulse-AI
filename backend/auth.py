"""CloudPulse AI — Dashboard Authentication & Multi-Tenant Authorization.

Security model
==============
Two *separate* authentication planes exist:

1. **Dashboard plane** (this module): every ``/api/*`` dashboard endpoint
   derives the caller identity from a verified Supabase JWT
   (``Authorization: Bearer <access_token>``). Client-supplied ``user_id`` /
   ``org_id`` / ``user_email`` query parameters are NEVER trusted — they are
   at most *hints* that are validated against the verified identity and
   server-side organization membership.

2. **Telemetry plane** (``/api/metrics``): machines authenticate with a
   per-server ingestion token (256-bit, stored on the ``servers`` row). This
   plane is intentionally kept separate — a compromised node token can only
   write metrics for its own server, never read dashboard data.

Authorization rules enforced here (defense in depth with Supabase RLS):

* Organization membership is resolved server-side from the verified user id.
* RBAC roles (OWNER > ADMIN > MEMBER > VIEWER) gate every capability via
  ``tenant_service.PERMISSIONS``.
* Cross-tenant access returns **404** (resource existence is not leaked);
  insufficient role within the tenant returns **403**.
* Legacy single-tenant rows (``owner_id`` set, no ``organization_id``) are
  still reachable by their owner.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request, status

from database import (
    get_organization_member,
    get_server,
    get_aws_connection,
    list_aws_connections_for_org,
    list_organizations_for_user,
)
from logging_conf import get_logger
from tenant_service import verify_permission

load_dotenv()

logger = get_logger("backend.auth")

# Supabase signs project JWTs with the per-project JWT secret (HS256).
# Find it under Supabase → Settings → API → JWT Settings → JWT Secret.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
JWT_LEEWAY_SECONDS = int(os.getenv("SUPABASE_JWT_LEEWAY_SECONDS", "30"))
# Accepted JWT "role" claims — service_role / anon keys must never be accepted
# as a dashboard user identity.
_ALLOWED_JWT_ROLES = {"authenticated"}


class AuthenticationError(HTTPException):
    """401 — missing, malformed, or invalid credentials."""

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthorizationError(HTTPException):
    """403 — authenticated but not allowed to perform the action."""

    def __init__(self, detail: str = "Forbidden: insufficient permissions") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@dataclass
class AuthenticatedUser:
    """Verified dashboard identity — populated exclusively from the JWT."""

    user_id: str
    email: Optional[str] = None
    role: Optional[str] = None  # JWT role claim ("authenticated")
    claims: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------

def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify a Supabase access token's signature and standard claims.

    Returns the decoded claims. Raises ``jwt.PyJWTError`` subclasses on any
    validation failure (expired, bad signature, bad audience, ...).
    """
    if not token:
        raise jwt.InvalidTokenError("Empty token")

    if not SUPABASE_JWT_SECRET:
        # Fail closed: without the signing secret no token can be trusted.
        raise jwt.InvalidTokenError(
            "SUPABASE_JWT_SECRET is not configured — cannot verify dashboard tokens"
        )

    claims = jwt.decode(
        token,
        SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        # Supabase user access tokens always carry aud="authenticated".
        # Passing the expected audience is required: PyJWT rejects any
        # token that *has* an aud claim when no audience is supplied,
        # which would 401 every real sign-in.
        audience="authenticated",
        options={
            "require": ["exp", "sub"],
            "leeway": JWT_LEEWAY_SECONDS,
        },
    )

    token_role = (claims.get("role") or "").lower()
    if token_role and token_role not in _ALLOWED_JWT_ROLES:
        raise jwt.InvalidTokenError(f"JWT role '{token_role}' is not a dashboard identity")

    return claims


def _bearer_token(request: Request) -> Optional[str]:
    """Extract the bearer token from the Authorization header (None if absent)."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def get_current_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency: derive the authenticated user from a verified JWT.

    The identity comes ONLY from the token — never from query parameters or
    request bodies. Invalid/missing tokens produce a 401.
    """
    token = _bearer_token(request)
    if not token:
        raise AuthenticationError("Missing bearer token — dashboard JWT required")

    try:
        claims = verify_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Session expired — please sign in again") from None
    except jwt.PyJWTError as exc:
        logger.warning("auth.jwt.rejected", reason=str(exc))
        raise AuthenticationError("Invalid or malformed authentication token") from None

    user_id = str(claims.get("sub") or "")
    if not user_id:
        raise AuthenticationError("Token missing subject claim")

    return AuthenticatedUser(
        user_id=user_id,
        email=claims.get("email"),
        role=claims.get("role"),
        claims=claims,
    )


# ---------------------------------------------------------------------------
# Organization membership & RBAC
# ---------------------------------------------------------------------------

def get_org_member(user: AuthenticatedUser, org_id: str | None) -> Optional[dict]:
    """Return the verified user's membership row for an org (None when absent)."""
    if not org_id:
        return None
    return get_organization_member(str(org_id), user.user_id)


def resolve_org_for_user(
    user: AuthenticatedUser,
    org_id: str | None = None,
    *,
    permission: str | None = None,
    auto_provision: bool = False,
) -> tuple[str, str]:
    """Resolve and validate the organization scope for a request.

    ``org_id`` (query parameter) is only ever a *hint*: it must match a real
    membership of the verified user, otherwise 403. When omitted, the user's
    default (first) workspace is used.

    Returns ``(organization_id, role)``. Raises 403 when the user belongs to
    no workspace or lacks the requested permission.
    """
    if org_id:
        member = get_org_member(user, org_id)
        if not member:
            logger.warning(
                "auth.org.not_a_member",
                user_id=user.user_id,
                org_id=str(org_id),
            )
            raise AuthorizationError("You are not a member of this workspace")
        role = (member.get("role") or "").upper()
        resolved_org = str(member.get("organization_id") or org_id)
    else:
        orgs = list_organizations_for_user(user.user_id)
        if not orgs:
            if not auto_provision:
                raise AuthorizationError("No workspace available for this user")
            from tenant_service import get_or_create_default_workspace  # noqa: PLC0415

            default_org = get_or_create_default_workspace(user.user_id, user_email=user.email)
            if not default_org:
                raise AuthorizationError("No workspace available for this user")
            return str(default_org["id"]), default_org.get("user_role") or "OWNER"
        role = (orgs[0].get("user_role") or "").upper()
        resolved_org = str(orgs[0]["id"])

    if not role:
        raise AuthorizationError("Workspace membership has no assigned role")

    if permission and not verify_permission(role, permission):
        raise AuthorizationError(
            f"Insufficient permissions: role '{role}' cannot perform '{permission}'"
        )

    return resolved_org, role


def require_org_permission(
    user: AuthenticatedUser,
    org_id: str | None,
    permission: str,
    *,
    auto_provision: bool = False,
) -> tuple[str, str]:
    """Shorthand: resolve the org scope and enforce an RBAC permission."""
    return resolve_org_for_user(
        user, org_id, permission=permission, auto_provision=auto_provision
    )


# ---------------------------------------------------------------------------
# Resource authorizers (IDOR / cross-tenant protection)
# ---------------------------------------------------------------------------

def authorize_server(
    user: AuthenticatedUser,
    server_id: str,
    permission: str,
    org_id_hint: str | None = None,
) -> dict:
    """Authorize access to a server resource.

    * Server in another tenant → 404 (existence not leaked).
    * Server in own tenant without the role permission → 403.
    * Legacy org-less node owned by the user → allowed (owner fallback).
    """
    server = get_server(str(server_id)) if server_id else None
    if not server:
        raise HTTPException(status_code=404, detail=f"Server {server_id} not found")

    server_org = server.get("organization_id")
    if server_org:
        member = get_org_member(user, str(server_org))
        if not member:
            raise HTTPException(status_code=404, detail=f"Server {server_id} not found")
        if not verify_permission((member.get("role") or "").upper(), permission):
            raise AuthorizationError(
                f"Insufficient permissions: role '{member.get('role')}' "
                f"cannot perform '{permission}'"
            )
        return server

    # Legacy single-tenant node: owner fallback.
    if server.get("owner_id") and str(server["owner_id"]) == user.user_id:
        if not verify_permission("OWNER", permission):
            raise AuthorizationError("Insufficient permissions")
        return server

    # Unowned/legacy row — only reachable when an explicit org hint matches
    # a real membership AND the caller has the permission.
    if org_id_hint:
        member = get_org_member(user, str(org_id_hint))
        if member and verify_permission((member.get("role") or "").upper(), permission):
            return server

    raise HTTPException(status_code=404, detail=f"Server {server_id} not found")


def authorize_connection(
    user: AuthenticatedUser,
    connection_id: str,
    permission: str,
) -> dict:
    """Authorize access to an AWS connection (cross-tenant → 404)."""
    conn = get_aws_connection(str(connection_id)) if connection_id else None
    if not conn:
        raise HTTPException(
            status_code=404, detail=f"AWS connection {connection_id} not found"
        )

    conn_org = conn.get("organization_id")
    if conn_org:
        member = get_org_member(user, str(conn_org))
        if not member:
            raise HTTPException(
                status_code=404, detail=f"AWS connection {connection_id} not found"
            )
        if not verify_permission((member.get("role") or "").upper(), permission):
            raise AuthorizationError(
                f"Insufficient permissions: role '{member.get('role')}' "
                f"cannot perform '{permission}'"
            )
        return conn

    # Legacy connection scoped to a single user.
    if conn.get("user_id") and str(conn["user_id"]) == user.user_id:
        if not verify_permission("OWNER", permission):
            raise AuthorizationError("Insufficient permissions")
        return conn

    raise HTTPException(status_code=404, detail=f"AWS connection {connection_id} not found")


def resolve_org_connection(
    user: AuthenticatedUser,
    org_id: str | None,
    connection_id: str | None = None,
    *,
    permission: str = "view_aws_connections",
) -> Optional[dict]:
    """Resolve the AWS connection for org-scoped cloud endpoints.

    When ``connection_id`` is given it must belong to the verified user
    (404 otherwise). When omitted, the org's first *connected* connection
    (then its newest connection) is selected.
    """
    org, _role = resolve_org_for_user(user, org_id, permission=permission)

    if connection_id:
        return authorize_connection(user, connection_id, permission)

    member = get_org_member(user, str(org))
    if not member:
        raise AuthorizationError("You are not a member of this workspace")
    conns = list_aws_connections_for_org(str(org))
    connected = next((c for c in conns if c.get("status") == "connected"), None)
    return connected or (conns[0] if conns else None)
