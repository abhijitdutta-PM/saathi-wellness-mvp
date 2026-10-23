import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_passwords_are_not_shipped_in_static_assets():
    for relative in ("app/static/index.html", "app/static/app.js"):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert "DemoStudent-2026!" not in content
        assert "DemoCounsellor-2026!" not in content
        assert "DemoAdmin-2026!" not in content


def test_notification_workflow_accepts_only_minimal_authenticated_events():
    workflow = json.loads((ROOT / "n8n/workflows/01-event-notifications-and-followups.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in workflow["nodes"]}
    assert "Authenticated Saathi Event" in names
    assert "Validate Minimal Tenant Event" in names
    joined = "\n".join(node.get("parameters", {}).get("jsCode", "") for node in workflow["nodes"])
    assert "contains_student_content !== false" in joined
    assert "No authorized recipient was resolved" in joined
    assert "http://app:8000" not in joined
    webhook = next(node for node in workflow["nodes"] if node["name"] == "Authenticated Saathi Event")
    assert webhook["parameters"].get("authentication") == "headerAuth"
    assert webhook["parameters"].get("path") == "wellness-events"


def test_aggregate_report_uses_backend_pushed_aggregates_not_localhost_api():
    workflow = json.loads((ROOT / "n8n/workflows/02-daily-aggregate-report.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in workflow["nodes"]}
    assert "Authenticated Daily Report" in names
    assert "Validate Aggregate-Only Report" in names
    joined = "\n".join(node.get("parameters", {}).get("jsCode", "") for node in workflow["nodes"])
    assert "contains_student_content !== false" in joined
    assert "No authorized report recipient" in joined
    assert "http://app:8000" not in joined


def test_health_workflow_is_outbound_heartbeat_only():
    workflow = json.loads((ROOT / "n8n/workflows/03-workflow-health-check.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in workflow["nodes"]}
    assert "Receive Backend Health Ping" in names
    assert "Validate Heartbeat" in names
    assert "http://app:8000" not in json.dumps(workflow)


def test_no_pgvector_dependency_or_schema_reference_remains():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    models = (ROOT / "app/models.py").read_text(encoding="utf-8").lower()
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").lower()
    assert "pgvector" not in requirements
    assert "pgvector" not in models
    assert "pgvector/pgvector" not in compose
    assert "pinecone" in requirements


def test_pinecone_uses_per_tenant_namespaces_and_never_stores_student_messages():
    code = (ROOT / "app/vector_store.py").read_text(encoding="utf-8")
    assert 'return "global" if tenant_id is None else f"school-{tenant_id}"' in code
    assert "Student messages and transcripts must never be upserted" in code
    assert '"knowledge_item_id"' in code


def test_n8n_cloud_uses_provided_instance_but_is_disabled_until_configured():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "N8N_ENABLED=false" in env
    assert "abhijitdutta-pm-new.app.n8n.cloud/webhook/wellness-events" in env
    assert "n8n_enabled: bool = False" in config
    assert "Production requires the reviewed n8n Cloud notification integration" in config
    assert "if settings.n8n_enabled else """ in main


def test_demo_hash_embeddings_are_not_synced_to_pinecone():
    ai = (ROOT / "app/ai.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "def real_embedding_provider_configured()" in ai
    assert "not real_embedding_provider_configured()" in main



def test_main_imports_real_embedding_provider_guard():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "from app.ai import retrieve_knowledge, generate_buddy_response, embed_text, real_embedding_provider_configured" in main


def test_gpt6_chat_payload_uses_current_token_parameter_and_reasoning_settings():
    ai = (ROOT / "app/ai.py").read_text(encoding="utf-8")
    assert "max_completion_tokens" in ai
    assert 'request_payload["reasoning_effort"] = "low"' in ai
    assert 'request_payload["temperature"] = 0.35' in ai
    # The deprecated field must not appear in the model request payload.
    assert '"max_tokens"' not in ai


def test_reduced_personas_are_blocked_without_deleting_legacy_data():
    security = (ROOT / "app/security.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    models = (ROOT / "app/models.py").read_text(encoding="utf-8")
    assert "parent_login_enabled" not in security
    assert 'DISABLED_LOGIN_ROLES = {"parent", "school_admin", "safeguarding_lead", "content_reviewer"}' in security
    assert "ensure_login_role_enabled(user)" in security
    assert "ensure_login_role_enabled(user)" in main
    assert 'account["role_label"] != "Parent"' in main
    # Keep historical role values, guardian relationships, and consent history in the data model.
    assert 'role: Mapped[str]' in models
    assert 'class GuardianLink' in models
    assert 'class ConsentRecord' in models


def test_role_reduction_delegates_sensitive_operations_to_counsellor_only():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    services = (ROOT / "app/services.py").read_text(encoding="utf-8")
    ui = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'Depends(require_roles("counsellor"))' in main
    assert 'User.role == "counsellor"' in services
    assert 'safeguarding_lead:' not in ui
    assert 'school_admin:' not in ui
    assert 'content_reviewer:' not in ui
    assert 'const canReview = state.user.role === "counsellor"' in ui
