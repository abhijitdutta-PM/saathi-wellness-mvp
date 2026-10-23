# Teacher support-action progress and counsellor review deployment

## What changed
- Teachers assigned to an action can save timestamped progress: work performed, outcome, further concerns, and next step.
- Teachers can submit progress for counsellor review. Submission changes the action to `submitted_for_review`; teachers cannot directly mark an action complete.
- Counsellors can approve completion, request more work, or reopen an action. Completion is timestamped only when approved.
- Progress entries are stored in `case_action_progress` and remain visible in the action history after refresh and re-login.
- Progress-submission notifications use the existing `case.updated` event contract; email copy remains generic and does not contain student details.
- The new progress table is included in tenant RLS enforcement.

## Apply safely
1. Stop the running app / deployment before replacing code. Keep the existing release available for rollback.
2. Take a database backup using the existing `scripts/backup-local.ps1` (Windows) or `scripts/backup.sh` (Linux/macOS) workflow and verify that the backup file exists.
3. Extract this ZIP into a new directory; do not extract over the live directory. Compare the `.env` and deployment-specific configuration with the current release and carry forward secrets securely. Do not copy `.env` into source control or share it.
4. Deploy the updated source and restart the application using the deployment method documented in `README.md` / `docker-compose.yml`.
5. On application startup, `init_schema()` creates the new `case_action_progress` table, and `apply_rls()` enables and forces tenant RLS. Confirm startup logs show schema initialization completed successfully. For a managed production database, run this in a maintenance window and verify table/RLS state before opening access.
6. No n8n workflow JSON change is required for this feature: review notifications use the existing `case.updated` event type accepted by workflow 01. Ensure the deployed workflow is active and the backend outbox worker can reach its webhook. Run a test event and confirm delivery in n8n execution history. Do not replace the existing event-validation node with a simplified validator.
7. Log in as a counsellor, assign an action to a test teacher, then log in as that teacher and exercise the workflow below.

## Acceptance test
1. Teacher opens the assigned case and sees the student name/class, action, due date, status, and progress form.
2. Teacher saves progress. The status becomes `in progress`; progress appears in history immediately. Refresh and sign out/in: the entry must still be visible.
3. Teacher submits another progress entry for review. Status becomes `submitted for review`; teacher cannot directly set `completed` via `PATCH /api/actions/{id}`.
4. Counsellor opens the case and sees the submitted entry. Counsellor approves: status becomes `completed` and completion time appears.
5. Repeat with “Request more work”: status becomes `changes requested`; teacher can add progress and submit again.
6. Counsellor reopens an action and verifies it is available to the assigned teacher again.
7. Verify a teacher cannot access an action assigned to another staff member, cannot approve their own completion, and cannot cross school/tenant boundaries.
8. Verify outbox/n8n notifications contain no student name, class, case summary, progress text, or other student narrative.

## Rollback
1. Stop the updated app.
2. Restore the prior application release and restore the database only if a migration or application failure requires it. The added table is additive; do not drop it as part of a normal rollback because it may contain submitted progress.
3. Confirm the prior version starts cleanly, then investigate using logs and a copy of the backup.

## Important operational note
This is an implementation package, not a confirmation of a live deployment. Validate the school’s safeguarding process, access permissions, backup restoration, production database behavior, and n8n delivery in the target environment before enabling real student records.
