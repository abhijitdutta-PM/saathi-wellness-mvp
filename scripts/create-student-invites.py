"""Create single-use student self-registration invitation codes.

Run from the project root after database schema has been initialized:
  python scripts/create-student-invites.py --tenant demo-school --count 10 --expires-days 30
Codes are printed once. Distribute each code privately to its intended student.
Only SHA-256 digests are stored in PostgreSQL.
"""
from __future__ import annotations
import argparse
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from app.db import SessionLocal, set_tenant_context  # noqa: E402
from app.models import StudentRegistrationInvite, Tenant  # noqa: E402
from app.security import new_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one-time student registration invitations")
    parser.add_argument("--tenant", required=True, help="Existing school tenant slug")
    parser.add_argument("--count", type=int, default=1, help="Number of single-use codes (1-500)")
    parser.add_argument("--expires-days", type=int, default=30, help="Code lifetime in days (1-180)")
    args = parser.parse_args()
    if not 1 <= args.count <= 500:
        parser.error("--count must be between 1 and 500")
    if not 1 <= args.expires_days <= 180:
        parser.error("--expires-days must be between 1 and 180")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=args.expires_days)
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant.strip().lower(), Tenant.status == "active"))
        if not tenant:
            print("Error: active tenant not found. Check --tenant.", file=sys.stderr)
            return 2
        set_tenant_context(db, tenant.id)
        output: list[tuple[str, str]] = []
        for _ in range(args.count):
            code = secrets.token_urlsafe(24)
            row = StudentRegistrationInvite(
                id=new_id(), tenant_id=tenant.id,
                code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
                expires_at=expires,
            )
            db.add(row)
            output.append((row.id, code))
        db.commit()
    print(f"Tenant: {args.tenant}\nExpires at (UTC): {expires.isoformat()}\nCodes below are shown once; distribute each privately.\n")
    print("INVITATION_ID (internal; do not enter in registration)\tINVITATION_CODE (enter only this value)")
    for invite_id, code in output:
        print(f"{invite_id}\t{code}")
    print("\nDo not commit these codes to source control, email them in bulk, or reuse a code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
