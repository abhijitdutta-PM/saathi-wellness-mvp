from datetime import datetime, timezone, timedelta
import logging
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.models import (Tenant, User, GuardianLink, ConsentRecord, Quote, KnowledgeItem,
                        SupportCase, SafetyAssessment, AuditEvent, OutboxEvent, CaseAction, RetentionPolicy)
from app.security import new_id, hash_password
from app.safety import Assessment

logger = logging.getLogger("saathi.services")
REQUIRED_PURPOSES = ("wellbeing_processing", "ai_processing")


def is_minor(student: User) -> bool:
    return (student.age_band or "").strip() != "18+"


def latest_consent(db: Session, student_id: str, purpose: str, actor_type: str, tenant_id: str) -> ConsentRecord | None:
    return db.scalar(select(ConsentRecord).where(
        ConsentRecord.tenant_id == tenant_id,
        ConsentRecord.student_user_id == student_id,
        ConsentRecord.purpose == purpose,
        ConsentRecord.actor_type == actor_type,
    ).order_by(desc(ConsentRecord.created_at)).limit(1))


def consent_summary(db: Session, student: User) -> dict:
    purposes = ["wellbeing_processing", "ai_processing", "voice_processing"]
    result = {}
    for purpose in purposes:
        if is_minor(student):
            assent = latest_consent(db, student.id, purpose, "student_assent", student.tenant_id)
            approval = latest_consent(db, student.id, purpose, "counsellor_approval", student.tenant_id)
            approval_is_current = bool(assent and approval and approval.created_at >= assent.created_at)
            result[purpose] = {
                "guardian_status": "not_required_for_mvp",
                "student_status": assent.status if assent else "not_recorded",
                "counsellor_status": approval.status if approval else "not_recorded",
                "effective": bool(assent and assent.status == "granted" and approval and approval.status == "granted" and approval_is_current),
            }
        else:
            self_record = latest_consent(db, student.id, purpose, "adult_self", student.tenant_id)
            result[purpose] = {
                "guardian_status": "not_required",
                "student_status": self_record.status if self_record else "not_recorded",
                "guardian_link_verified": True,
                "counsellor_status": "not_required",
                "effective": bool(self_record and self_record.status == "granted"),
            }
    return result


def has_consent(db: Session, student: User, purpose: str) -> bool:
    summary = consent_summary(db, student)
    return bool(summary.get(purpose, {}).get("effective"))


def has_core_consent(db: Session, student: User) -> bool:
    return all(has_consent(db, student, p) for p in REQUIRED_PURPOSES)


def require_core_consent(db: Session, student: User) -> None:
    if not has_core_consent(db, student):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Wellbeing processing is not enabled. Please complete the required consent and student assent steps first.")


def write_audit(db: Session, tenant_id: str, actor_user_id: str | None, action: str,
                resource_type: str, resource_id: str | None = None, purpose: str = "application_operation",
                outcome: str = "success", metadata: dict | None = None) -> None:
    db.add(AuditEvent(id=new_id(), tenant_id=tenant_id, actor_user_id=actor_user_id, action=action,
                      resource_type=resource_type, resource_id=resource_id, purpose=purpose,
                      outcome=outcome, metadata_json=metadata or {}))


def enqueue_event(db: Session, tenant_id: str, event_type: str, resource_id: str, payload: dict | None = None) -> None:
    db.add(OutboxEvent(id=new_id(), tenant_id=tenant_id, event_type=event_type,
                       resource_id=resource_id, payload=payload or {}, status="pending", attempts=0))


def find_default_assignee(db: Session, tenant_id: str, urgency: str) -> User | None:
    roles = ["counsellor"]
    for role in roles:
        user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == role, User.active.is_(True)).order_by(User.created_at).limit(1))
        if user:
            return user
    return None


def build_notification_payload(db: Session, tenant_id: str, resource_id: str, event_type: str,
                               urgency: str = "human_review", preferred_user_id: str | None = None,
                               extra: dict | None = None) -> dict:
    """Resolve a notification recipient in the same tenant before sending to n8n Cloud."""
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    recipient = None
    if preferred_user_id:
        recipient = db.scalar(select(User).where(
            User.id == preferred_user_id, User.tenant_id == tenant_id,
            User.role.in_(["teacher", "counsellor"]), User.active.is_(True), User.email.is_not(None)))
    if not recipient:
        recipient = db.scalar(select(User).where(
            User.tenant_id == tenant_id, User.role == "counsellor",
            User.active.is_(True), User.email.is_not(None)).order_by(User.created_at).limit(1))
    tenant_slug = tenant.slug if tenant else "school"
    if event_type == "followup.assigned":
        subject = "Saathi: a support follow-up is assigned to you"
        message = "A support action has been assigned to you. Sign in to the secure school dashboard to review it. This message contains no student content."
    elif event_type == "followup.due":
        subject = "Saathi: a support follow-up is due"
        message = "A support follow-up is due or approaching its due time. Sign in to the secure school dashboard. This message contains no student content."
    elif urgency == "immediate":
        subject = "Saathi: urgent safeguarding review required"
        message = "An urgent student support case requires prompt human review. Follow the school's safeguarding procedure; email alone is not sufficient."
    elif not preferred_user_id or not recipient:
        subject = "Saathi: unassigned student support case needs routing"
        message = "A restricted student support item needs an owner. Sign in to the secure school dashboard and route it under the school's procedure. This message contains no student content."
    else:
        subject = "Saathi: student support case requires review"
        message = "A restricted student support case requires review. Sign in to the secure school dashboard. This message intentionally contains no student content."
    payload = {
        "resource_id": resource_id,
        "event_type": event_type,
        "tenant_slug": tenant_slug,
        "recipient_email": recipient.email if recipient else None,
        "subject": subject,
        "message": message,
        "dashboard_path": "/?view=cases",
        "contains_student_content": False,
    }
    if extra:
        payload.update(extra)
    return payload


def create_safety_record_and_case(db: Session, student: User, assessment: Assessment,
                                  source_type: str, source_id: str, source_text: str,
                                  created_by_user_id: str | None = None) -> tuple[SafetyAssessment, SupportCase | None, bool]:
    item = SafetyAssessment(
        id=new_id(), tenant_id=student.tenant_id, student_user_id=student.id,
        source_type=source_type, source_id=source_id,
        concern_category=assessment.category, urgency=assessment.urgency,
        evidence_terms=assessment.matched_terms, reason_summary=assessment.reason[:500],
    )
    db.add(item)
    case = None
    created_new = False
    if assessment.create_case:
        now = datetime.now(timezone.utc)
        case = db.scalar(select(SupportCase).where(
            SupportCase.tenant_id == student.tenant_id,
            SupportCase.student_user_id == student.id,
            SupportCase.category == assessment.category,
            SupportCase.status.in_(["open", "in_review"]),
            SupportCase.created_at >= now - timedelta(hours=24),
        ).order_by(desc(SupportCase.created_at)).limit(1))
        if case:
            case.evidence_excerpt = source_text[:650]
            case.summary = assessment.reason[:700]
            case.urgency = max((case.urgency, assessment.urgency), key=lambda x: {"routine": 0, "human_review": 1, "immediate": 2}.get(x, 0))
            case.updated_at = now
            event_type = "case.updated"
        else:
            assignee = find_default_assignee(db, student.tenant_id, assessment.urgency)
            case = SupportCase(
                id=new_id(), tenant_id=student.tenant_id, student_user_id=student.id,
                assigned_to_user_id=assignee.id if assignee else None,
                created_by_user_id=created_by_user_id,
                urgency=assessment.urgency, category=assessment.category,
                title="Urgent student support review" if assessment.urgency == "immediate" else "Student wellbeing follow-up",
                summary=assessment.reason[:700], evidence_excerpt=source_text[:650],
                source_type=source_type, source_id=source_id, status="open",
            )
            db.add(case)
            created_new = True
            event_type = "case.created"
        db.flush()
        notification = build_notification_payload(
            db, student.tenant_id, case.id, event_type, case.urgency, case.assigned_to_user_id,
            extra={"case_id": case.id, "urgency": case.urgency},
        )
        enqueue_event(db, student.tenant_id, event_type, case.id, notification)
    write_audit(db, student.tenant_id, created_by_user_id, "safety_assessment_created", "safety_assessment", item.id,
                purpose="student_safety", metadata={"urgency": assessment.urgency, "source_type": source_type})
    return item, case, created_new


QUOTE_CONTENT = [
    ("You do not have to solve the whole day at once. What is one small thing you can do next?", "Saathi reflection", "small-steps"),
    ("A feeling is something you are experiencing, not everything you are.", "Saathi reflection", "self-compassion"),
    ("When something is outside your control, you can still choose one kind step for yourself.", "Saathi reflection", "agency"),
    ("Asking for help is one way of taking care of yourself.", "Saathi reflection", "help-seeking"),
    ("You can pause, take a breath, and begin again without needing to be perfect.", "Saathi reflection", "resilience"),
    ("A difficult moment can matter without defining your whole story.", "Saathi reflection", "perspective"),
]

KNOWLEDGE_CONTENT = [
    {
        "title": "Focus on what is within your control",
        "category": "philosophical_reflection", "age_band": "all",
        "source": "Original educational summary inspired by Stoic philosophy; not a quotation",
        "content": "When school or friendship problems feel big, gently separate what you can influence from what you cannot. You may be able to choose one next step, ask a question, practise for ten minutes, or seek help. You are not responsible for things that other people do to harm you, and this idea should never be used to excuse bullying or abuse."
    },
    {
        "title": "A short grounding exercise",
        "category": "coping_skill", "age_band": "all",
        "source": "Original wellbeing exercise; must be reviewed by qualified professionals before production",
        "content": "If it feels okay, place both feet on the floor and breathe normally. Notice five things you can see, four things you can feel, and three things you can hear. You can stop whenever you want. This is an optional grounding exercise, not a substitute for getting help when you feel unsafe or overwhelmed."
    },
    {
        "title": "When friendship feels difficult",
        "category": "relationships", "age_band": "all",
        "source": "Original school wellbeing guidance; professional review required before production",
        "content": "It can help to name what happened, what you felt, and what you need next. If you feel safe, you may choose to speak calmly with the other person. If there are threats, repeated bullying, pressure, or fear, you do not have to handle it alone. Tell a trusted adult and ask for help."
    },
    {
        "title": "A small reflection after a setback",
        "category": "academic_stress", "age_band": "all",
        "source": "Original educational guidance; professional review required before production",
        "content": "A mark, mistake, or difficult day gives information about one moment; it does not measure your worth. You might ask: What was hard? What helped a little? What is one realistic next step? Rest and support matter too. If pressure feels unmanageable, talk to a trusted adult."
    },
    {
        "title": "When something feels unsafe",
        "category": "safeguarding", "age_band": "all",
        "source": "Original safety-oriented guidance; safeguarding lead review required before production",
        "content": "If someone is hurting, threatening, pressuring, or making you feel unsafe, it is not your fault that you need help. Try to reach a safe trusted adult or the school's designated safeguarding person. If one adult is not safe to tell, choose another. If danger is immediate, contact local emergency services."
    },
    {
        "title": "Talking to a trusted adult",
        "category": "help_seeking", "age_band": "all",
        "source": "Original help-seeking prompt; professional review required before production",
        "content": "You can start with a simple sentence such as: 'Something has been bothering me, and I need you to listen.' You do not need to explain everything at once. You may write down what you want to say or ask the adult to help you find a counsellor."
    },
]


def seed_demo_data(db: Session) -> None:
    """Create fictional users and reviewed-for-demo content. Never run in production."""
    if db.query(Tenant).count() > 0:
        return
    now = datetime.now(timezone.utc)
    tenant_a = Tenant(id=new_id(), slug="demo-school", name="Riverbend Demonstration School", status="active",
                      support_instructions="Demo only: no live support team is monitoring this application. Please contact a trusted adult directly.")
    tenant_b = Tenant(id=new_id(), slug="sample-academy", name="Sample Academy (Isolation Test Tenant)", status="active",
                      support_instructions="Demo only: no live support team is monitoring this application. Please contact a trusted adult directly.")
    db.add_all([tenant_a, tenant_b]); db.flush()
    for tenant in (tenant_a, tenant_b):
        for category, days in (("journal_entries", 365), ("messages", 365), ("voice_sessions", 90), ("closed_cases", 1095)):
            db.add(RetentionPolicy(id=new_id(), tenant_id=tenant.id, data_category=category, retention_days=days,
                                   active=False, approved_for_live_data=False, policy_version="demo-v1"))

    demo_users = [
        (tenant_a, "student@demo.school", "Amara Student", "student", "11-14", "DemoStudent-2026!"),
        (tenant_a, "parent@demo.school", "Asha Guardian", "parent", None, "DemoParent-2026!"),
        (tenant_a, "teacher@demo.school", "Rohan Teacher", "teacher", None, "DemoTeacher-2026!"),
        (tenant_a, "counsellor@demo.school", "Meera Counsellor", "counsellor", None, "DemoCounsellor-2026!"),
        (tenant_b, "student@sample.academy", "Ishaan Sample Student", "student", "18+", "DemoStudent-2026!"),
        (tenant_b, "counsellor@sample.academy", "Sample Academy Counsellor", "counsellor", None, "DemoCounsellor-2026!"),
    ]
    users: dict[str, User] = {}
    for tenant, email, name, role, age_band, password in demo_users:
        user = User(id=new_id(), tenant_id=tenant.id, email=email, display_name=name, role=role,
                    age_band=age_band, password_hash=hash_password(password), active=True)
        if email == "student@demo.school":
            user.school_class = "9-B"  # Fictional demonstration data only.
        db.add(user); users[email] = user
    db.flush()

    guardian_link = GuardianLink(id=new_id(), tenant_id=tenant_a.id,
                                 student_user_id=users["student@demo.school"].id,
                                 guardian_user_id=users["parent@demo.school"].id,
                                 relationship_label="guardian", verified=True, verified_at=now)
    db.add(guardian_link)
    for purpose in ("wellbeing_processing", "ai_processing", "voice_processing"):
        db.add(ConsentRecord(id=new_id(), tenant_id=tenant_a.id,
            student_user_id=users["student@demo.school"].id, actor_user_id=users["parent@demo.school"].id,
            actor_type="guardian", purpose=purpose, status="granted", notice_version="demo-v1",
            verification_method="synthetic-demo-only", created_at=now))
        db.add(ConsentRecord(id=new_id(), tenant_id=tenant_a.id,
            student_user_id=users["student@demo.school"].id, actor_user_id=users["student@demo.school"].id,
            actor_type="student_assent", purpose=purpose, status="granted", notice_version="demo-v1",
            verification_method="synthetic-demo-only", created_at=now))
    for purpose in ("wellbeing_processing", "ai_processing", "voice_processing"):
        db.add(ConsentRecord(id=new_id(), tenant_id=tenant_b.id,
            student_user_id=users["student@sample.academy"].id, actor_user_id=users["student@sample.academy"].id,
            actor_type="adult_self", purpose=purpose, status="granted", notice_version="demo-v1",
            verification_method="synthetic-demo-only", created_at=now))

    for text_value, author, theme in QUOTE_CONTENT:
        db.add(Quote(id=new_id(), tenant_id=None, text=text_value, author=author, theme=theme, age_band="all", active=True))
    for item in KNOWLEDGE_CONTENT:
        db.add(KnowledgeItem(id=new_id(), tenant_id=None, title=item["title"], content=item["content"],
            category=item["category"], age_band=item["age_band"], source=item["source"], review_status="approved",
            reviewer="Synthetic demo content only; clinical and safeguarding review required before live use",
            content_version="demo-v1", published=True, vector_sync_status="pending"))

    write_audit(db, tenant_a.id, users["counsellor@demo.school"].id, "demo_seed_created", "tenant", tenant_a.id,
                metadata={"synthetic_data": True})
    write_audit(db, tenant_b.id, users["counsellor@sample.academy"].id, "demo_seed_created", "tenant", tenant_b.id,
                metadata={"synthetic_data": True})
    db.commit()
