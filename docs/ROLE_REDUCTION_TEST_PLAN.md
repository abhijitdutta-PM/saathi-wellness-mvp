# Role reduction test plan

Run this checklist against a disposable test database first. Do not use real student data for acceptance testing.

## 1. Automated checks

From the project root, with the project's virtual environment and dependencies installed:

```powershell
python -m compileall -q app scripts tests
python -m pytest -q
node --check app/static/app.js
```

Expected: compilation succeeds, all pytest tests pass, and JavaScript syntax check exits successfully.

## 2. Authentication and session retirement

Use synthetic accounts in a non-production instance.

- Sign in as Student, Teacher, and Counsellor. Each should work with valid credentials.
- Attempt sign-in as Parent/Guardian, School Admin, Safeguarding Lead, and Content Reviewer using any retained legacy accounts. Each must be denied with HTTP 403 and must not create a session.
- If a session cookie was issued before deploying this build for one of those four roles, call an authenticated endpoint such as `/api/me`. The request must be denied with HTTP 403.
- Verify `/api/system/demo-accounts` only lists Student, Teacher, and Counsellor accounts.
- Verify an invalid password still returns the normal generic authentication error and does not reveal whether an account exists.

## 3. Permission checks

- Counsellor can view the tenant's case queue, view case evidence, assign follow-up actions to an active Teacher or Counsellor, close a case with a required resolution note, view aggregate reports, view audit records, and view consent readiness.
- Teacher can view only cases assigned to them; direct requests for unassigned cases must return 404/403 and must not reveal evidence.
- Student can access only their own student features and consent/assent records.
- Teacher cannot publish knowledge items, view the audit log, change retention policies, create/release legal holds, or view all students' consent readiness.
- Counsellor can publish a resource only when the reviewer-attestation field is true. Treat this as an application attestation, not proof of independent clinical or safeguarding review.
- Counsellor consent readiness is status-only. Attempts to record guardian consent through `/api/consent` as a counsellor must return HTTP 403.

## 4. Safeguarding and notification routing

- Create a synthetic support case with an active Teacher assigned. The notification target should resolve to that assigned Teacher.
- Create an unassigned case. The fallback recipient should be an active Counsellor in the same tenant.
- Repeat with a legacy disabled-role user as the old assignee. That user must not receive a notification; the fallback should resolve to the active Counsellor.
- With no active counsellor email configured, the fallback endpoint should return HTTP 503 rather than silently choosing a generic mailbox.
- Verify notification payloads contain no student message text, journal text, or raw evidence.
- Verify n8n event delivery, retries, and health monitoring in the test environment; do not assume these are validated by unit tests alone.

## 5. Consent and data preservation

- Confirm existing guardian links, consent records, user IDs, audit records, and case/action records remain in the database after deployment.
- Confirm legacy user rows are not deleted or rewritten.
- Confirm a minor's wellbeing access remains blocked when required guardian consent and student assent are not effective.
- Do not treat student assent as a replacement for guardian consent. Before real minor data is processed, approve and implement a verified out-of-band guardian-consent process and an auditable evidence-recording path.

## 6. Retention and audit

- Retention policies should remain inactive unless explicitly approved for live data.
- Run a dry-run and verify it deletes nothing.
- Create a legal hold and verify held records are excluded from deletion candidates; release the hold and verify both actions are audited.
- Verify audit history retains the original actor IDs and role history; do not rewrite historical events to the new role model.

## 7. Multi-tenant regression

- Sign in as Counsellor in `demo-school` and verify no case, student, consent status, audit record, retention policy, or notification target from `sample-academy` is visible.
- Repeat with Teacher and confirm assignment scoping is preserved.

## 8. Deployment checks

- Back up the application directory and database before replacing files.
- Replace the application files from the supplied package and restart/recreate the application using the normal project method. A container image may need rebuilding if source files are baked into the image.
- No database migration is included or required by this patch. Do not run setup, bootstrap, Pinecone, or retention-execution scripts just to apply this role change.
- Run the checks above in staging before deploying to any live school.
