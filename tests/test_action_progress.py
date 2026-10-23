from pathlib import Path

from app.models import Base, CaseActionProgress

ROOT = Path(__file__).resolve().parents[1]


def test_progress_history_table_has_required_persistent_fields():
    table = Base.metadata.tables["case_action_progress"]
    assert {"tenant_id", "action_id", "author_user_id", "work_performed", "outcome",
            "further_concerns", "next_step", "submitted_for_review", "created_at"}.issubset(table.columns.keys())
    assert CaseActionProgress.__tablename__ == "case_action_progress"


def test_progress_and_review_endpoints_are_role_gated_and_audited():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.post("/api/actions/{action_id}/progress")' in source
    assert '@app.patch("/api/actions/{action_id}/review")' in source
    assert "Only a counsellor may review or close a support action." in source
    assert "Teachers must submit progress for counsellor review rather than changing action status directly." in source
    assert '"case_action_submitted_for_review"' in source
    assert '"case_action_review_approved"' in source


def test_progress_history_is_tenant_rls_protected_and_rendered_in_ui():
    db_source = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
    ui_source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert '"case_actions", "case_action_progress", "audit_events"' in db_source
    assert "progress_history" in ui_source
    assert "Submit to counsellor" in ui_source
    assert "Approve completion" in ui_source
