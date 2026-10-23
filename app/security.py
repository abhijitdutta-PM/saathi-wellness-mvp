from datetime import datetime, timedelta, timezone
import logging
import secrets
import uuid
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db, set_tenant_context
from app.models import User, UserSession, Tenant

logger = logging.getLogger("saathi.security")
password_hasher = PasswordHasher()
COOKIE_NAME = "saathi_session"
SESSION_HOURS = 8

# These legacy role values remain in existing records for audit/data compatibility,
# but are no longer permitted to authenticate as interactive personas.
DISABLED_LOGIN_ROLES = {"parent", "school_admin", "safeguarding_lead", "content_reviewer"}

def ensure_login_role_enabled(user: User) -> None:
    if user.role in DISABLED_LOGIN_ROLES:
        raise HTTPException(status_code=403, detail="This Saathi role is no longer available for sign-in. Contact your school counsellor or approved support contact.")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def create_session_token(user: User, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "tid": user.tenant_id,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(hours=SESSION_HOURS),
        "iss": "saathi-wellness",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_session_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"], issuer="saathi-wellness")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again.") from exc


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=SESSION_HOURS * 60 * 60,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    claims = decode_session_token(token)
    tenant_id = str(claims.get("tid", ""))
    user_id = str(claims.get("sub", ""))
    session_id = str(claims.get("sid", ""))
    if not tenant_id or not user_id or not session_id:
        raise HTTPException(status_code=401, detail="Invalid session. Please sign in again.")

    set_tenant_context(db, tenant_id)
    session_row = db.scalar(select(UserSession).where(
        UserSession.id == session_id,
        UserSession.tenant_id == tenant_id,
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > datetime.now(timezone.utc),
    ))
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.active.is_(True)))
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active"))
    if not session_row or not user or not tenant:
        raise HTTPException(status_code=401, detail="Your session is no longer active. Please sign in again.")
    # Block legacy personas even when a session was issued before role reduction.
    ensure_login_role_enabled(user)
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        return user
    return dependency


def check_same_origin(request: Request) -> None:
    """Cookie-authenticated write requests accept only same-origin browser requests."""
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if request.url.path.startswith("/api/internal/"):
        return
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlparse
        supplied = urlparse(origin)
        expected = urlparse(settings.app_base_url)
        if supplied.scheme != expected.scheme or supplied.netloc != expected.netloc:
            raise HTTPException(status_code=403, detail="Cross-origin requests are not accepted.")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site.lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site requests are not accepted.")


def new_id() -> str:
    return str(uuid.uuid4())


def safe_request_id(request: Request) -> str:
    return request.headers.get("x-request-id", secrets.token_hex(8))[:80]
