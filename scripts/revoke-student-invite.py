"""Revoke an unused student registration invitation by marking it redeemed.

Example:
  python scripts/revoke-student-invite.py --tenant demo-school --invite-id UUID-FROM-GENERATOR

This does not reveal or require the invitation code. It only revokes an unused invitation.
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from app.db import SessionLocal, set_tenant_context  # noqa: E402
from app.models import StudentRegistrationInvite, Tenant  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Revoke an unused student registration invitation")
    parser.add_argument("--tenant", required=True, help="Existing school tenant slug")
    parser.add_argument("--invite-id", required=True, help="Invitation ID printed by create-student-invites.py")
    args = parser.parse_args()
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant.strip().lower(), Tenant.status == "active"))
        if not tenant:
            print("Error: active tenant not found. Check --tenant.", file=sys.stderr)
            return 2
        set_tenant_context(db, tenant.id)
        invite = db.scalar(select(StudentRegistrationInvite).where(
            StudentRegistrationInvite.tenant_id == tenant.id,
            StudentRegistrationInvite.id == args.invite_id.strip(),
            StudentRegistrationInvite.redeemed_at.is_(None),
        ).with_for_update())
        if not invite:
            print("No unused invitation found for that ID and school. It may already be used or invalid.", file=sys.stderr)
            return 3
        invite.redeemed_at = datetime.now(timezone.utc)
        db.commit()
    print("Invitation revoked. It can no longer be used for registration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
