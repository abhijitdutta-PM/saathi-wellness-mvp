from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default="active")
    support_instructions: Mapped[str] = mapped_column(Text, default="Please contact a trusted adult or the school's designated support team. This application cannot guarantee an immediate human response.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
        Index("ix_users_tenant_role", "tenant_id", "role"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40), index=True)
    age_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    school_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentRegistrationInvite(Base):
    """Single-use invitation codes; only a SHA-256 digest is stored."""
    __tablename__ = "student_registration_invites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code_hash", name="uq_student_invite_tenant_hash"),
        Index("ix_student_invite_tenant_expiry", "tenant_id", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_session_tenant_user"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuardianLink(Base):
    __tablename__ = "guardian_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_user_id", "guardian_user_id", name="uq_guardian_student_link"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_guardian_student_tenant"),
        ForeignKeyConstraint(["tenant_id", "guardian_user_id"], ["users.tenant_id", "users.id"], name="fk_guardian_guardian_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    guardian_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    relationship_label: Mapped[str] = mapped_column(String(40), default="guardian")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        Index("ix_consent_latest", "tenant_id", "student_user_id", "purpose", "actor_type", "created_at"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_consent_student_tenant"),
        ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["users.tenant_id", "users.id"], name="fk_consent_actor_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(40))  # guardian / student_assent / adult_self
    purpose: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))  # granted / withdrawn / denied
    notice_version: Mapped[str] = mapped_column(String(40), default="mvp-v1")
    verification_method: Mapped[str] = mapped_column(String(80), default="demo-account-link")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(120), default="Reflection prompt")
    theme: Mapped[str] = mapped_column(String(80), default="reflection")
    age_band: Mapped[str] = mapped_column(String(20), default="all")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_student_created", "tenant_id", "student_user_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_journal_student_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180), default="My reflection")
    content: Mapped[str] = mapped_column(Text)
    share_with_support_team: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_student_created", "tenant_id", "student_user_id", "created_at"),
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_conversation_student_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180), default="Conversation with Saathi")
    channel: Mapped[str] = mapped_column(String(20), default="text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "tenant_id", "conversation_id", "created_at"),
        UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], name="fk_message_conversation_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(20))  # student / buddy / system
    channel: Mapped[str] = mapped_column(String(20), default="text")
    content: Mapped[str] = mapped_column(Text)
    safety_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_voice_student_tenant"),
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], name="fk_voice_conversation_tenant"),
        ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], name="fk_voice_message_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    transcript_status: Mapped[str] = mapped_column(String(30), default="persisted")
    audio_retained: Mapped[bool] = mapped_column(Boolean, default=False)
    transcription_provider: Mapped[str] = mapped_column(String(100), default="configured-stt")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (Index("ix_knowledge_tenant_approval", "tenant_id", "review_status", "published"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)  # NULL means platform-approved shared content
    title: Mapped[str] = mapped_column(String(220))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    age_band: Mapped[str] = mapped_column(String(20), default="all")
    source: Mapped[str] = mapped_column(String(240), default="Platform-authored resource")
    review_status: Mapped[str] = mapped_column(String(30), default="approved")
    reviewer: Mapped[str] = mapped_column(String(160), default="Clinical/content review required before production")
    content_version: Mapped[str] = mapped_column(String(40), default="1")
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    vector_sync_status: Mapped[str] = mapped_column(String(20), default="pending")
    vector_sync_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vector_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyAssessment(Base):
    __tablename__ = "safety_assessments"
    __table_args__ = (
        Index("ix_safety_student_created", "tenant_id", "student_user_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_safety_student_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(36))
    concern_category: Mapped[str] = mapped_column(String(40))
    urgency: Mapped[str] = mapped_column(String(30))
    evidence_terms: Mapped[list] = mapped_column(JSON, default=list)
    reason_summary: Mapped[str] = mapped_column(String(500))
    rule_version: Mapped[str] = mapped_column(String(40), default="keyword-rules-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportCase(Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        Index("ix_case_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_case_assignee", "tenant_id", "assigned_to_user_id", "status"),
        UniqueConstraint("tenant_id", "id", name="uq_cases_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "student_user_id"], ["users.tenant_id", "users.id"], name="fk_case_student_tenant"),
        ForeignKeyConstraint(["tenant_id", "assigned_to_user_id"], ["users.tenant_id", "users.id"], name="fk_case_assignee_tenant"),
        ForeignKeyConstraint(["tenant_id", "created_by_user_id"], ["users.tenant_id", "users.id"], name="fk_case_creator_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    student_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    urgency: Mapped[str] = mapped_column(String(30), index=True)
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(220))
    summary: Mapped[str] = mapped_column(String(700))
    evidence_excerpt: Mapped[str] = mapped_column(String(700), default="")
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CaseAction(Base):
    __tablename__ = "case_actions"
    __table_args__ = (
        Index("ix_case_actions_due", "tenant_id", "status", "due_at"),
        ForeignKeyConstraint(["tenant_id", "case_id"], ["support_cases.tenant_id", "support_cases.id"], name="fk_case_action_case_tenant"),
        ForeignKeyConstraint(["tenant_id", "assigned_to_user_id"], ["users.tenant_id", "users.id"], name="fk_case_action_assignee_tenant"),
        ForeignKeyConstraint(["tenant_id", "created_by_user_id"], ["users.tenant_id", "users.id"], name="fk_case_action_creator_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("support_cases.id"), index=True)
    assigned_to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseActionProgress(Base):
    __tablename__ = "case_action_progress"
    __table_args__ = (
        Index("ix_action_progress_tenant_action_created", "tenant_id", "action_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "author_user_id"], ["users.tenant_id", "users.id"], name="fk_action_progress_author_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("case_actions.id"), index=True)
    author_user_id: Mapped[str] = mapped_column(String(36), index=True)
    work_performed: Mapped[str] = mapped_column(String(2000))
    outcome: Mapped[str] = mapped_column(String(1000), default="")
    further_concerns: Mapped[str] = mapped_column(String(1000), default="")
    next_step: Mapped[str] = mapped_column(String(1000), default="")
    submitted_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["users.tenant_id", "users.id"], name="fk_audit_actor_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    purpose: Mapped[str] = mapped_column(String(120), default="application_operation")
    outcome: Mapped[str] = mapped_column(String(30), default="success")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending", "tenant_id", "status", "next_attempt_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "data_category", name="uq_retention_tenant_category"),
        ForeignKeyConstraint(["tenant_id", "approved_by_user_id"], ["users.tenant_id", "users.id"], name="fk_retention_approver_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    data_category: Mapped[str] = mapped_column(String(60))
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_for_live_data: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(40), default="mvp-v1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RetentionHold(Base):
    __tablename__ = "retention_holds"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "created_by_user_id"], ["users.tenant_id", "users.id"], name="fk_hold_creator_tenant"),
        ForeignKeyConstraint(["tenant_id", "released_by_user_id"], ["users.tenant_id", "users.id"], name="fk_hold_releaser_tenant"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(60), index=True)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    released_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
