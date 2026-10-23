"""Create a real school tenant and primary/backup counsellor accounts.

Run inside the app container after the schema is initialized and before importing real data.
Do not use default/demo passwords; provision this in a protected terminal and rotate passwords.
"""
import argparse
import re
from pathlib import Path
import sys

# Make direct execution via ``python scripts\bootstrap_school.py`` reliable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.db import SessionLocal, set_tenant_context  # noqa: E402
from app.models import Tenant, User, RetentionPolicy
from app.security import hash_password, new_id
from app.services import write_audit


def strong(password: str) -> bool:
    return len(password) >= 14 and any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password) and any(not c.isalnum() for c in password)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap a school tenant and its primary and backup counsellor users")
    parser.add_argument("--slug", required=True, help="Short school code, e.g. greenfield-school")
    parser.add_argument("--name", required=True, help="Official school display name")
    parser.add_argument("--counsellor-email", required=True)
    parser.add_argument("--counsellor-name", required=True)
    parser.add_argument("--counsellor-password", required=True)
    parser.add_argument("--backup-counsellor-email", required=True)
    parser.add_argument("--backup-counsellor-name", required=True)
    parser.add_argument("--backup-counsellor-password", required=True)
    args = parser.parse_args()
    if not strong(args.counsellor_password) or not strong(args.backup_counsellor_password):
        parser.error("Passwords must be at least 14 characters and contain upper/lowercase, a digit, and a symbol")
    slug = args.slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?", slug):
        parser.error("School slug must be 2-80 characters, using lowercase letters, digits, and internal hyphens only")
    if not args.name.strip():
        parser.error("School name must not be empty")
    with SessionLocal() as db:
        existing = db.scalar(select(Tenant).where(Tenant.slug == slug))
        if existing:
            parser.error("That school slug already exists")
        tenant = Tenant(id=new_id(), slug=slug, name=args.name.strip(), status="active",
                        support_instructions="Please follow the school's approved safeguarding instructions. This application cannot guarantee an immediate human response.")
        db.add(tenant); db.commit()
        set_tenant_context(db, tenant.id)
        for category, days in (("journal_entries", 365), ("messages", 365), ("voice_sessions", 90), ("closed_cases", 1095)):
            db.add(RetentionPolicy(id=new_id(), tenant_id=tenant.id, data_category=category, retention_days=days,
                                   active=False, approved_for_live_data=False, policy_version="mvp-v1"))
        for email, name, role, password in [
            (args.counsellor_email, args.counsellor_name, "counsellor", args.counsellor_password),
            (args.backup_counsellor_email, args.backup_counsellor_name, "counsellor", args.backup_counsellor_password),
        ]:
            db.add(User(id=new_id(), tenant_id=tenant.id, email=email.strip().lower(), display_name=name.strip(),
                        role=role, age_band=None, password_hash=hash_password(password), active=True))
        write_audit(db, tenant.id, None, "school_tenant_bootstrapped", "tenant", tenant.id,
                    purpose="school_provisioning", metadata={"slug": slug})
        db.commit()
        print(f"Created tenant '{slug}'. Both counsellor accounts must complete your institution's MFA and onboarding process before use.")
        print("Next: create teacher accounts through an approved identity onboarding procedure; do not use demo seed accounts for real students.")

if __name__ == "__main__":
    main()
