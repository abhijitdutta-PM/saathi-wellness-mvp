# Data model and access boundaries

The authoritative schema is in `app/models.py`; RLS policies are applied by `app/db.py` at startup. The MVP uses SQLAlchemy schema creation for convenience. Production schema changes should use reviewed, versioned migrations.

## Main entities

- `tenants`: school-level tenant configuration and support instructions. This table is platform metadata and does not contain student message content.
- `users`, `user_sessions`, `guardian_links`, `consent_records`: tenant-scoped identity references, active session revocation, verified guardian relationship, and purpose-specific consent/assent history.
- `quotes`, `knowledge_items`: curated resources. `tenant_id IS NULL` means shared demo/platform resource; otherwise the content is scoped to a school. Approved knowledge embeddings are held in Pinecone namespaces: shared approved content uses `global`, while school-owned knowledge uses `school-<tenant_id>`. PostgreSQL remains the source of truth; content is fetched and re-authorized from PostgreSQL after vector search. Private student messages, journals, voice transcripts, and case notes are never indexed.
- `journal_entries`, `conversations`, `messages`, `voice_sessions`: student's own reflection and conversation records. Students can retrieve only their own rows through the backend; staff do not get a general journal endpoint.
- `safety_assessments`, `support_cases`, `case_actions`: derived assessment outcomes and human-owned follow-up. Cases store a limited relevant excerpt; counsellors may review case evidence, while teachers only see assigned, redacted case records.
- `audit_events`: metadata about actions and access; never include raw message content, audio, or secret values in audit metadata.
- `outbox_events`: durable asynchronous integration events. Payloads should contain only what the workflow needs; message content is not sent to n8n.
- `retention_policies`, `retention_holds`: tenant-specific policy settings, explicit approval state, and record-level holds.

## Tenant isolation enforcement

All tenant-owned tables have a `tenant_id` and an RLS policy equivalent to:

`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::text`

`FORCE ROW LEVEL SECURITY` is enabled. Shared quote and knowledge rows also permit `tenant_id IS NULL`. The authenticated backend sets the tenant context from a signed session claim, and its query paths add tenant filters as defence in depth. The pooled DB session context is reset in the request dependency teardown. The app DB role must never be a PostgreSQL superuser or have `BYPASSRLS`.

A PostgreSQL integration suite is still required before production. It should test cross-tenant reads, writes, joins, Pinecone tenant namespace filtering and re-authorization, subqueries, exports, session reuse after exceptions, background worker contexts, and restore behavior. Pinecone query-vector processing remains disabled until a documented privacy/cross-border review approves it.

## Key handling rules

- A journal entry is private by default. If a safety rule matches, or the student explicitly requests support, a limited excerpt can be placed in a restricted case. Tell students about this boundary before they use the service.
- AI messages do not become independent medical assessments. `safety_assessments` store rule/model versions and an evidence reference, not a diagnosis.
- Voice clips are processed transiently; raw recordings are not stored. Only a reviewed transcript submitted by the student is persisted as a message.
- Pinecone vector search is over approved educational resources, not a shared index of private conversations. Pinecone does not currently publish an India serverless region; student-derived query vectors must not be sent there until the cross-border/privacy review approves the flow.
- Audit records exclude full transcript content. Retention jobs preserve audit metadata and exclude held or case-referenced source content.
