from pathlib import Path
from app.models import Base, StudentRegistrationInvite

ROOT = Path(__file__).resolve().parents[1]


def test_invitation_model_stores_digest_and_single_use_state():
    table = Base.metadata.tables["student_registration_invites"]
    assert StudentRegistrationInvite.__tablename__ == "student_registration_invites"
    assert {"tenant_id", "code_hash", "expires_at", "redeemed_at", "created_at"}.issubset(table.columns.keys())
    assert table.c.code_hash.type.length == 64


def test_registration_endpoint_is_student_only_and_invite_gated():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.post("/api/auth/student/register", status_code=201)' in source
    assert "StudentRegistrationInvite.code_hash == code_hash" in source
    assert "StudentRegistrationInvite.redeemed_at.is_(None)" in source
    assert "invite.redeemed_at = now" in source
    assert 'role="student"' in source
    assert '"student_self_registered"' in source
    assert '"case.created"' not in source[source.index('def register_student'):source.index('@app.post("/api/auth/login")')]


def test_registration_invite_table_is_in_tenant_rls_list():
    source = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
    assert '"student_registration_invites"' in source
    assert "current_setting('app.tenant_id'" in source


def test_registration_ui_and_operator_script_exist():
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "create-student-invites.py").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "STUDENT_SELF_REGISTRATION_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert 'id="registration-form"' in html
    assert '/api/auth/student/register' in js
    assert "hashlib.sha256" in script
    assert "Backout" in docs


def test_registration_rate_limit_is_more_forgiving_but_still_enabled():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    function = source[source.index("def rate_limit_registration"):source.index("def iso(")]
    assert "now - 900" in function  # rolling 15-minute window
    assert "if len(q) >= 20" in function
    assert "raise HTTPException(status_code=429" in function


def test_registration_flushes_student_before_audit_and_logs_database_failure():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    start = source.index("def register_student")
    end = source.index('@app.post("/api/auth/login")')
    endpoint = source[start:end]
    assert "db.flush()" in endpoint
    assert "logger.exception(\"Student registration integrity failure" in endpoint
    assert "logger.exception(\"Student registration persistence failure" in endpoint
    assert "from sqlalchemy.exc import IntegrityError" in source
