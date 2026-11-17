"""Pytest bootstrap — makes the suite runnable with zero local setup.

The backend modules under test import ``database`` at module level, and
``database`` refuses to import without ``SUPABASE_URL`` /
``SUPABASE_SERVICE_KEY`` set. The unit tests are DB-free (they mock the
Supabase layer), so this conftest installs harmless dummy values *before*
any test module is imported:

* ``SUPABASE_URL`` — a non-routable ``.supabase.co`` placeholder.
* ``SUPABASE_SERVICE_KEY`` — a JWT-shaped dummy. The supabase-py client
  validates the key's shape at construction time, so a plain string like
  ``"dummy"`` is rejected; the payload below decodes to
  ``{"role": "service_role", ...}`` and is never sent anywhere.
* ``SUPABASE_JWT_SECRET`` — a throwaway secret so auth helpers import
  cleanly.

Real values already present in the environment (e.g. a developer's
``backend/.env`` exported into the shell) always win — ``setdefault`` is
used throughout.
"""

import base64
import json
import os


def _dummy_service_key() -> str:
    def _b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64(
        {
            "role": "service_role",
            "iss": "supabase",
            "ref": "dummy",
            "iat": 1700000000,
            "exp": 2000000000,
        }
    )
    return f"{header}.{payload}.dummy-signature"


os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", _dummy_service_key())
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-only-jwt-secret-not-for-production")
