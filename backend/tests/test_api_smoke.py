"""API smoke tests — every route, exercised end-to-end through FastAPI.

Why this file exists
--------------------
The unit suite mocks the layer below the one it tests, which let a class
of wiring bugs ship unnoticed: endpoints calling helpers with arguments
they don't accept, helpers used without being imported, and auth helpers
invoked without their required request. Those all surface as HTTP 500s
only when a real request crosses the endpoint → service → database path.

These tests drive every route through ``TestClient`` with:

* JWT auth replaced via ``dependency_overrides`` (plus direct patches for
  the helpers endpoints call inline, e.g. ``authorize_server``), and
* the Supabase client replaced by an in-memory fake whose queries return
  empty result sets.

Empty data means "not found" / "not configured" answers (401/404/503)
are legitimate. A **500 is never legitimate** here — it means the wiring
is broken. If you add a route, add it to ``CASES``.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import database
import main as main_mod
from auth import AuthenticatedUser
from main import app, authorize_connection, authorize_server, get_current_user


# ---------------------------------------------------------------------------
# Fake Supabase client (chainable query builder returning empty results)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if isinstance(data, list) else 0


class _FakeQuery:
    def __init__(self, data=None):
        self._data = data if data is not None else []

    def select(self, *a, **k):
        return self

    def insert(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def upsert(self, *a, **k):
        return self

    def delete(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def not_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    def maybe_single(self, *a, **k):
        return self

    def execute(self):
        return _FakeResult(self._data)


class _FakeClient:
    def table(self, name):
        return _FakeQuery()

    def rpc(self, name, params=None):
        return _FakeQuery()

    def from_(self, name):
        return _FakeQuery()


_TEST_USER = AuthenticatedUser(
    user_id="test-user", email="test@cloudpulse.io", role="authenticated", claims={}
)

ORG = "11111111-1111-1111-1111-111111111111"
SRV = "22222222-2222-2222-2222-222222222222"
CONN = "33333333-3333-3333-3333-333333333333"
ANY_ID = "44444444-4444-4444-4444-444444444444"

CASES = [
    ("GET", "/health", None),
    ("POST", "/api/metrics", {"cpu_usage": 1, "ram_usage": 2, "network_traffic": 3}),
    ("POST", "/api/servers/sync-node", {"id": SRV, "server_name": "n", "ingestion_token": "tok"}),
    ("GET", "/api/servers/status", None),
    ("GET", "/api/cloud/status", None),
    ("POST", "/api/cloud/discover", None),
    ("POST", "/api/cloud/sync", None),
    ("POST", "/api/aws/connections/initiate", {"region": "us-east-1"}),
    ("GET", "/api/aws/connections", None),
    (
        "POST",
        "/api/aws/connections",
        {
            "role_arn": "arn:aws:iam::123456789012:role/R",
            "external_id": "ext",
            "region": "us-east-1",
            "display_name": "x",
        },
    ),
    ("GET", f"/api/aws/connections/{CONN}", None),
    ("POST", f"/api/aws/connections/{CONN}/verify", None),
    ("GET", f"/api/aws/connections/{CONN}/health", None),
    ("POST", f"/api/aws/connections/{CONN}/sync", None),
    ("DELETE", f"/api/aws/connections/{CONN}", None),
    ("GET", "/api/organizations", None),
    ("POST", "/api/organizations", {"name": "Org", "plan_tier": "free"}),
    ("GET", f"/api/organizations/{ORG}", None),
    ("PUT", f"/api/organizations/{ORG}", {"name": "Org2"}),
    ("DELETE", f"/api/organizations/{ORG}", None),
    ("GET", f"/api/organizations/{ORG}/members", None),
    ("POST", f"/api/organizations/{ORG}/members", {"email": "a@b.co", "role": "MEMBER"}),
    ("PUT", f"/api/organizations/{ORG}/members/{ANY_ID}", {"role": "ADMIN"}),
    ("DELETE", f"/api/organizations/{ORG}/members/{ANY_ID}", None),
    ("GET", f"/api/organizations/{ORG}/audit-logs", None),
    ("GET", f"/api/organizations/{ORG}/usage", None),
    ("GET", "/api/insights/latest", None),
    ("POST", "/api/insights/generate", None),
    ("GET", f"/api/servers/{SRV}/metrics", None),
    ("GET", "/api/alerts", None),
    ("GET", "/api/costs/account", None),
    ("GET", "/api/costs/services", None),
    ("GET", "/api/costs/regions", None),
    ("GET", f"/api/costs/trends/{SRV}", None),
    ("GET", f"/api/costs/anomalies/{SRV}", None),
    ("PATCH", f"/api/alerts/{ANY_ID}/resolve", None),
    ("PUT", f"/api/servers/{SRV}/status", {"status": "idle"}),
    ("DELETE", f"/api/servers/{SRV}", None),
    ("GET", "/api/anomalies", None),
    ("GET", "/api/anomalies/events", None),
    ("PATCH", f"/api/anomalies/{ANY_ID}/resolve", None),
    ("GET", f"/api/anomalies/baseline/{SRV}", None),
    ("GET", "/api/optimization/summary", None),
    ("GET", "/api/optimization/recommendations", None),
    ("POST", "/api/optimization/analyze", None),
    ("PATCH", f"/api/optimization/recommendations/{ANY_ID}/status", {"status": "dismissed"}),
    ("GET", "/api/incidents", None),
    ("GET", f"/api/incidents/{ANY_ID}", None),
    ("PATCH", f"/api/incidents/{ANY_ID}/status", {"status": "acknowledged", "actor": "op"}),
    ("POST", f"/api/incidents/{ANY_ID}/notes", {"note_text": "hello", "author_name": "op"}),
    ("POST", f"/api/incidents/{ANY_ID}/investigate", None),
    ("GET", "/api/alerts/rules", None),
    (
        "POST",
        "/api/alerts/rules",
        {"name": "r", "rule_type": "CPU_ANOMALY", "severity": "warning"},
    ),
    ("DELETE", f"/api/alerts/rules/{ANY_ID}", None),
    ("GET", "/api/alerts/channels", None),
    (
        "POST",
        "/api/alerts/channels",
        {"name": "c", "channel_type": "webhook", "config": {"url": "https://example.com/hook"}},
    ),
    ("DELETE", f"/api/alerts/channels/{ANY_ID}", None),
    ("POST", f"/api/alerts/channels/{ANY_ID}/test", None),
    ("GET", "/api/alerts/logs", None),
]


@pytest.fixture()
def smoke_client():
    # NOTE: endpoints call authorize_* helpers *directly* (not via Depends),
    # so the fakes patched into main's namespace must be plain sync
    # functions — an async fake would hand the endpoint a coroutine.
    def _fake_user():
        return _TEST_USER

    def _fake_authorize_server(user, server_id, permission=None):
        return {"id": server_id, "server_name": "n", "organization_id": ORG}

    def _fake_authorize_connection(user, connection_id, permission=None):
        # Full AWSConnectionOut shape (external_id is the one required field
        # without a default) so response validation passes.
        return {
            "id": connection_id,
            "organization_id": ORG,
            "status": "active",
            "external_id": "ext-1",
            "role_arn": "arn:aws:iam::123456789012:role/R",
            "region": "us-east-1",
            "display_name": "AWS Account",
        }

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[authorize_server] = _fake_authorize_server
    app.dependency_overrides[authorize_connection] = _fake_authorize_connection

    real_supabase = database._supabase
    database._supabase = _FakeClient()
    patches = [
        patch.object(
            main_mod,
            "resolve_org_for_user",
            lambda user, org_id=None, permission=None, auto_provision=False: (ORG, "OWNER"),
        ),
        patch.object(main_mod, "authorize_server", _fake_authorize_server),
        patch.object(main_mod, "authorize_connection", _fake_authorize_connection),
    ]
    for p in patches:
        p.start()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        for p in patches:
            p.stop()
        database._supabase = real_supabase
        app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path,body", CASES, ids=[f"{m} {p}" for m, p, _ in CASES])
def test_endpoint_never_500s(smoke_client, method, path, body):
    response = (
        smoke_client.request(method, path, json=body)
        if body is not None
        else smoke_client.request(method, path)
    )
    assert response.status_code != 500, (
        f"{method} {path} returned 500: {response.text[:400]}"
    )


def test_dashboard_endpoints_reject_anonymous():
    """Without an auth override, dashboard-plane routes must 401 — only
    /health and the ingestion-token plane (/api/metrics) are public."""
    app.dependency_overrides.clear()
    client = TestClient(app, raise_server_exceptions=False)
    for path in ["/api/servers/status", "/api/alerts", "/api/organizations", "/api/costs/account"]:
        response = client.get(path)
        assert response.status_code == 401, f"GET {path} -> {response.status_code}, expected 401"
    assert client.get("/health").status_code in (200, 503)


def test_real_shaped_supabase_jwt_is_accepted():
    """A token shaped like a real Supabase access token (aud=authenticated,
    role=authenticated, HS256 with the project JWT secret) must verify —
    and a wrongly-signed one must not. Regression: jwt.decode() without an
    audience argument rejects every real Supabase token."""
    import time

    import jwt as pyjwt

    import auth as auth_mod

    secret = "unit-test-jwt-secret"
    claims = {
        "sub": "user-123",
        "role": "authenticated",
        "aud": "authenticated",
        "email": "a@b.co",
        "exp": int(time.time()) + 3600,
    }
    token = pyjwt.encode(claims, secret, algorithm="HS256")
    bad = pyjwt.encode(claims, "wrong-secret", algorithm="HS256")

    original = auth_mod.SUPABASE_JWT_SECRET
    auth_mod.SUPABASE_JWT_SECRET = secret
    try:
        decoded = auth_mod.verify_supabase_jwt(token)
        assert decoded["sub"] == "user-123"
        with pytest.raises(pyjwt.PyJWTError):
            auth_mod.verify_supabase_jwt(bad)
    finally:
        auth_mod.SUPABASE_JWT_SECRET = original
