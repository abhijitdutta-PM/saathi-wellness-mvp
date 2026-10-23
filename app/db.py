import logging
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError
from app.config import settings
from app.models import Base

logger = logging.getLogger("saathi.db")
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

TENANT_TABLES = [
    "users", "user_sessions", "student_registration_invites", "guardian_links", "consent_records", "journal_entries",
    "conversations", "messages", "voice_sessions", "safety_assessments", "support_cases",
    "case_actions", "case_action_progress", "audit_events", "outbox_events", "retention_policies", "retention_holds"
]
GLOBAL_OR_TENANT_TABLES = ["quotes", "knowledge_items"]


def _restore_tenant_context_on_transaction(session: Session, transaction, connection) -> None:
    """Apply the authenticated tenant to every new transaction on this Session.

    SQLAlchemy may return a connection to the pool after commit and check out a
    different connection for the next transaction. A session-level PostgreSQL
    setting therefore cannot be relied on to survive commits. Transaction-local
    context is re-applied here for each transaction instead.
    """
    tenant_id = session.info.get("tenant_id")
    if tenant_id:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )


event.listen(Session, "after_begin", _restore_tenant_context_on_transaction)


def set_tenant_context(db: Session, tenant_id: str) -> None:
    """Set tenant context now and remember it for later transactions in this Session."""
    db.info["tenant_id"] = str(tenant_id)
    # `true` scopes the setting to this transaction; the after_begin listener
    # reapplies it after every commit/rollback before the next transaction runs.
    db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})


def apply_rls() -> None:
    """Force RLS even for the table owner; the app DB role is not a superuser/BYPASSRLS role."""
    with engine.begin() as conn:
        for table in TENANT_TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
            conn.execute(text(
                f'CREATE POLICY tenant_isolation ON "{table}" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text)"
            ))
        for table in GLOBAL_OR_TENANT_TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation_or_shared ON "{table}"'))
            conn.execute(text(f'DROP POLICY IF EXISTS shared_content_read ON "{table}"'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_owned_access ON "{table}"'))
            # All tenants may read platform-shared rows, but application writes must be tenant-owned.
            # This prevents tenant-scoped API paths from creating or mutating global shared resources.
            conn.execute(text(
                f'CREATE POLICY shared_content_read ON "{table}" FOR SELECT '
                "USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text)"
            ))
            conn.execute(text(
                f'CREATE POLICY tenant_owned_access ON "{table}" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text)"
            ))


def init_schema(retries: int = 30) -> None:
    for attempt in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            Base.metadata.create_all(bind=engine)
            # Migration from the previous MVP build: vectors now live in Pinecone.
            # Remove the obsolete embedding column from previous local builds.
            with engine.begin() as migration_conn:
                # Student profile enhancement: standard/grade/section is optional for existing records.
                migration_conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS school_class VARCHAR(40) NULL"))
                migration_conn.execute(text("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS vector_sync_status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
                migration_conn.execute(text("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS vector_sync_attempted_at TIMESTAMPTZ NULL"))
                migration_conn.execute(text("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS vector_synced_at TIMESTAMPTZ NULL"))
                migration_conn.execute(text("ALTER TABLE knowledge_items DROP COLUMN IF EXISTS embedding"))
            return
        except OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(2)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        # A failed request may leave a transaction aborted. Roll it back before resetting the
        # session-level tenant context, or a pooled connection could keep the previous tenant.
        try:
            db.rollback()
            # This Session is request-scoped. Remove the remembered tenant before
            # touching a pooled connection during cleanup.
            db.info.pop("tenant_id", None)
            db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
            db.commit()
        except Exception:
            db.rollback()
        db.close()
