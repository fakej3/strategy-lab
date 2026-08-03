"""Single-user authentication — PBKDF2 hashed password, session cookies."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status


# ── Credentials ───────────────────────────────────────────────────────────────
# Set EDGELAB_USERNAME and EDGELAB_PASSWORD_HASH before starting.
# Generate a hash:
#   python -c "from server.auth import hash_password; print(hash_password('yourpass'))"

_USERNAME  = os.environ.get("EDGELAB_USERNAME",      "admin")
_PASS_HASH = os.environ.get("EDGELAB_PASSWORD_HASH", "")

USING_DEFAULT_CREDS: bool = not _PASS_HASH  # warn on startup if true

# ── Secret key (session signing) ──────────────────────────────────────────────
# Persist across restarts by storing in a local file, or set EDGELAB_SECRET_KEY.
_KEY_FILE = Path(__file__).parent / ".secret_key"


def _load_or_create_secret() -> str:
    env_key = os.environ.get("EDGELAB_SECRET_KEY", "")
    if env_key:
        return env_key
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text().strip()
    key = secrets.token_hex(32)
    _KEY_FILE.write_text(key)
    return key


SECRET_KEY: str = _load_or_create_secret()


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a hex PBKDF2-SHA256 digest for use as EDGELAB_PASSWORD_HASH."""
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), b"edgelab-salt", 260_000
    )
    return dk.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        # No hash configured — default credentials are admin / admin
        return password == "admin"
    computed = hash_password(password)
    return hmac.compare_digest(computed, stored_hash)


def authenticate(username: str, password: str) -> bool:
    if username != _USERNAME:
        return False
    return verify_password(password, _PASS_HASH)


# ── FastAPI dependency ─────────────────────────────────────────────────────────

def require_auth(request: Request) -> str:
    """Dependency: return username or raise 303 redirect to /login."""
    user = request.session.get("user")
    if not user:
        next_url = request.url.path
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={next_url}"},
        )
    return user


AuthUser = Annotated[str, Depends(require_auth)]
