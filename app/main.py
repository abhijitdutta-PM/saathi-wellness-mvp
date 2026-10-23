from __future__ import annotations
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from uuid import uuid5, NAMESPACE_URL
from pathlib import Path
from collections import defaultdict, deque
from contextlib import suppress
import json
import logging
import os
import re
import threading
import time
import secrets
import hashlib
import hmac

import requests
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, desc, func, and_, or_, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings, validate_settings
from app.db import init_schema, apply_rls, get_db, set_tenant_context, SessionLocal, engine
from app.models import (Tenant, User, UserSession, GuardianLink, ConsentRecord, Quote, JournalEntry,
                        Conversation, Message, VoiceSession, KnowledgeItem, SafetyAssessment,
                        SupportCase, CaseAction, CaseActionProgress, AuditEvent, OutboxEvent, RetentionPolicy, RetentionHold, StudentRegistrationInvite)
from app.security import (hash_password, verify_password, create_session_token, decode_session_token,
                          set_session_cookie, clear_session_cookie, get_current_user, require_roles, ensure_login_role_enabled,
                          check_same_origin, COOKIE_NAME, new_id)
from app.services import (seed_demo_data, consent_summary, latest_consent, has_consent, has_core_consent,
                          require_core_consent, write_audit, enqueue_event, create_safety_record_and_case,
                          build_notification_payload, REQUIRED_PURPOSES)
from app.safety import assess_text, urgent_support_message, safe_buddy_fallback
from app.ai import retrieve_knowledge, generate_buddy_response, embed_text, real_embedding_provider_configured
from app.vector_store import upsert_knowledge_vector, configured as pinecone_configured

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("saathi.api")
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title=settings.app_name, version="0.1.0", docs_url="/api/docs" if not settings.is_production else None,
              redoc_url=None, openapi_url="/api/openapi.json" if not settings.is_production else None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

login_attempts: dict[str, deque[float]] = defaultdict(deque)
login_attempts_lock = threading.Lock()
registration_attempts: dict[str, deque[float]] = defaultdict(deque)
registration_attempts_lock = threading.Lock()
stop_worker = threading.Event()
worker_thread: threading.Thread | None = None
last_n8n_health_ping = 0.0


@app.middleware("http")
async def security_headers(request: Request, call_next):
    try:
        check_same_origin(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    # Swagger UI uses FastAPI's CDN-hosted assets and an inline initialization script.
    # Permit those resources only for the development docs endpoints; keep the
    # normal restrictive policy for the rest of the app and all production requests.
    is_development_docs = (
        not settings.is_production
        and request.url.path in {"/api/docs", "/docs/oauth2-redirect"}
    )
    if is_development_docs:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self'; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class StudentRegistrationInput(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")
    invitation_code: str = Field(min_length=20, max_length=120)
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=200)
    age_band: str = Field(pattern=r"^(6-10|11-14|15-17|18\+)$")
    school_class: str | None = Field(default=None, max_length=40)

class LoginInput(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)

class JournalInput(BaseModel):
    title: str = Field(default="My reflection", max_length=180)
    content: str = Field(min_length=1, max_length=20000)
    request_support: bool = False

class ConversationInput(BaseModel):
    title: str = Field(default="Conversation with Saathi", max_length=180)
    channel: str = Field(default="text", pattern="^(text|voice)$")

class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=6000)
    channel: str = Field(default="text", pattern="^(text|voice)$")

class ConsentInput(BaseModel):
    student_id: str | None = None
    purposes: list[str] = Field(min_length=1, max_length=4)
    status: str = Field(pattern="^(granted|withdrawn|denied)$")

class ConsentReviewInput(BaseModel):
    student_id: str
    purposes: list[str] = Field(min_length=1, max_length=3)

class CaseUpdateInput(BaseModel):
    status: str = Field(pattern="^(open|in_review|closed)$")
    resolution_note: str | None = Field(default=None, max_length=1000)

class CaseAssignmentInput(BaseModel):
    assigned_to_user_id: str | None = None

class StudentProfileInput(BaseModel):
    school_class: str | None = Field(default=None, max_length=40)

class CaseActionInput(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    notes: str = Field(default="", max_length=1000)
    assigned_to_user_id: str | None = None
    due_at: datetime | None = None

class ActionUpdateInput(BaseModel):
    status: str = Field(pattern="^(open|in_progress|submitted_for_review|changes_requested|completed|cancelled)$")

class ActionProgressInput(BaseModel):
    work_performed: str = Field(min_length=3, max_length=2000)
    outcome: str = Field(default="", max_length=1000)
    further_concerns: str = Field(default="", max_length=1000)
    next_step: str = Field(default="", max_length=1000)
    submit_for_review: bool = False

class ActionReviewInput(BaseModel):
    decision: str = Field(pattern="^(approve|request_changes|reopen)$")
    review_note: str = Field(default="", max_length=1000)

class KnowledgeInput(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    content: str = Field(min_length=20, max_length=12000)
    category: str = Field(min_length=2, max_length=80)
    age_band: str = Field(default="all", pattern=r"^(all|6-10|11-14|15-17|18\+)$")
    source: str = Field(min_length=3, max_length=240)
    reviewer_attestation: bool = False

class RetentionPolicyInput(BaseModel):
    retention_days: int = Field(ge=30, le=3650)
    active: bool = False
    approved_for_live_data: bool = False

class RetentionRunInput(BaseModel):
    dry_run: bool = True


def rate_limit_login(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with login_attempts_lock:
        q = login_attempts[ip]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= 12:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please try again later.")
        q.append(now)


def rate_limit_registration(request: Request) -> None:
    """Allow ordinary student retries while retaining a per-process abuse guard.

    Permit up to 20 registration submissions per client IP in a rolling 15-minute
    window. Production deployments should also enforce limits at the reverse proxy.
    """
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with registration_attempts_lock:
        q = registration_attempts[ip]
        while q and q[0] < now - 900:
            q.popleft()
        if len(q) >= 20:
            raise HTTPException(status_code=429, detail="Too many registration attempts. Please wait a little and try again.")
        q.append(now)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def current_tenant(db: Session, user: User) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == user.tenant_id, Tenant.status == "active"))
    if not tenant:
        raise HTTPException(status_code=403, detail="This school account is not active.")
    return tenant


def audit_and_commit(db: Session, user: User, action: str, resource_type: str, resource_id: str | None = None,
                     purpose: str = "application_operation", metadata: dict | None = None) -> None:
    write_audit(db, user.tenant_id, user.id, action, resource_type, resource_id, purpose=purpose, metadata=metadata)
    db.commit()


def student_only(user: User) -> None:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="This action is available to students only.")


def can_read_case(db: Session, user: User, case: SupportCase) -> bool:
    if case.tenant_id != user.tenant_id:
        return False
    if user.role == "counsellor":
        return True
    if user.role == "teacher" and case.assigned_to_user_id == user.id:
        return True
    return False


def serialize_case(db: Session, user: User, case: SupportCase, detailed: bool = False) -> dict:
    student = db.scalar(select(User).where(User.id == case.student_user_id, User.tenant_id == user.tenant_id))
    assignee = db.scalar(select(User).where(User.id == case.assigned_to_user_id, User.tenant_id == user.tenant_id)) if case.assigned_to_user_id else None
    privileged = user.role == "counsellor"
    out = {
        "id": case.id, "urgency": case.urgency, "category": case.category, "title": case.title,
        "summary": case.summary, "status": case.status, "assigned_to": assignee.display_name if assignee else "Unassigned",
        "assigned_to_user_id": case.assigned_to_user_id,
        "created_at": iso(case.created_at), "updated_at": iso(case.updated_at), "acknowledged_at": iso(case.acknowledged_at),
        # Student identity is shown only inside a case the current staff member may read.
        "student_id": student.id if student else None,
        "student_display": student.display_name if student else "Student",
        "student_school_class": student.school_class if student else None,
    }
    if detailed:
        if privileged:
            out["evidence_excerpt"] = case.evidence_excerpt
            out["resolution_note"] = case.resolution_note
            actions = db.scalars(select(CaseAction).where(
                CaseAction.tenant_id == user.tenant_id, CaseAction.case_id == case.id
            ).order_by(desc(CaseAction.created_at))).all()
        elif user.role == "teacher":
            # Teachers see only follow-up actions explicitly assigned to them.
            actions = db.scalars(select(CaseAction).where(
                CaseAction.tenant_id == user.tenant_id, CaseAction.case_id == case.id,
                CaseAction.assigned_to_user_id == user.id
            ).order_by(desc(CaseAction.created_at))).all()
        else:
            actions = []
        serialized_actions = []
        for a in actions:
            progress_rows = db.scalars(select(CaseActionProgress).where(
                CaseActionProgress.tenant_id == user.tenant_id,
                CaseActionProgress.action_id == a.id
            ).order_by(CaseActionProgress.created_at.desc())).all()
            serialized_actions.append({
                "id": a.id, "title": a.title, "notes": a.notes, "status": a.status,
                "due_at": iso(a.due_at), "assigned_to_user_id": a.assigned_to_user_id,
                "created_at": iso(a.created_at), "completed_at": iso(a.completed_at),
                "progress_history": [{
                    "id": p.id, "author_user_id": p.author_user_id,
                    "author_name": (db.scalar(select(User.display_name).where(User.id == p.author_user_id, User.tenant_id == user.tenant_id)) or "Staff member"),
                    "work_performed": p.work_performed, "outcome": p.outcome,
                    "further_concerns": p.further_concerns, "next_step": p.next_step,
                    "submitted_for_review": p.submitted_for_review, "created_at": iso(p.created_at)
                } for p in progress_rows]
            })
        out["actions"] = serialized_actions
    return out


def recent_distress_count(db: Session, student_id: str, tenant_id: str) -> int:
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    return int(db.scalar(select(func.count(SafetyAssessment.id)).where(
        SafetyAssessment.tenant_id == tenant_id,
        SafetyAssessment.student_user_id == student_id,
        SafetyAssessment.concern_category == "emotional_distress",
        SafetyAssessment.created_at >= seven_days_ago,
    )) or 0)


def get_student_conversation(db: Session, user: User, conversation_id: str) -> Conversation:
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id,
        Conversation.student_user_id == user.id,
    ))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


def create_case_from_text(db: Session, user: User, source_type: str, source_id: str, text_value: str,
                          request_support: bool = False) -> tuple[object, SupportCase | None, bool]:
    count_recent = recent_distress_count(db, user.id, user.tenant_id)
    assessment = assess_text(text_value, recent_distress_count=count_recent)
    if request_support and not assessment.create_case:
        from app.safety import Assessment
        assessment = Assessment("human_review", "student_requested_support", [],
                                "The student explicitly requested a human support check-in.", True)
    return create_safety_record_and_case(db, user, assessment, source_type, source_id, text_value, created_by_user_id=user.id)


def enqueue_case_notification(db: Session, tenant_id: str, case_id: str, event_type: str,
                              urgency: str, category: str, recipient_email: str | None) -> None:
    enqueue_event(db, tenant_id, event_type, case_id, {
        "case_id": case_id, "urgency": urgency, "category": category,
        "recipient_email": recipient_email, "dashboard_path": "/?view=cases",
    })


def require_internal_secret(request: Request) -> None:
    supplied = request.headers.get("x-wellness-internal-key", "")
    expected = settings.internal_api_secret
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service authentication.")


def queue_daily_report_event(tenant_id: str, report_day: date) -> None:
    """Create one aggregate-only report event per tenant/day; no local API must be public."""
    if not settings.n8n_enabled or not settings.n8n_report_webhook_url:
        return
    now = datetime.now(timezone.utc)
    event_id = str(uuid5(NAMESPACE_URL, f"saathi-daily-report:{tenant_id}:{report_day.isoformat()}"))
    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        if db.get(OutboxEvent, event_id) is not None:
            db.rollback()
            return
        recipient = db.scalar(select(User).where(
            User.tenant_id == tenant_id, User.role == "counsellor", User.active.is_(True),
            User.email.is_not(None)).order_by(User.created_at).limit(1))
        if not recipient:
            logger.warning("Daily report not queued; tenant has no authorized report recipient: %s", tenant_id)
            db.rollback()
            return
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        open_cases = int(db.scalar(select(func.count(SupportCase.id)).where(
            SupportCase.tenant_id == tenant_id, SupportCase.status.in_(["open", "in_review"]))) or 0)
        immediate_cases = int(db.scalar(select(func.count(SupportCase.id)).where(
            SupportCase.tenant_id == tenant_id, SupportCase.urgency == "immediate",
            SupportCase.status.in_(["open", "in_review"]))) or 0)
        overdue_followups = int(db.scalar(select(func.count(CaseAction.id)).where(
            CaseAction.tenant_id == tenant_id, CaseAction.status == "open",
            CaseAction.due_at.is_not(None), CaseAction.due_at < now)) or 0)
        active_students = int(db.scalar(select(func.count(User.id)).where(
            User.tenant_id == tenant_id, User.role == "student", User.active.is_(True))) or 0)
        db.add(OutboxEvent(
            id=event_id, tenant_id=tenant_id, event_type="report.daily", resource_id=tenant_id,
            payload={
                "tenant_slug": tenant.slug if tenant else "school",
                "recipient_email": recipient.email,
                "active_students": active_students,
                "open_cases": open_cases,
                "immediate_cases": immediate_cases,
                "overdue_followups": overdue_followups,
                "generated_at": iso(now),
                "contains_student_content": False,
            }, status="pending", attempts=0, next_attempt_at=now,
        ))
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Unable to queue daily aggregate report for tenant %s", tenant_id)


def sync_pending_knowledge(db: Session, tenant_id: str) -> None:
    """Retry tenant-owned knowledge vectors inside the tenant's database scope."""
    if not pinecone_configured() or not real_embedding_provider_configured():
        return
    now = datetime.now(timezone.utc)
    items = db.scalars(select(KnowledgeItem).where(
        KnowledgeItem.tenant_id == tenant_id,
        KnowledgeItem.published.is_(True), KnowledgeItem.review_status == "approved",
        or_(KnowledgeItem.vector_sync_status == "pending",
            and_(KnowledgeItem.vector_sync_status == "failed",
                 or_(KnowledgeItem.vector_sync_attempted_at.is_(None),
                     KnowledgeItem.vector_sync_attempted_at < now - timedelta(minutes=5))))
    ).limit(10)).all()
    if not items:
        return
    for item in items:
        item.vector_sync_attempted_at = now
        try:
            upsert_knowledge_vector(item, embed_text(item.title + "\n" + item.content))
            item.vector_sync_status = "synced"
            item.vector_synced_at = datetime.now(timezone.utc)
        except Exception:
            item.vector_sync_status = "failed"
            logger.exception("Pinecone sync failed for approved knowledge item %s", item.id)
    db.commit()


def sync_global_knowledge() -> None:
    """Synchronize reviewed shared resources on startup; shared rows are read-only to tenants."""
    if not pinecone_configured() or not real_embedding_provider_configured():
        if pinecone_configured():
            logger.info("Pinecone configured but no real embedding provider is configured; skipping sync to avoid indexing demo hash vectors")
        return
    with SessionLocal() as db:
        rows = db.scalars(select(KnowledgeItem).where(
            KnowledgeItem.tenant_id.is_(None), KnowledgeItem.published.is_(True),
            KnowledgeItem.review_status == "approved")).all()
        for item in rows:
            try:
                upsert_knowledge_vector(item, embed_text(item.title + "\n" + item.content))
            except Exception:
                logger.exception("Pinecone sync failed for shared knowledge item %s", item.id)


def send_n8n_health_ping() -> None:
    """Optional outbound heartbeat; n8n Cloud never needs to call localhost."""
    global last_n8n_health_ping
    if not settings.n8n_enabled or not settings.n8n_health_webhook_url or time.monotonic() - last_n8n_health_ping < 600:
        return
    last_n8n_health_ping = time.monotonic()
    try:
        response = requests.post(settings.n8n_health_webhook_url,
            json={"event_type": "backend.health_ping", "status": "ok", "sent_at": iso(datetime.now(timezone.utc)),
                  "environment": settings.app_env},
            headers={"X-Wellness-Workflow-Key": settings.n8n_webhook_secret, "Content-Type": "application/json"},
            timeout=8)
        response.raise_for_status()
    except Exception:
        logger.exception("Optional n8n Cloud health ping failed")


def outbox_loop() -> None:
    logger.info("Outbox dispatcher started; n8n Cloud enabled=%s", settings.n8n_enabled)
    while not stop_worker.wait(max(5, settings.n8n_dispatch_interval_seconds)):
        try:
            with SessionLocal() as list_db:
                tenant_ids = [row[0] for row in list_db.execute(select(Tenant.id).where(Tenant.status == "active")).all()]
            local_now = datetime.now(ZoneInfo(settings.app_timezone))
            if local_now.hour == 8 and settings.n8n_report_webhook_url:
                for report_tenant_id in tenant_ids:
                    queue_daily_report_event(report_tenant_id, local_now.date())
            for tenant_id in tenant_ids:
                if stop_worker.is_set():
                    break
                db = SessionLocal()
                try:
                    set_tenant_context(db, tenant_id)
                    sync_pending_knowledge(db, tenant_id)
                    now = datetime.now(timezone.utc)
                    due_actions = db.scalars(select(CaseAction).where(
                        CaseAction.tenant_id == tenant_id, CaseAction.status == "open",
                        CaseAction.reminder_sent_at.is_(None), CaseAction.due_at.is_not(None),
                        CaseAction.due_at <= now + timedelta(hours=24), CaseAction.due_at >= now - timedelta(days=1),
                    ).limit(20)).all()
                    for action in due_actions:
                        assignee = db.scalar(select(User).where(User.id == action.assigned_to_user_id,
                            User.tenant_id == tenant_id, User.active.is_(True))) if action.assigned_to_user_id else None
                        action.reminder_sent_at = now
                        payload = build_notification_payload(db, tenant_id, action.id, "followup.due",
                            preferred_user_id=assignee.id if assignee else None,
                            extra={"action_id": action.id, "case_id": action.case_id})
                        enqueue_event(db, tenant_id, "followup.due", action.id, payload)
                    db.commit()
                    events = db.scalars(select(OutboxEvent).where(
                        OutboxEvent.tenant_id == tenant_id,
                        OutboxEvent.status == "pending",
                        OutboxEvent.next_attempt_at <= datetime.now(timezone.utc),
                    ).order_by(OutboxEvent.created_at).limit(25)).all()
                    for event in events:
                        target_url = (settings.n8n_report_webhook_url if event.event_type == "report.daily" else settings.n8n_webhook_url) if settings.n8n_enabled else ""
                        if not target_url:
                            # Keep pending until the corresponding production webhook is configured.
                            continue
                        payload = {
                            "event_id": event.id, "tenant_id": tenant_id,
                            "event_type": event.event_type, "resource_id": event.resource_id,
                            "payload": event.payload, "created_at": iso(event.created_at),
                        }
                        try:
                            resp = requests.post(target_url, json=payload,
                                headers={"X-Wellness-Workflow-Key": settings.n8n_webhook_secret,
                                         "Content-Type": "application/json"}, timeout=20)
                            if 200 <= resp.status_code < 300:
                                event.status = "delivered"; event.delivered_at = datetime.now(timezone.utc); event.last_error = None
                            else:
                                raise RuntimeError(f"n8n Cloud returned HTTP {resp.status_code}")
                        except Exception as exc:
                            event.attempts += 1
                            event.last_error = str(exc)[:480]
                            if event.attempts >= 12:
                                event.status = "dead_letter"
                                write_audit(db, tenant_id, None, "outbox_dead_letter", "outbox_event", event.id,
                                            purpose="workflow_delivery", outcome="failure", metadata={"event_type": event.event_type})
                            else:
                                event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 15 * (2 ** min(event.attempts, 7))))
                        db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Outbox worker failed for tenant id %s", tenant_id)
                finally:
                    with suppress(Exception):
                        from sqlalchemy import text
                        db.execute(text("SELECT set_config('app.tenant_id', '', false)")); db.commit()
                    db.close()
            send_n8n_health_ping()
        except Exception:
            logger.exception("Outbox dispatcher iteration failed")

@app.on_event("startup")
def startup_event():
    global worker_thread
    validate_settings()
    init_schema()
    if settings.seed_demo_data and not settings.is_production:
        with SessionLocal() as db:
            seed_demo_data(db)
    apply_rls()
    # Shared approved content is indexed into Pinecone; student conversations never are.
    try:
        sync_global_knowledge()
    except Exception:
        logger.exception("Shared Pinecone knowledge synchronization failed")
    stop_worker.clear()
    worker_thread = threading.Thread(target=outbox_loop, name="saathi-outbox", daemon=True)
    worker_thread.start()


@app.on_event("shutdown")
def shutdown_event():
    stop_worker.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=3)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/healthz")
def healthz():
    return {"status": "ok", "environment": settings.app_env}

@app.get("/api/system/status")
def system_status():
    return {
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "demo_mode": settings.app_env != "production" and not (settings.ai_api_base_url and settings.ai_api_key and settings.ai_model),
        "demo_accounts_available": settings.app_env.lower() != "production" and settings.seed_demo_data,
        "ai_mode": "configured_provider" if settings.ai_api_base_url and settings.ai_api_key and settings.ai_model else "local_demo_fallback",
        "embedding_mode": "configured_provider" if settings.embedding_api_base_url and settings.embedding_model else "local_demo_hashing",
        "vector_store": "pinecone" if pinecone_configured() else "local_relational_demo_fallback",
        "pinecone_query_vectors_enabled": settings.pinecone_query_vectors_enabled,
        "voice_enabled": settings.voice_enabled,
        "voice_configured": bool(settings.voice_enabled and settings.stt_api_base_url and settings.stt_model),
        "n8n_configured": bool(settings.n8n_enabled and settings.n8n_webhook_url),
        "notice": "Demonstration mode uses synthetic accounts, local fallback responses, and unvalidated keyword triage. It is not a live monitored service.",
    }

@app.get("/api/system/demo-accounts")
def demo_accounts():
    """Expose synthetic convenience accounts only on a non-production seeded instance."""
    if settings.app_env.lower() == "production" or not settings.seed_demo_data:
        raise HTTPException(status_code=404, detail="Demo accounts are not available.")
    accounts = [
        {"tenant_slug": "demo-school", "role_label": "Student", "email": "student@demo.school", "password": "DemoStudent-2026!"},
        {"tenant_slug": "demo-school", "role_label": "Parent", "email": "parent@demo.school", "password": "DemoParent-2026!"},
        {"tenant_slug": "demo-school", "role_label": "Teacher", "email": "teacher@demo.school", "password": "DemoTeacher-2026!"},
        {"tenant_slug": "demo-school", "role_label": "Counsellor", "email": "counsellor@demo.school", "password": "DemoCounsellor-2026!"},
        {"tenant_slug": "sample-academy", "role_label": "Student (second school)", "email": "student@sample.academy", "password": "DemoStudent-2026!"},
        {"tenant_slug": "sample-academy", "role_label": "Counsellor (second school)", "email": "counsellor@sample.academy", "password": "DemoCounsellor-2026!"},
    ]
    # Only supported human personas are advertised. Legacy role rows remain in storage.
    accounts = [account for account in accounts if account["role_label"] != "Parent"]
    return accounts


@app.post("/api/auth/student/register", status_code=201)
def register_student(payload: StudentRegistrationInput, request: Request, db: Session = Depends(get_db)):
    """Self-registration only. A single-use invitation proves access to a school-issued invite."""
    rate_limit_registration(request)
    tenant = db.scalar(select(Tenant).where(
        Tenant.slug == payload.tenant_slug.strip().lower(), Tenant.status == "active"
    ))
    # Keep tenant/invite failures generic to reduce school-code and invitation enumeration.
    if not tenant:
        raise HTTPException(status_code=400, detail="Registration details could not be verified. Check the school code and invitation, or contact your school.")
    set_tenant_context(db, tenant.id)
    email = str(payload.email).strip().lower()
    code_hash = hashlib.sha256(payload.invitation_code.strip().encode("utf-8")).hexdigest()
    invite = db.scalar(select(StudentRegistrationInvite).where(
        StudentRegistrationInvite.tenant_id == tenant.id,
        StudentRegistrationInvite.code_hash == code_hash,
        StudentRegistrationInvite.redeemed_at.is_(None),
    ).with_for_update())
    now = datetime.now(timezone.utc)
    expiry = invite.expires_at if invite else None
    if not invite or not hmac.compare_digest(invite.code_hash, code_hash) or not expiry or expiry <= now:
        raise HTTPException(status_code=400, detail="Registration details could not be verified. Check the school code and invitation, or contact your school.")
    if db.scalar(select(User.id).where(User.tenant_id == tenant.id, User.email == email)):
        raise HTTPException(status_code=409, detail="An account with these details may already exist. Try signing in or use account recovery.")
    student = User(
        id=new_id(), tenant_id=tenant.id, email=email,
        display_name=payload.display_name.strip(), role="student",
        age_band=payload.age_band, school_class=(payload.school_class.strip() or None) if payload.school_class else None,
        password_hash=hash_password(payload.password), active=True,
    )
    invite.redeemed_at = now
    db.add(student)
    try:
        # Flush the student first so the audit event's actor foreign key is valid
        # before the audit row is written. Both writes and invite redemption still
        # remain in one transaction; any later failure rolls everything back.
        db.flush()
        write_audit(db, tenant.id, student.id, "student_self_registered", "student_account", student.id,
                    purpose="authentication", metadata={"invitation_id": invite.id})
        db.commit()
    except IntegrityError:
        db.rollback()
        # Do not expose database internals to the public registration endpoint.
        # Keep the specific cause in server logs for operator diagnosis.
        logger.exception("Student registration integrity failure; tenant_id=%s", tenant.id)
        raise HTTPException(
            status_code=409,
            detail="Registration conflicts with an existing account or database constraint. If you already registered, try signing in; otherwise contact your school administrator."
        )
    except Exception:
        db.rollback()
        logger.exception("Student registration persistence failure; tenant_id=%s", tenant.id)
        raise HTTPException(
            status_code=500,
            detail="Registration could not be saved because of a server error. Please try again later or contact your school administrator."
        )
    return {"ok": True, "message": "Your student account has been created. You can now sign in. Registration does not create a wellbeing case; wellbeing features remain subject to Saathi's consent requirements."}


@app.post("/api/auth/login")
def login(payload: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit_login(request)
    tenant = db.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug.strip().lower(), Tenant.status == "active"))
    if not tenant:
        logger.warning("Sign-in failed: unknown tenant; request_id=%s", request.headers.get("x-request-id", "n/a"))
        raise HTTPException(status_code=401, detail="School code, email, or password is incorrect.")
    set_tenant_context(db, tenant.id)
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == str(payload.email).lower(), User.active.is_(True)))
    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning("Sign-in failed: invalid credentials; tenant_id=%s", tenant.id)
        raise HTTPException(status_code=401, detail="School code, email, or password is incorrect.")
    ensure_login_role_enabled(user)
    session_id = new_id()
    db.add(UserSession(id=session_id, tenant_id=tenant.id, user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=8)))
    write_audit(db, tenant.id, user.id, "login_success", "session", session_id, purpose="authentication")
    db.commit()
    set_session_cookie(response, create_session_token(user, session_id))
    return {"ok": True, "user": {"id": user.id, "display_name": user.display_name, "role": user.role}, "tenant": tenant.slug}

@app.post("/api/auth/logout")
def logout(response: Response, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    claims = decode_session_token(token) if token else {}
    sid = claims.get("sid")
    if sid:
        session_row = db.scalar(select(UserSession).where(UserSession.id == sid, UserSession.tenant_id == user.tenant_id))
        if session_row:
            session_row.revoked_at = datetime.now(timezone.utc)
    write_audit(db, user.tenant_id, user.id, "logout", "session", str(sid or ""), purpose="authentication")
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}

@app.get("/api/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = current_tenant(db, user)
    summary = consent_summary(db, user) if user.role == "student" else None
    return {
        "id": user.id, "display_name": user.display_name, "email": user.email, "role": user.role,
        "age_band": user.age_band, "tenant_id": user.tenant_id, "tenant_name": tenant.name, "tenant_slug": tenant.slug,
        "support_instructions": tenant.support_instructions,
        "consent": summary,
        "can_use_wellbeing": bool(user.role == "student" and has_core_consent(db, user)),
        "demo_mode": settings.app_env != "production" and settings.seed_demo_data,
    }

@app.get("/api/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = current_tenant(db, user)
    today = date.today().toordinal()
    quotes = db.scalars(select(Quote).where(Quote.active.is_(True), or_(Quote.tenant_id.is_(None), Quote.tenant_id == user.tenant_id)).order_by(Quote.id)).all()
    quote = quotes[today % len(quotes)] if quotes else None
    if user.role == "student":
        return {
            "quote": {"text": quote.text, "author": quote.author, "theme": quote.theme} if quote else None,
            "journal_count": int(db.scalar(select(func.count(JournalEntry.id)).where(JournalEntry.tenant_id == user.tenant_id, JournalEntry.student_user_id == user.id)) or 0),
            "conversation_count": int(db.scalar(select(func.count(Conversation.id)).where(Conversation.tenant_id == user.tenant_id, Conversation.student_user_id == user.id)) or 0),
            "open_support_requests": int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.student_user_id == user.id, SupportCase.status.in_(["open", "in_review"]))) or 0),
            "demo_mode": settings.app_env != "production" and settings.seed_demo_data,
        }
    if user.role == "counsellor":
        total_open = db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.status.in_(["open", "in_review"]))) or 0
        immediate = db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.urgency == "immediate", SupportCase.status.in_(["open", "in_review"]))) or 0
        unassigned = db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.assigned_to_user_id.is_(None), SupportCase.status.in_(["open", "in_review"]))) or 0
        return {"open_cases": int(total_open), "immediate_cases": int(immediate), "unassigned_cases": int(unassigned), "n8n_configured": bool(settings.n8n_enabled and settings.n8n_webhook_url), "demo_mode": settings.app_env != "production" and settings.seed_demo_data}
    if user.role == "teacher":
        assigned = db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.assigned_to_user_id == user.id, SupportCase.status.in_(["open", "in_review"]))) or 0
        return {"assigned_cases": int(assigned), "demo_mode": settings.app_env != "production" and settings.seed_demo_data}
    return {"demo_mode": settings.app_env != "production" and settings.seed_demo_data}

@app.get("/api/quotes/today")
def quote_today(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    quotes = db.scalars(select(Quote).where(Quote.active.is_(True), or_(Quote.tenant_id.is_(None), Quote.tenant_id == user.tenant_id)).order_by(Quote.id)).all()
    if not quotes:
        raise HTTPException(status_code=404, detail="No quote is configured.")
    quote = quotes[date.today().toordinal() % len(quotes)]
    return {"id": quote.id, "text": quote.text, "author": quote.author, "theme": quote.theme}

@app.get("/api/journals")
def list_journals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    rows = db.scalars(select(JournalEntry).where(JournalEntry.tenant_id == user.tenant_id, JournalEntry.student_user_id == user.id).order_by(desc(JournalEntry.created_at)).limit(50)).all()
    return [{"id": r.id, "title": r.title, "content": r.content, "request_support": r.share_with_support_team, "created_at": iso(r.created_at)} for r in rows]

@app.post("/api/journals")
def create_journal(payload: JournalInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    row = JournalEntry(id=new_id(), tenant_id=user.tenant_id, student_user_id=user.id, title=payload.title.strip() or "My reflection",
                       content=payload.content.strip(), share_with_support_team=payload.request_support)
    db.add(row); db.flush()
    assessment, case, created_new = create_case_from_text(db, user, "journal", row.id, row.content, request_support=payload.request_support)
    write_audit(db, user.tenant_id, user.id, "journal_created", "journal_entry", row.id, purpose="student_wellbeing")
    db.commit()
    response = {"id": row.id, "title": row.title, "content": row.content, "request_support": row.share_with_support_team, "created_at": iso(row.created_at)}
    if case:
        response["support_request_created"] = True
        response["case_status"] = case.status
    return response

@app.get("/api/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    rows = db.scalars(select(Conversation).where(Conversation.tenant_id == user.tenant_id, Conversation.student_user_id == user.id).order_by(desc(Conversation.updated_at)).limit(50)).all()
    return [{"id": c.id, "title": c.title, "channel": c.channel, "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)} for c in rows]

@app.post("/api/conversations")
def create_conversation(payload: ConversationInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    if payload.channel == "voice" and not has_consent(db, user, "voice_processing"):
        raise HTTPException(status_code=403, detail="Voice processing consent is required first.")
    conversation = Conversation(id=new_id(), tenant_id=user.tenant_id, student_user_id=user.id,
                                title=payload.title.strip() or "Conversation with Saathi", channel=payload.channel)
    db.add(conversation)
    db.add(Message(id=new_id(), tenant_id=user.tenant_id, conversation_id=conversation.id, speaker="buddy", channel=payload.channel,
                   content="Hi. I'm here to listen. You can share as much or as little as you feel comfortable sharing."))
    write_audit(db, user.tenant_id, user.id, "conversation_created", "conversation", conversation.id, purpose="student_wellbeing")
    db.commit()
    return {"id": conversation.id, "title": conversation.title, "channel": conversation.channel}

@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    conversation = get_student_conversation(db, user, conversation_id)
    rows = db.scalars(select(Message).where(Message.tenant_id == user.tenant_id, Message.conversation_id == conversation.id).order_by(Message.created_at).limit(200)).all()
    write_audit(db, user.tenant_id, user.id, "conversation_viewed", "conversation", conversation.id, purpose="student_wellbeing")
    db.commit()
    return [{"id": m.id, "speaker": m.speaker, "content": m.content, "channel": m.channel, "created_at": iso(m.created_at), "safety_level": m.safety_level} for m in rows]

@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, payload: MessageInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    if payload.channel == "voice" and not has_consent(db, user, "voice_processing"):
        raise HTTPException(status_code=403, detail="Voice processing consent is required first.")
    conversation = get_student_conversation(db, user, conversation_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Please enter a message.")
    user_message = Message(id=new_id(), tenant_id=user.tenant_id, conversation_id=conversation.id,
                           speaker="student", channel=payload.channel, content=content)
    db.add(user_message); db.flush()
    if payload.channel == "voice":
        db.add(VoiceSession(id=new_id(), tenant_id=user.tenant_id, student_user_id=user.id,
                            conversation_id=conversation.id, message_id=user_message.id,
                            transcript_status="persisted", audio_retained=False, transcription_provider="configured-stt"))
    assessment, support_case, created_new = create_case_from_text(db, user, "message", user_message.id, content)
    user_message.safety_level = assessment.urgency
    conversation.updated_at = datetime.now(timezone.utc)
    write_audit(db, user.tenant_id, user.id, "message_created", "message", user_message.id, purpose="student_wellbeing",
                metadata={"channel": payload.channel, "safety_level": assessment.urgency})
    # Commit the message, assessment and any case before the AI or external providers are called.
    db.commit()

    if assessment.urgency == "immediate":
        tenant = current_tenant(db, user)
        buddy_text = urgent_support_message(tenant.support_instructions)
        model_used = "safety-template"
    elif assessment.urgency == "human_review":
        buddy_text = "Thank you for telling me. You deserve to be listened to and supported. It may help to speak with a trusted adult or the school's designated support person. You do not have to handle this alone."
        model_used = "safety-template"
    else:
        try:
            resources = retrieve_knowledge(db, user.tenant_id, content, user.age_band, 3)
            previous = db.scalars(select(Message).where(Message.tenant_id == user.tenant_id,
                Message.conversation_id == conversation.id).order_by(desc(Message.created_at)).limit(9)).all()
            history = [(m.speaker, m.content) for m in reversed(previous) if m.id != user_message.id]
            buddy_text, model_used = generate_buddy_response(content, user.age_band, resources, history)
        except Exception:
            logger.exception("Buddy generation failed; using safe fallback; tenant_id=%s", user.tenant_id)
            buddy_text, model_used = safe_buddy_fallback(content, user.age_band), "local-fallback-after-provider-error"
    buddy_message = Message(id=new_id(), tenant_id=user.tenant_id, conversation_id=conversation.id,
                            speaker="buddy", channel=payload.channel, content=buddy_text)
    db.add(buddy_message)
    write_audit(db, user.tenant_id, None, "buddy_response_created", "message", buddy_message.id,
                purpose="student_wellbeing", metadata={"model_used": model_used})
    db.commit()
    return {
        "student_message": {"id": user_message.id, "speaker": "student", "content": content, "channel": payload.channel, "created_at": iso(user_message.created_at)},
        "buddy_message": {"id": buddy_message.id, "speaker": "buddy", "content": buddy_text, "channel": payload.channel, "created_at": iso(buddy_message.created_at)},
        "safety": {"urgency": assessment.urgency, "case_created": bool(support_case), "case_id": support_case.id if support_case else None,
                   "notice": "If you feel unsafe or need immediate help, contact a trusted adult or local emergency services. The app cannot guarantee an immediate human response." if assessment.urgency in ("immediate", "human_review") else None},
    }

@app.post("/api/voice/transcribe")
def transcribe_voice(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_only(user); require_core_consent(db, user)
    if not settings.voice_enabled:
        raise HTTPException(status_code=503, detail="Voice features are disabled by the school.")
    if not has_consent(db, user, "voice_processing"):
        raise HTTPException(status_code=403, detail="Voice processing consent is required first.")
    allowed_types = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"}
    content_type = (file.content_type or "").split(";")[0].lower()
    if content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="This audio format is not supported. Try a browser-supported webm or wav recording.")
    raw = file.file.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Recording is too large. Please record a shorter message.")
    if not settings.stt_api_base_url or not settings.stt_model:
        raise HTTPException(status_code=503, detail="Speech transcription is not configured in this environment. The recording was not saved by this application.")
    headers = {}
    if settings.stt_api_key:
        headers["Authorization"] = f"Bearer {settings.stt_api_key}"
    try:
        resp = requests.post(settings.stt_api_base_url.rstrip("/") + "/audio/transcriptions",
            headers=headers, data={"model": settings.stt_model},
            files={"file": (file.filename or "voice-message.webm", raw, content_type)}, timeout=35)
        resp.raise_for_status()
        transcript = str(resp.json().get("text", "")).strip()
    except Exception:
        logger.exception("Speech transcription provider failed; no audio persisted; tenant_id=%s", user.tenant_id)
        raise HTTPException(status_code=502, detail="Speech transcription failed. The recording was not saved by this application. You can type the message instead.")
    finally:
        raw = b""
    if not transcript:
        raise HTTPException(status_code=422, detail="No speech was recognized. Please try again or type your message.")
    audit_and_commit(db, user, "voice_transcription_completed", "voice_session", None, purpose="voice_processing",
                     metadata={"provider_configured": True, "audio_retained": False, "characters": len(transcript)})
    return {"transcript": transcript[:6000], "audio_retained": False, "provider_configured": True,
            "notice": "The application does not retain raw audio. The configured speech provider processed the recording; verify its region and retention terms before live use."}

@app.get("/api/knowledge")
def list_knowledge(q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if q and user.role == "student":
        require_core_consent(db, user)
    stmt = select(KnowledgeItem).where(KnowledgeItem.published.is_(True), KnowledgeItem.review_status == "approved",
        or_(KnowledgeItem.tenant_id.is_(None), KnowledgeItem.tenant_id == user.tenant_id))
    if q.strip():
        rows = retrieve_knowledge(db, user.tenant_id, q.strip(), user.age_band, 30)
    else:
        stmt = stmt.order_by(KnowledgeItem.category, KnowledgeItem.title)
        rows = db.scalars(stmt.limit(30)).all()
    return [{"id": k.id, "title": k.title, "content": k.content, "category": k.category, "age_band": k.age_band,
             "source": k.source, "review_status": k.review_status, "reviewer": k.reviewer} for k in rows]

@app.post("/api/knowledge")
def add_knowledge(payload: KnowledgeInput, user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    if not payload.reviewer_attestation:
        raise HTTPException(status_code=400, detail="A counsellor must attest that the item has completed the required review before publication.")
    item = KnowledgeItem(id=new_id(), tenant_id=user.tenant_id, title=payload.title.strip(), content=payload.content.strip(),
        category=payload.category.strip(), age_band=payload.age_band, source=payload.source.strip(), review_status="approved",
        reviewer=user.display_name, content_version="1", published=True, vector_sync_status="pending")
    db.add(item)
    write_audit(db, user.tenant_id, user.id, "knowledge_item_published", "knowledge_item", item.id,
                purpose="content_governance", metadata={"category": item.category, "age_band": item.age_band})
    db.commit()
    vector_status = "pending"
    if pinecone_configured() and not real_embedding_provider_configured():
        vector_status = "waiting_for_embedding_provider"
    elif pinecone_configured():
        item.vector_sync_attempted_at = datetime.now(timezone.utc)
        try:
            upsert_knowledge_vector(item, embed_text(item.title + "\n" + item.content))
            item.vector_sync_status = "synced"
            item.vector_synced_at = datetime.now(timezone.utc)
            vector_status = "synced"
        except Exception:
            item.vector_sync_status = "failed"
            vector_status = "failed_retry_scheduled"
            logger.exception("Knowledge item saved but Pinecone indexing failed; background retry will run")
        db.commit()
    return {"id": item.id, "title": item.title, "review_status": item.review_status,
            "reviewer": item.reviewer, "vector_sync_status": vector_status}

@app.get("/api/consent/status")
def consent_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "student":
        return {"own_student": {"student_id": user.id, "display_name": user.display_name, "age_band": user.age_band,
                                 "consent": consent_summary(db, user)}}
    if user.role == "parent":
        links = db.scalars(select(GuardianLink).where(GuardianLink.tenant_id == user.tenant_id,
            GuardianLink.guardian_user_id == user.id, GuardianLink.verified.is_(True))).all()
        children = []
        for link in links:
            child = db.scalar(select(User).where(User.id == link.student_user_id, User.tenant_id == user.tenant_id, User.role == "student"))
            if child:
                children.append({"student_id": child.id, "display_name": child.display_name, "age_band": child.age_band,
                                 "consent": consent_summary(db, child)})
        return {"children": children}
    if user.role == "counsellor":
        students = db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.role == "student", User.active.is_(True))).all()
        result = []
        for student in students:
            summary = consent_summary(db, student)
            result.append({"student_id": student.id, "display_name": student.display_name, "age_band": student.age_band,
                           "wellbeing_effective": all(summary[p]["effective"] for p in REQUIRED_PURPOSES),
                           "consent": summary})
        return {"students": result}
    raise HTTPException(status_code=403, detail="Consent status is available to students and authorized counsellors only.")

@app.post("/api/consent")
def change_consent(payload: ConsentInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed_purposes = {"wellbeing_processing", "ai_processing", "voice_processing"}
    if any(p not in allowed_purposes for p in payload.purposes):
        raise HTTPException(status_code=422, detail="Unknown consent purpose.")
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Students record their own consent or assent. Counsellors review it separately.")
    if payload.student_id and payload.student_id != user.id:
        raise HTTPException(status_code=403, detail="Students may only manage their own consent or assent.")
    student = user
    actor_type = "adult_self" if (user.age_band or "") == "18+" else "student_assent"
    for purpose in payload.purposes:
        db.add(ConsentRecord(id=new_id(), tenant_id=user.tenant_id, student_user_id=student.id,
            actor_user_id=user.id, actor_type=actor_type, purpose=purpose, status=payload.status,
            notice_version="mvp-v1", verification_method=actor_type))
    write_audit(db, user.tenant_id, user.id, "consent_status_changed", "consent_record", None,
                purpose="consent_administration", metadata={"student_id": student.id, "purposes": payload.purposes,
                                                             "status": payload.status, "actor_type": actor_type})
    db.commit()
    return {"ok": True, "consent": consent_summary(db, student)}

@app.post("/api/consent/review")
def review_student_consent(payload: ConsentReviewInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only counsellors may review student consent in this MVP.")
    allowed_purposes = {"wellbeing_processing", "ai_processing", "voice_processing"}
    if not payload.purposes or any(p not in allowed_purposes for p in payload.purposes):
        raise HTTPException(status_code=422, detail="Select valid consent purposes.")
    student = db.scalar(select(User).where(User.id == payload.student_id, User.tenant_id == user.tenant_id,
                                           User.role == "student", User.active.is_(True)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    if (student.age_band or "") == "18+":
        raise HTTPException(status_code=400, detail="Adult students manage their own consent; counsellor approval is not required.")
    for purpose in payload.purposes:
        assent = latest_consent(db, student.id, purpose, "student_assent", student.tenant_id)
        if not assent or assent.status != "granted":
            raise HTTPException(status_code=409, detail=f"The student has not granted consent for {purpose}.")
        db.add(ConsentRecord(id=new_id(), tenant_id=user.tenant_id, student_user_id=student.id,
            actor_user_id=user.id, actor_type="counsellor_approval", purpose=purpose, status="granted",
            notice_version="mvp-v1", verification_method="counsellor_reviewed_student_assent"))
    write_audit(db, user.tenant_id, user.id, "student_consent_review_approved", "consent_record", None,
                purpose="consent_administration", metadata={"student_id": student.id, "purposes": payload.purposes,
                                                             "actor_type": "counsellor_approval"})
    db.commit()
    return {"ok": True, "consent": consent_summary(db, student)}

@app.get("/api/cases")
def list_cases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "counsellor":
        stmt = select(SupportCase).where(SupportCase.tenant_id == user.tenant_id)
    elif user.role == "teacher":
        stmt = select(SupportCase).where(SupportCase.tenant_id == user.tenant_id, SupportCase.assigned_to_user_id == user.id)
    else:
        raise HTTPException(status_code=403, detail="This role cannot access case-level records.")
    rows = db.scalars(stmt.order_by(desc(SupportCase.created_at)).limit(100)).all()
    write_audit(db, user.tenant_id, user.id, "case_queue_viewed", "support_case_queue", None, purpose="case_management")
    db.commit()
    return [serialize_case(db, user, c, detailed=False) for c in rows]

@app.get("/api/cases/{case_id}")
def get_case(case_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.tenant_id == user.tenant_id))
    if not case or not can_read_case(db, user, case):
        raise HTTPException(status_code=404, detail="Case not found.")
    write_audit(db, user.tenant_id, user.id, "case_viewed", "support_case", case.id, purpose="case_management")
    db.commit()
    return serialize_case(db, user, case, detailed=True)

@app.patch("/api/students/{student_id}/profile")
def update_student_profile(student_id: str, payload: StudentProfileInput,
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update the student's standard/class; only counsellors may edit this profile field."""
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only counsellors may update student profile details.")
    student = db.scalar(select(User).where(
        User.id == student_id, User.tenant_id == user.tenant_id,
        User.role == "student", User.active.is_(True)
    ))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    value = payload.school_class.strip() if payload.school_class else None
    student.school_class = value or None
    write_audit(db, user.tenant_id, user.id, "student_class_updated", "student_profile", student.id,
                purpose="case_management", metadata={"school_class": student.school_class})
    db.commit()
    return {"ok": True, "student_id": student.id, "school_class": student.school_class}

@app.patch("/api/cases/{case_id}/assignment")
def assign_case(case_id: str, payload: CaseAssignmentInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Assign or unassign a case. Assignment changes are tenant-scoped and audited."""
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only counsellors may assign cases.")
    case = db.scalar(select(SupportCase).where(
        SupportCase.id == case_id, SupportCase.tenant_id == user.tenant_id
    ))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    assignee = None
    if payload.assigned_to_user_id:
        assignee = db.scalar(select(User).where(
            User.id == payload.assigned_to_user_id, User.tenant_id == user.tenant_id,
            User.active.is_(True), User.role.in_(["teacher", "counsellor"])
        ))
        if not assignee:
            raise HTTPException(status_code=400, detail="Choose an active teacher or counsellor from this school.")
    previous_assignee_id = case.assigned_to_user_id
    case.assigned_to_user_id = assignee.id if assignee else None
    case.updated_at = datetime.now(timezone.utc)
    write_audit(db, user.tenant_id, user.id, "case_assigned" if assignee else "case_unassigned",
                "support_case", case.id, purpose="case_management",
                metadata={"previous_assignee_id": previous_assignee_id, "new_assignee_id": case.assigned_to_user_id})
    notification_queued = False
    # Do not silently send to the counsellor as a fallback if the assigned staff member lacks email.
    if assignee and assignee.email and assignee.id != previous_assignee_id:
        notification = build_notification_payload(
            db, user.tenant_id, case.id, "case.updated", case.urgency, assignee.id,
            extra={"case_id": case.id, "assignment_changed": True},
        )
        enqueue_event(db, user.tenant_id, "case.updated", case.id, notification)
        notification_queued = True
    db.commit()
    return {"ok": True, "assigned_to_user_id": case.assigned_to_user_id,
            "assigned_to": assignee.display_name if assignee else "Unassigned",
            "notification_queued": notification_queued,
            "notification_note": None if not assignee or assignee.email else "Assignment saved, but the assignee has no email address configured."}


@app.patch("/api/cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdateInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.tenant_id == user.tenant_id))
    if not case or not can_read_case(db, user, case):
        raise HTTPException(status_code=404, detail="Case not found.")
    if payload.status == "closed" and user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only a counsellor may close a case.")
    now = datetime.now(timezone.utc)
    case.status = payload.status
    if payload.status == "in_review" and not case.acknowledged_at:
        case.acknowledged_at = now
    if payload.status == "closed":
        if not payload.resolution_note or not payload.resolution_note.strip():
            raise HTTPException(status_code=400, detail="A resolution note is required to close a case.")
        case.closed_at = now
        case.resolution_note = payload.resolution_note.strip()
    case.updated_at = now
    write_audit(db, user.tenant_id, user.id, "case_status_changed", "support_case", case.id,
                purpose="case_management", metadata={"status": payload.status})
    db.commit()
    return {"ok": True, "case": serialize_case(db, user, case, detailed=True)}

@app.post("/api/cases/{case_id}/actions")
def add_case_action(case_id: str, payload: CaseActionInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.tenant_id == user.tenant_id))
    if not case or not can_read_case(db, user, case):
        raise HTTPException(status_code=404, detail="Case not found.")
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only counsellors may assign support actions.")
    assignee = None
    if payload.assigned_to_user_id:
        assignee = db.scalar(select(User).where(User.id == payload.assigned_to_user_id, User.tenant_id == user.tenant_id, User.active.is_(True)))
        if not assignee or assignee.role not in ("teacher", "counsellor"):
            raise HTTPException(status_code=400, detail="Choose an active staff member from this school.")
    due_at = payload.due_at
    if due_at and due_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Due dates must include a timezone.")
    action = CaseAction(id=new_id(), tenant_id=user.tenant_id, case_id=case.id,
                        assigned_to_user_id=assignee.id if assignee else None, created_by_user_id=user.id,
                        title=payload.title.strip(), notes=payload.notes.strip(), due_at=due_at, status="open")
    db.add(action)
    write_audit(db, user.tenant_id, user.id, "case_action_created", "case_action", action.id, purpose="case_management")
    notification_queued = False
    if assignee and assignee.email:
        notification = build_notification_payload(
            db, user.tenant_id, action.id, "followup.assigned", case.urgency, assignee.id,
            extra={"action_id": action.id, "case_id": case.id},
        )
        enqueue_event(db, user.tenant_id, "followup.assigned", action.id, notification)
        notification_queued = True
    db.commit()
    return {"id": action.id, "title": action.title, "status": action.status, "due_at": iso(action.due_at),
            "notification_queued": notification_queued,
            "notification_note": None if not assignee or assignee.email else "Action saved, but the assignee has no email address configured."}

@app.post("/api/actions/{action_id}/progress")
def record_action_progress(action_id: str, payload: ActionProgressInput,
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Persist a staff progress entry and optionally hand the action back for counsellor review."""
    action = db.scalar(select(CaseAction).where(
        CaseAction.id == action_id, CaseAction.tenant_id == user.tenant_id
    ))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    case = db.scalar(select(SupportCase).where(
        SupportCase.id == action.case_id, SupportCase.tenant_id == user.tenant_id
    ))
    if not case or not can_read_case(db, user, case):
        raise HTTPException(status_code=404, detail="Action not found.")
    if user.role != "counsellor" and (user.role != "teacher" or action.assigned_to_user_id != user.id):
        raise HTTPException(status_code=403, detail="Only the assigned staff member or counsellor may record progress.")
    if action.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail="This action is closed. Ask the counsellor to reopen it before adding progress.")
    progress = CaseActionProgress(
        id=new_id(), tenant_id=user.tenant_id, action_id=action.id, author_user_id=user.id,
        work_performed=payload.work_performed.strip(), outcome=payload.outcome.strip(),
        further_concerns=payload.further_concerns.strip(), next_step=payload.next_step.strip(),
        submitted_for_review=payload.submit_for_review,
    )
    db.add(progress)
    now = datetime.now(timezone.utc)
    action.status = "submitted_for_review" if payload.submit_for_review else "in_progress"
    if not payload.submit_for_review and action.status == "submitted_for_review":
        action.status = "in_progress"
    action.completed_at = None
    write_audit(db, user.tenant_id, user.id,
                "case_action_submitted_for_review" if payload.submit_for_review else "case_action_progress_saved",
                "case_action", action.id, purpose="case_management",
                metadata={"status": action.status, "progress_id": progress.id})
    # Notify the action's creator (normally the assigning counsellor) without sending student data.
    notification_queued = False
    if payload.submit_for_review:
        recipient = db.scalar(select(User).where(
            User.id == action.created_by_user_id, User.tenant_id == user.tenant_id,
            User.role == "counsellor", User.active.is_(True), User.email.is_not(None)
        ))
        if recipient:
            notification = build_notification_payload(
                db, user.tenant_id, action.id, "case.updated", case.urgency, recipient.id,
                extra={"action_id": action.id, "case_id": case.id, "review_requested": True}
            )
            enqueue_event(db, user.tenant_id, "case.updated", action.id, notification)
            notification_queued = True
    case.updated_at = now
    db.commit()
    return {"ok": True, "id": action.id, "status": action.status,
            "progress_id": progress.id, "notification_queued": notification_queued}

@app.patch("/api/actions/{action_id}/review")
def review_action(action_id: str, payload: ActionReviewInput,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Counsellor-only review: approve completion, request changes, or reopen an action."""
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Only a counsellor may review or close a support action.")
    action = db.scalar(select(CaseAction).where(
        CaseAction.id == action_id, CaseAction.tenant_id == user.tenant_id
    ))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    case = db.scalar(select(SupportCase).where(
        SupportCase.id == action.case_id, SupportCase.tenant_id == user.tenant_id
    ))
    if not case:
        raise HTTPException(status_code=404, detail="Action not found.")
    if payload.decision != "reopen" and action.status != "submitted_for_review":
        raise HTTPException(status_code=409, detail="Only actions submitted for review can be approved or returned for changes.")
    now = datetime.now(timezone.utc)
    if payload.decision == "approve":
        action.status = "completed"
        action.completed_at = now
        audit_action = "case_action_review_approved"
    elif payload.decision == "request_changes":
        action.status = "changes_requested"
        action.completed_at = None
        audit_action = "case_action_changes_requested"
    else:
        action.status = "open"
        action.completed_at = None
        audit_action = "case_action_reopened"
    # Review note is stored as a separate progress entry so it persists with the action's history.
    if payload.review_note.strip():
        db.add(CaseActionProgress(
            id=new_id(), tenant_id=user.tenant_id, action_id=action.id, author_user_id=user.id,
            work_performed="Counsellor review", outcome=payload.review_note.strip(),
            further_concerns="", next_step="", submitted_for_review=False,
        ))
    case.updated_at = now
    write_audit(db, user.tenant_id, user.id, audit_action, "case_action", action.id,
                purpose="case_management", metadata={"decision": payload.decision})
    db.commit()
    return {"ok": True, "id": action.id, "status": action.status, "completed_at": iso(action.completed_at)}

@app.patch("/api/actions/{action_id}")
def update_action(action_id: str, payload: ActionUpdateInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Counsellors manage action state; teachers must use progress submission and review handoff."""
    action = db.scalar(select(CaseAction).where(CaseAction.id == action_id, CaseAction.tenant_id == user.tenant_id))
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    case = db.scalar(select(SupportCase).where(SupportCase.id == action.case_id, SupportCase.tenant_id == user.tenant_id))
    if not case or not can_read_case(db, user, case):
        raise HTTPException(status_code=404, detail="Action not found.")
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Teachers must submit progress for counsellor review rather than changing action status directly.")
    action.status = payload.status
    action.completed_at = datetime.now(timezone.utc) if payload.status == "completed" else None
    case.updated_at = datetime.now(timezone.utc)
    write_audit(db, user.tenant_id, user.id, "case_action_status_changed", "case_action", action.id,
                purpose="case_management", metadata={"status": action.status})
    db.commit()
    return {"ok": True, "id": action.id, "status": action.status}

@app.get("/api/reports/summary")
def reports_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Aggregate reports are not available for this role.")
    active_students = int(db.scalar(select(func.count(User.id)).where(User.tenant_id == user.tenant_id, User.role == "student", User.active.is_(True))) or 0)
    open_cases = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.status.in_(["open", "in_review"]))) or 0)
    by_urgency = {}
    for urgency in ("immediate", "human_review", "routine"):
        by_urgency[urgency] = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == user.tenant_id, SupportCase.urgency == urgency, SupportCase.status.in_(["open", "in_review"]))) or 0)
    completed_actions = int(db.scalar(select(func.count(CaseAction.id)).where(CaseAction.tenant_id == user.tenant_id, CaseAction.status == "completed")) or 0)
    return {"active_students": active_students, "open_cases": open_cases, "open_cases_by_urgency": by_urgency,
            "completed_support_actions": completed_actions, "generated_at": iso(datetime.now(timezone.utc)),
            "note": "Aggregate operational counts only; not a diagnostic or student ranking report."}

@app.get("/api/audit")
def list_audit(limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "counsellor":
        raise HTTPException(status_code=403, detail="Audit records are not available for this role.")
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == user.tenant_id).order_by(desc(AuditEvent.created_at)).limit(max(1, min(limit, 200)))).all()
    return [{"id": r.id, "actor_user_id": r.actor_user_id, "action": r.action, "resource_type": r.resource_type,
             "resource_id": r.resource_id, "purpose": r.purpose, "outcome": r.outcome, "metadata": r.metadata_json,
             "created_at": iso(r.created_at)} for r in rows]

@app.get("/api/admin/users")
def admin_users(user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.active.is_(True)).order_by(User.role, User.display_name)).all()
    return [{"id": r.id, "display_name": r.display_name, "role": r.role} for r in rows]

@app.get("/api/internal/notification-target")
def internal_notification_target(tenant_id: str, resource_id: str, event_type: str,
                                request: Request, db: Session = Depends(get_db)):
    """Resolve an event's fallback recipient inside its own tenant; never use a global school mailbox."""
    require_internal_secret(request)
    if event_type not in {"case.created", "case.updated", "followup.due", "followup.assigned"}:
        raise HTTPException(status_code=422, detail="Unsupported notification event.")
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active"))
    if not tenant:
        raise HTTPException(status_code=404, detail="Active tenant not found.")
    set_tenant_context(db, tenant.id)
    urgency = "human_review"
    category = "student_support"
    if event_type in {"case.created", "case.updated"}:
        record = db.scalar(select(SupportCase).where(SupportCase.tenant_id == tenant.id, SupportCase.id == resource_id))
        if not record:
            raise HTTPException(status_code=404, detail="Case not found in this tenant.")
        urgency, category = record.urgency, record.category
        if record.assigned_to_user_id:
            assigned = db.scalar(select(User).where(User.tenant_id == tenant.id, User.id == record.assigned_to_user_id,
                User.role.in_(["teacher", "counsellor"]), User.active.is_(True)))
            if assigned and assigned.email:
                subject = "Saathi: urgent safeguarding review required" if urgency == "immediate" else "Saathi: student support case requires review"
                message = ("An urgent student support case requires prompt human review. Follow the school's safeguarding procedure; email alone is not sufficient."
                           if urgency == "immediate" else "A restricted student support case requires review. Sign in to the secure school dashboard. This message intentionally contains no student content.")
                return {"recipient_email": assigned.email, "tenant_slug": tenant.slug, "resource_id": resource_id,
                        "subject": subject, "message": message}
    else:
        action = db.scalar(select(CaseAction).where(CaseAction.tenant_id == tenant.id, CaseAction.id == resource_id))
        if not action:
            raise HTTPException(status_code=404, detail="Follow-up action not found in this tenant.")
        if action.assigned_to_user_id:
            assigned = db.scalar(select(User).where(User.tenant_id == tenant.id, User.id == action.assigned_to_user_id,
                User.role.in_(["teacher", "counsellor"]), User.active.is_(True)))
            if assigned and assigned.email:
                return {"recipient_email": assigned.email, "tenant_slug": tenant.slug, "resource_id": resource_id,
                        "subject": "Saathi: a support follow-up is assigned to you" if event_type == "followup.assigned" else "Saathi: a support follow-up is due",
                        "message": "A support action has been assigned to you. Sign in to the secure school dashboard to review it. This message contains no student content." if event_type == "followup.assigned" else "A support follow-up is due or approaching its due time. Sign in to the secure school dashboard. This message contains no student content."}
    # Only an active counsellor in this exact tenant can receive the no-assignee fallback.
    lead = db.scalar(select(User).where(User.tenant_id == tenant.id, User.role == "counsellor", User.active.is_(True), User.email.is_not(None)).order_by(User.created_at).limit(1))
    if not lead:
        logger.error("No tenant counsellor notification recipient configured; tenant_id=%s event_type=%s", tenant.id, event_type)
        raise HTTPException(status_code=503, detail="This school has no active counsellor notification recipient. No email was sent.")
    subject = "Saathi: urgent safeguarding review required" if urgency == "immediate" else "Saathi: unassigned student support case needs routing"
    message = "An urgent student support case requires prompt human review. Follow the school's safeguarding procedure; email alone is not sufficient." if urgency == "immediate" else "A student support item has no active assignee. Sign in to the secure school dashboard and route it under the school's procedure."
    if event_type == "followup.due":
        subject = "Saathi: a support follow-up is unassigned"
        message = "A support follow-up has no active assignee. Sign in to the secure school dashboard and route it. This message contains no student content."
    return {"recipient_email": lead.email, "tenant_slug": tenant.slug, "resource_id": resource_id,
            "subject": subject, "message": message}


@app.get("/api/internal/aggregate-report")
def internal_aggregate_report(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    require_internal_secret(request)
    tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug, Tenant.status == "active"))
    if not tenant:
        raise HTTPException(status_code=404, detail="Unknown school tenant.")
    set_tenant_context(db, tenant.id)
    open_cases = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == tenant.id, SupportCase.status.in_(["open", "in_review"]))) or 0)
    immediate = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.tenant_id == tenant.id, SupportCase.urgency == "immediate", SupportCase.status.in_(["open", "in_review"]))) or 0)
    overdue_actions = int(db.scalar(select(func.count(CaseAction.id)).where(CaseAction.tenant_id == tenant.id, CaseAction.status == "open", CaseAction.due_at < datetime.now(timezone.utc))) or 0)
    active_students = int(db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id, User.role == "student", User.active.is_(True))) or 0)
    return {"tenant_slug": tenant.slug, "active_students": active_students, "open_cases": open_cases,
            "immediate_cases": immediate, "overdue_followups": overdue_actions,
            "generated_at": iso(datetime.now(timezone.utc)), "contains_student_content": False}

@app.get("/api/internal/health")
def internal_health(request: Request):
    require_internal_secret(request)
    return {"status": "ok", "n8n_webhook_configured": bool(settings.n8n_enabled and settings.n8n_webhook_url), "voice_configured": bool(settings.stt_api_base_url)}


RETENTION_CATEGORIES = {"journal_entries", "messages", "voice_sessions", "closed_cases"}

@app.get("/api/retention/policies")
def get_retention_policies(user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RetentionPolicy).where(RetentionPolicy.tenant_id == user.tenant_id).order_by(RetentionPolicy.data_category)).all()
    return [{"id": r.id, "data_category": r.data_category, "retention_days": r.retention_days,
             "active": r.active, "approved_for_live_data": r.approved_for_live_data,
             "policy_version": r.policy_version, "updated_at": iso(r.updated_at)} for r in rows]

@app.put("/api/retention/policies/{category}")
def update_retention_policy(category: str, payload: RetentionPolicyInput,
                            user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    if category not in RETENTION_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown retention category.")
    if payload.active and not payload.approved_for_live_data:
        raise HTTPException(status_code=400, detail="Active deletion requires an explicit live-data policy approval attestation.")
    row = db.scalar(select(RetentionPolicy).where(RetentionPolicy.tenant_id == user.tenant_id, RetentionPolicy.data_category == category))
    if not row:
        row = RetentionPolicy(id=new_id(), tenant_id=user.tenant_id, data_category=category)
        db.add(row)
    row.retention_days = payload.retention_days
    row.active = payload.active
    row.approved_for_live_data = payload.approved_for_live_data
    row.approved_by_user_id = user.id if payload.approved_for_live_data else None
    row.policy_version = f"mvp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    row.updated_at = datetime.now(timezone.utc)
    write_audit(db, user.tenant_id, user.id, "retention_policy_changed", "retention_policy", row.id,
                purpose="retention_governance", metadata={"category": category, "days": row.retention_days,
                                                           "active": row.active, "approved": row.approved_for_live_data})
    db.commit()
    return {"ok": True, "data_category": row.data_category, "retention_days": row.retention_days,
            "active": row.active, "policy_version": row.policy_version}

@app.post("/api/retention/run")
def run_retention(payload: RetentionRunInput, user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    policies = db.scalars(select(RetentionPolicy).where(RetentionPolicy.tenant_id == user.tenant_id,
        RetentionPolicy.active.is_(True), RetentionPolicy.approved_for_live_data.is_(True))).all()
    if not policies:
        return {"dry_run": payload.dry_run, "message": "No active, approved retention policies. Nothing was deleted.", "candidates": {}}
    now = datetime.now(timezone.utc)
    candidates: dict[str, int] = {}
    policy_map = {p.data_category: p for p in policies}

    def held_ids(record_type: str) -> set[str]:
        return set(db.scalars(select(RetentionHold.record_id).where(RetentionHold.tenant_id == user.tenant_id,
            RetentionHold.record_type == record_type, RetentionHold.released_at.is_(None))).all())

    if "closed_cases" in policy_map:
        cutoff = now - timedelta(days=policy_map["closed_cases"].retention_days)
        ids = list(db.scalars(select(SupportCase.id).where(SupportCase.tenant_id == user.tenant_id,
            SupportCase.status == "closed", SupportCase.closed_at.is_not(None), SupportCase.closed_at < cutoff)).all())
        ids = [i for i in ids if i not in held_ids("support_case")]
        candidates["closed_cases"] = len(ids)
    else:
        ids = []
        candidates["closed_cases"] = 0

    # Only content that is not referenced by a support case is eligible. Open/closed case evidence is retained
    # unless the closed case itself is eligible for deletion in this run.
    def referenced_source_ids(source_type: str) -> set[str]:
        excluded_case_ids = set(ids)
        rows = db.execute(select(SupportCase.source_id).where(SupportCase.tenant_id == user.tenant_id,
            SupportCase.source_type == source_type, ~SupportCase.id.in_(excluded_case_ids) if excluded_case_ids else True)).all()
        return {r[0] for r in rows}

    journal_ids: list[str] = []
    if "journal_entries" in policy_map:
        cutoff = now - timedelta(days=policy_map["journal_entries"].retention_days)
        rows = db.scalars(select(JournalEntry.id).where(JournalEntry.tenant_id == user.tenant_id, JournalEntry.created_at < cutoff)).all()
        excluded = held_ids("journal_entry") | referenced_source_ids("journal")
        journal_ids = [i for i in rows if i not in excluded]
    candidates["journal_entries"] = len(journal_ids)

    message_ids: list[str] = []
    if "messages" in policy_map:
        cutoff = now - timedelta(days=policy_map["messages"].retention_days)
        rows = db.scalars(select(Message.id).where(Message.tenant_id == user.tenant_id, Message.created_at < cutoff)).all()
        excluded = held_ids("message") | referenced_source_ids("message")
        message_ids = [i for i in rows if i not in excluded]
    candidates["messages"] = len(message_ids)

    voice_ids: list[str] = []
    if "voice_sessions" in policy_map:
        cutoff = now - timedelta(days=policy_map["voice_sessions"].retention_days)
        rows = db.scalars(select(VoiceSession.id).where(VoiceSession.tenant_id == user.tenant_id, VoiceSession.created_at < cutoff)).all()
        excluded = held_ids("voice_session")
        voice_ids = [i for i in rows if i not in excluded]
    candidates["voice_sessions"] = len(voice_ids)

    write_audit(db, user.tenant_id, user.id, "retention_run_requested", "retention_job", None,
                purpose="retention_governance", metadata={"dry_run": payload.dry_run, "candidate_counts": candidates})
    if payload.dry_run:
        db.commit()
        return {"dry_run": True, "message": "No records were deleted. Review candidates before an execution run.", "candidates": candidates}

    # Delete case-linked child actions and assessments before eligible cases; preserve audit events.
    if ids:
        cases = db.scalars(select(SupportCase).where(SupportCase.tenant_id == user.tenant_id, SupportCase.id.in_(ids))).all()
        source_refs = [(c.source_type, c.source_id) for c in cases]
        db.execute(delete(CaseAction).where(CaseAction.tenant_id == user.tenant_id, CaseAction.case_id.in_(ids)))
        for source_type, source_id in source_refs:
            db.execute(delete(SafetyAssessment).where(SafetyAssessment.tenant_id == user.tenant_id,
                SafetyAssessment.source_type == source_type, SafetyAssessment.source_id == source_id))
        db.execute(delete(SupportCase).where(SupportCase.tenant_id == user.tenant_id, SupportCase.id.in_(ids)))
    if journal_ids:
        db.execute(delete(SafetyAssessment).where(SafetyAssessment.tenant_id == user.tenant_id,
            SafetyAssessment.source_type == "journal", SafetyAssessment.source_id.in_(journal_ids)))
        db.execute(delete(JournalEntry).where(JournalEntry.tenant_id == user.tenant_id, JournalEntry.id.in_(journal_ids)))
    if message_ids:
        db.execute(delete(VoiceSession).where(VoiceSession.tenant_id == user.tenant_id, VoiceSession.message_id.in_(message_ids)))
        db.execute(delete(SafetyAssessment).where(SafetyAssessment.tenant_id == user.tenant_id,
            SafetyAssessment.source_type == "message", SafetyAssessment.source_id.in_(message_ids)))
        db.execute(delete(Message).where(Message.tenant_id == user.tenant_id, Message.id.in_(message_ids)))
    if voice_ids:
        db.execute(delete(VoiceSession).where(VoiceSession.tenant_id == user.tenant_id, VoiceSession.id.in_(voice_ids)))
    write_audit(db, user.tenant_id, user.id, "retention_execution_completed", "retention_job", None,
                purpose="retention_governance", metadata={"deleted_counts": candidates})
    db.commit()
    return {"dry_run": False, "message": "Retention execution completed. Audit metadata was preserved.", "deleted_counts": candidates}

class RetentionHoldInput(BaseModel):
    record_type: str = Field(pattern="^(journal_entry|message|voice_session|support_case)$")
    record_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=5, max_length=1000)

@app.post("/api/retention/holds")
def create_retention_hold(payload: RetentionHoldInput,
                          user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    models = {"journal_entry": JournalEntry, "message": Message, "voice_session": VoiceSession, "support_case": SupportCase}
    model = models[payload.record_type]
    record = db.scalar(select(model).where(model.id == payload.record_id, model.tenant_id == user.tenant_id))
    if not record:
        raise HTTPException(status_code=404, detail="Record not found in this school.")
    hold = RetentionHold(id=new_id(), tenant_id=user.tenant_id, record_type=payload.record_type,
                         record_id=payload.record_id, reason=payload.reason.strip(), created_by_user_id=user.id)
    db.add(hold)
    write_audit(db, user.tenant_id, user.id, "retention_hold_created", "retention_hold", hold.id,
                purpose="retention_governance", metadata={"record_type": payload.record_type, "record_id": payload.record_id})
    db.commit()
    return {"id": hold.id, "record_type": hold.record_type, "record_id": hold.record_id, "created_at": iso(hold.created_at)}

@app.post("/api/retention/holds/{hold_id}/release")
def release_retention_hold(hold_id: str, user: User = Depends(require_roles("counsellor")), db: Session = Depends(get_db)):
    hold = db.scalar(select(RetentionHold).where(RetentionHold.id == hold_id, RetentionHold.tenant_id == user.tenant_id,
                                                  RetentionHold.released_at.is_(None)))
    if not hold:
        raise HTTPException(status_code=404, detail="Active retention hold not found.")
    hold.released_at = datetime.now(timezone.utc); hold.released_by_user_id = user.id
    write_audit(db, user.tenant_id, user.id, "retention_hold_released", "retention_hold", hold.id,
                purpose="retention_governance", metadata={"record_type": hold.record_type})
    db.commit()
    return {"ok": True, "released_at": iso(hold.released_at)}
