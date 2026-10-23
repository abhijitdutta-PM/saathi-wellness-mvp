# Saathi case assignment and notification fix

## Changes

- Added a counsellor-only case-owner assignment endpoint: `PATCH /api/cases/{case_id}/assignment`.
- Added a case-owner selector in the counsellor case detail screen.
- The teacher case queue already filters by the case's `assigned_to_user_id`; assignments now update that field through the supported UI and API.
- Teachers see only follow-up actions explicitly assigned to them in case details; counsellors retain the full action list and evidence view.
- Case assignment queues a minimal `case.updated` outbox notification for the assigned staff member when they have an email address.
- Assigning a follow-up action queues a `followup.assigned` notification. The n8n workflow accepts this event type.
- Notification emails contain no student name, evidence excerpt, journal text, or conversation content.

## Email prerequisites

Queueing an event is not the same as delivering an email. For delivery, configure the approved SMTP credential in n8n, configure the matching Saathi webhook URL and shared key, activate the n8n event workflow, and set the application environment variables (`N8N_ENABLED`, `N8N_WEBHOOK_URL`, and `N8N_WEBHOOK_SECRET`) appropriately. If an assignee has no email address, the assignment is saved but no email event is queued; the UI reports this.

## Validation performed

- `python -m pytest tests -q`: 18 passed
- `node --check app/static/app.js`: passed
- `python -m py_compile app/main.py app/services.py`: passed

These are code-level checks only. End-to-end browser, database, n8n, and SMTP delivery still need to be tested in the deployment environment.

## Security packaging note

This release archive intentionally excludes `.env`, `.venv`, `.git`, Python bytecode, and pytest caches. Copy settings into your local `.env` from `.env.example` and keep actual credentials private.

## Student identity and standard/class display enhancement

- Added optional `users.school_class` to store a school standard/grade and optional section (for example, `Standard 9, Section B`). Existing records are migrated with `NULL`; the migration does not invent real student data.
- Case list and case detail now show the student's display name and standard/class to staff who are already authorized to read that case. Teachers still see only cases assigned to them, and sensitive evidence remains counsellor-only.
- Counsellors can update a student's standard/class from the case detail screen. The API is counsellor-only, tenant-scoped, restricted to active student accounts, and audited.
- Fictional demo student `Amara Student` has `9-B` as a demonstration value only.
- For existing students, sign in as a counsellor, open a case, and use **Update standard / class** in the Student details section. Leave it blank if unknown; the UI will say `Class not recorded` rather than guessing.

## Validation performed after student identity enhancement

- `python -m pytest tests -q`: 18 passed
- `node --check app/static/app.js`: passed
- `python -m py_compile app/main.py app/models.py app/db.py app/services.py`: passed

The tests above are code-level checks. A live database migration and role-based browser test still need to be run in the deployment environment.
