# Saathi Student Wellness MVP

A development MVP scaffold for a multi-school student wellbeing platform. It includes tenant-scoped identity and role-based permissions, consent records, daily quotes and journaling, text conversations with a virtual buddy, Pinecone-backed retrieval over approved content, conservative rule-based safety routing, restricted support cases, optional voice transcription with transcript review, n8n Cloud workflow exports, audit logging, retention controls, and local backup/restore scripts.

> **Important safety limitation:** This is a development scaffold, not a clinically validated or production-ready service. Demo accounts/content are synthetic. Keyword safety rules can miss serious concerns and generate false alarms. Do not enter real student data into the demo. A live pilot requires legal/privacy and clinical/safeguarding review, verified identity and guardian onboarding, staffed response coverage, vendor due diligence, security testing, and exercised incident response.

## Design decisions

- **Local app and database:** The web application and PostgreSQL run on your Windows machine. Docker is optional; the native Windows setup below does not require Docker.
- **n8n:** Uses your cloud instance at `https://abhijitdutta-pm-new.app.n8n.cloud/`. This project does not deploy another n8n instance. The local app is preconfigured with outbound HTTPS webhook URLs for your cloud instance but automation is disabled by default; you enable it only after importing/publishing the workflows and setting up credentials. Your cloud workflows must not call `localhost` on your laptop.
- **Knowledge retrieval:** Pinecone stores approved-resource vectors only. Journal entries, student messages, transcripts, and counselling notes must never be upserted into Pinecone.
- **Embeddings:** In this implementation, a separate embedding endpoint/model creates vectors. Therefore the running app needs a Pinecone API key **and** an embedding provider configuration for real semantic retrieval. A local hash-based embedding exists only for synthetic demo testing and is not semantically meaningful.
- **Privacy gate:** The public Pinecone serverless region list currently includes US, EU, and Singapore regions but does not list India. The cloud/region is selected when an index is created and cannot be changed afterward. The MVP keeps Pinecone query vectors disabled and production startup requires a documented cross-border/privacy approval flag before sending student-derived query vectors to Pinecone. Review this carefully because Pinecone is part of the processing path. See [Pinecone's current index region documentation](https://docs.pinecone.io/guides/index-data/create-an-index).

## Applications required on your Windows machine

Required for native local development:

1. **Python 3.12 (64-bit)** — [official Python downloads](https://www.python.org/downloads/windows/).
2. **PostgreSQL 16 or later** — use the [official PostgreSQL Windows installer page](https://www.postgresql.org/download/windows/). Ensure `psql.exe` and `pg_dump.exe` are installed; add the PostgreSQL `bin` folder to PATH if the preflight checker cannot find them.
3. **A modern browser** such as Chrome or Edge.
4. **Internet access** to install Python packages and call the configured AI/Pinecone/n8n Cloud endpoints.

Optional:

- **Git** if you want source-control workflows; it is not required to run the ZIP.
- **Docker Desktop** is optional if you prefer container-based local development. It is not required with the native PostgreSQL setup in this README.
- **pgAdmin** is bundled by many PostgreSQL Windows installer options, but the app does not require it.
- No separate n8n installation is needed because you already have n8n Cloud.

This environment cannot inspect applications installed on your personal Windows computer. Use the included preflight script there; it reports missing local prerequisites.

## Native Windows setup (no Docker)

1. Download and extract the project ZIP to a folder such as `C:\Saathi\saathi-wellness-mvp`.
2. Open **PowerShell** in that folder. If scripts are blocked by your Windows policy, do not change a broad machine-wide execution policy; use an approved process for running the included project scripts.
3. Run the local preflight check:

   ```powershell
   .\scripts\check-local-prereqs.ps1
   ```

4. Install any missing required apps reported by the checker. Close and reopen PowerShell after installing Python or PostgreSQL so PATH and services refresh.
5. Create the virtual environment and install Python packages:

   ```powershell
   .\scripts\setup-local.ps1
   ```

6. Create the local app database and database role. The script prompts for your PostgreSQL `postgres` administrator password securely, generates a separate high-entropy application password, and writes only the application connection string to `.env`:

   ```powershell
   .\scripts\setup-local-db.ps1
   ```

7. Generate unique local app/integration secrets (this updates `.env` without displaying the secret values):

   ```powershell
   .\scripts\generate-local-secrets.ps1
   ```

8. Edit `.env` in a local text editor. Keep it private and never commit or send it. For demo browsing you can leave AI/Pinecone/voice credentials empty; Pinecone retrieval falls back to database lexical search until explicitly configured. Set the n8n webhook URLs only after the workflows are imported, credentials are configured, and the workflows are published.
9. Start the app:

   ```powershell
   .\scripts\run-local.ps1
   ```

   The launcher temporarily uses `Continue` for the native Uvicorn process only, because Windows PowerShell 5.1 can turn normal Uvicorn stderr `INFO` logs into `NativeCommandError` records even when `2>&1` is used. The script keeps strict error handling for its own pre-flight checks and checks Uvicorn's exit code after it stops. Wait for `Application startup complete` and `Uvicorn running on http://127.0.0.1:8000`. Keep this terminal open while using the app.

10. Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Health endpoint: [http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz). Stop the server with `Ctrl+C`.

Keep it bound to `127.0.0.1` for local development. Do not expose the laptop/database to the internet or forward port 8000 from your router. A local app that is asleep, offline, behind a changing IP, or blocked by a firewall cannot deliver outbound n8n events until it resumes network access.

### Student self-registration

This release adds student-only self-registration using single-use invitation codes. Registration creates a student account only; it does not create a case, assign staff, create guardian access, change consent, or trigger n8n. After the account is created, the student can sign in and use the existing student flows subject to the existing consent requirements.

Follow the full [Student Self-Registration Deployment Guide](docs/STUDENT_SELF_REGISTRATION_DEPLOYMENT.md) for backup, upgrade, invitation generation, verification, regression tests, and rollback. Create invitations only after the updated application has initialized its schema:

```powershell
.\.venv\Scripts\python.exe .\scripts\create-student-invites.py --tenant demo-school --count 10 --expires-days 30
```

The CLI prints one-time codes once and stores only SHA-256 digests. Distribute codes privately to their intended students. The guide documents important limits: this MVP does not perform email verification, and real deployment with minors requires an approved identity-verification and privacy/consent process.

### Synthetic demo accounts

The demo sign-in endpoint is available only in development and returns fictional accounts. For the main tenant use school code `demo-school`.

| Role | Email | Password |
|---|---|---|
| Student | `student@demo.school` | `DemoStudent-2026!` |
| Teacher | `teacher@demo.school` | `DemoTeacher-2026!` |
| Counsellor | `counsellor@demo.school` | `DemoCounsellor-2026!` |

Parent/guardian, School Admin, Safeguarding Lead, and Content Reviewer are disabled as login personas. Existing legacy user rows and consent/audit references are retained for historical integrity; old sessions are blocked. The supported human personas are Student, Teacher, and Counsellor. Counsellors receive the delegated case-management, aggregate-report, consent-status, resource-review, audit, and retention capabilities. Teacher access remains assignment-scoped. Guardian consent is not replaced by student assent: use an approved, independently verified consent process before real minor data is processed. The retired roles remain in historical database rows, but there is no configuration switch to re-enable their login personas. No migration deletes or rewrites consent data.

A second tenant `sample-academy` exists for isolation testing. Demo seed data is fictional. Do not use demo accounts for real records.

## Pinecone setup

### Do I need to provide the API key here?

No. You need a Pinecone API key for the application to authenticate, but **do not paste it into this chat**. Put it only in your local `.env` as `PINECONE_API_KEY`. The SDK reads it from the environment. The setup script reads `.env` and creates/checks the index.

The current implementation also uses a separate OpenAI-compatible embedding provider. Configure all of these in `.env` for real vector search:

```dotenv
PINECONE_API_KEY=your-key-entered-locally
PINECONE_INDEX_NAME=saathi-knowledge
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
PINECONE_DIMENSION=384
EMBEDDING_API_BASE_URL=https://your-approved-provider.example/v1
EMBEDDING_API_KEY=your-embedding-key-entered-locally
EMBEDDING_MODEL=your-model-that-returns-384-dimensions
```

The embedding model must return exactly the dimension configured in Pinecone. The default is 384; do not use a model that returns 768, 1024, or another size without changing the index and adapter consistently. The local hashing fallback is only for synthetic development and is not a real semantic embedding.

After adding the key locally, create/check the index using:

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_pinecone
```

The app synchronizes approved shared content on startup and queues tenant-approved knowledge for synchronization. It stores only resource IDs and safe metadata in Pinecone; actual knowledge text is refetched and re-authorized from PostgreSQL before it is returned to the buddy.

**Cross-border warning:** The currently published Pinecone serverless locations do not include India. The default `us-east-1` region is in the United States; Singapore is another listed choice on qualifying plans. The query path creates a vector from the student's question and sends that vector to Pinecone. While raw student conversations are not stored in Pinecone, query vectors can still be derived from sensitive personal content. Leave `PINECONE_QUERY_VECTORS_ENABLED=false` unless the privacy/legal team approves the data flow and the `PINECONE_CROSS_BORDER_APPROVED=true` setting is justified and documented. For a strict India-only residency requirement, do not use this Pinecone setup until an acceptable region/contractual solution is verified.

The chat endpoint is separate and has its own `AI_API_BASE_URL`, `AI_API_KEY`, and `AI_MODEL` settings. Voice transcription is separate too. Review each provider's processing region, retention, subprocessors, and training terms.

## Configure your n8n Cloud instance

Your instance is `https://abhijitdutta-pm-new.app.n8n.cloud/`. No local n8n installation is needed and the cloud webhook does not need to call back to your laptop.

1. Sign in to your n8n Cloud instance and import each JSON file under `n8n/workflows/`:
   - `01-event-notifications-and-followups.json`
   - `02-daily-aggregate-report.json`
   - `03-workflow-health-check.json`
2. For each Webhook node, create/attach an **HTTP Header Auth** credential. The header name must be `X-Wellness-Workflow-Key` and its value must match the locally generated `N8N_WEBHOOK_SECRET` in `.env`. Do not put this secret into chat.
3. Attach your approved SMTP/email credential to the email nodes in workflows 01 and 02. Configure an approved sender address and test delivery to a synthetic recipient. Email should contain generic notification copy or aggregate counts only, never transcripts, excerpts, or student names.
4. Test with synthetic payloads first. Publish each workflow only when credential setup and routing are correct. n8n distinguishes its test and production webhook URLs; the production URL is registered when the workflow is published. Copy the **Production URL** shown in each Webhook node rather than guessing it. See [n8n Webhook documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).
5. Copy the Production URL into the matching `.env` setting:

   ```dotenv
   N8N_WEBHOOK_URL=https://abhijitdutta-pm-new.app.n8n.cloud/webhook/wellness-events
   N8N_REPORT_WEBHOOK_URL=https://abhijitdutta-pm-new.app.n8n.cloud/webhook/wellness-daily-report
   N8N_HEALTH_WEBHOOK_URL=https://abhijitdutta-pm-new.app.n8n.cloud/webhook/wellness-health-check
   ```

   Confirm each URL against the Production URL shown by your own n8n workflow; if n8n displays a different path, use the displayed URL.
6. Keep `N8N_ENABLED=false` while setting up; do not start delivery to an inactive workflow. After all three URLs and credentials are correct and synthetic test events succeed, set `N8N_ENABLED=true` and restart the local app once.
7. `01` sends a generic event notification to the recipient already resolved by the local backend within that event's school tenant. `02` receives aggregate-only counts per tenant and validates that a tenant-specific approved report recipient exists in the event. `03` accepts an outbound backend heartbeat every 10 minutes; it proves this workflow ran, not that email delivery or human response works.

Do not configure n8n Cloud workflows to call `http://localhost:8000` or any private laptop IP. That address refers to the cloud worker itself or is unreachable from the public service. This design sends everything the workflow needs in the inbound event payload, avoiding a public API tunnel to your local machine.

## Voice support

Voice uses the browser microphone and an OpenAI-compatible `POST /audio/transcriptions` endpoint configured by `STT_API_BASE_URL`, `STT_API_KEY`, and `STT_MODEL`, with `VOICE_ENABLED=true`. The application sends audio to the configured provider only when the student explicitly records and submits it for transcription. The app does not retain raw audio: a transcript is returned for the student to review before sending, and only a submitted transcript is stored as a message. Browser read-aloud can use local speech synthesis where supported.

Voice transcription must remain disabled in any live environment until provider region, retention, training policy, notice, consent, and safety fallback are approved.

## Create a non-demo school

Public self-service tenant creation is intentionally not included. Once the app schema is initialized, create a tenant from a protected local terminal using strong unique credentials:

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_school.py `
  --slug greenfield-school `
  --name "Greenfield School" `
  --counsellor-email counsellor@greenfield.example `
  --counsellor-name "Primary Counsellor" `
  --counsellor-password 'Use-A-Unique-Strong-Password!2026' `
  --backup-counsellor-email backup-counsellor@greenfield.example `
  --backup-counsellor-name "Backup Counsellor" `
  --backup-counsellor-password 'Use-Another-Unique-Password!2026'
```

Do not use these example strings as real passwords. The bootstrap script does not implement institutional identity proofing, MFA, school SSO, guardian verification, or class-roster import.

## Teacher support-action progress and review

See [`docs/TEACHER_ACTION_PROGRESS_DEPLOYMENT.md`](docs/TEACHER_ACTION_PROGRESS_DEPLOYMENT.md) for the implementation scope, rollout steps, n8n checks, acceptance tests, and rollback procedure.

## Local backup and restore

Back up the database:

```powershell
.\scripts\backup-local.ps1
```

The script prompts for the PostgreSQL administrator password, creates a PostgreSQL custom-format dump, and does not save the administrator password to `.env`. The dump is not encrypted by the script. Encrypt it with approved tooling and move it to access-controlled off-device storage. Backups may contain highly sensitive records.

Restore is destructive to the named target database. Use a recovery environment and type the literal word `RESTORE` when prompted:

```powershell
.\scripts\restore-local.ps1 -BackupFile .\backups\saathi-example.dump
```

Verify database counts, tenant isolation, schema, and application startup after restore. Test restoration regularly.

## Tests and API

From PowerShell with setup completed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
node --check app/static/app.js  # optional; only if Node.js is installed
```

The test suite uses synthetic data and lightweight unit/static checks. It is not a clinical safety evaluation or full PostgreSQL integration test. Add and pass dedicated integration tests for row-level security, consent withdrawal, cross-tenant access, case permissions, event retries, Pinecone filtering, retention holds, and backup restoration before any real student pilot.

Development API docs: [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs). The docs are disabled in production.

## Production readiness gates

- [ ] Legal and privacy review of children's data, consent/assent, applicable DPDP requirements, school/vendor roles, cross-border processing, and retention.
- [ ] Named primary and backup counsellor/safeguarding contacts per school, with verified coverage, response targets, and urgent fallback.
- [ ] Clinician/content review of all resources and age-specific buddy behavior.
- [ ] Guardian verification, staff verification, MFA, secure recovery, school SSO/onboarding, and offboarding.
- [ ] Pinecone region and query-vector handling approved or replaced with a storage/search option meeting residency requirements.
- [ ] AI and speech providers reviewed for region, retention, subprocessors, and training.
- [ ] Tenant isolation/RLS, abuse/rate limits, secrets, logs, backup/restore, and incident response independently tested.
- [ ] n8n Cloud production webhooks published, Header Auth and SMTP credentials reviewed, execution logging limited, and synthetic delivery tests passed.
- [ ] Safety scenarios, including failures and missed staff acknowledgement, exercised by a responsible human team.

This is an MVP scaffold for supervised development, not a clinical product. Do not use real student data until the gates are resolved.


### Troubleshooting: Pinecone synchronization `NameError`

If startup logs show `NameError: name 'real_embedding_provider_configured' is not defined`, update `app/main.py` so the `app.ai` import includes `real_embedding_provider_configured`. This release includes that import fix. Stop the server with Ctrl+C and restart using `scripts\run-local.ps1`.

On Windows PowerShell, `python.exe : INFO: Started server process ... NativeCommandError` may be the shell surfacing Uvicorn's stderr log stream. If `Application startup complete` and `Uvicorn running on http://127.0.0.1:8000` appear, the server has started; investigate subsequent Python tracebacks as the actual application failures.


## GPT-6 Luna chat model setting

The chat adapter uses `max_completion_tokens` (not the deprecated `max_tokens`). For model IDs starting with `gpt-6`, it sets `reasoning_effort=low` and omits `temperature`, since reasoning models can reject temperature when reasoning effort is enabled. After replacing an existing installation, restart Saathi so the updated `app/ai.py` is loaded.
