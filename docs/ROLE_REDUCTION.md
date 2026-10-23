# Saathi role reduction

## Supported login personas
- **Student:** personal wellbeing features and own consent/assent actions.
- **Teacher:** assigned support items only; no access to unassigned cases or raw case evidence.
- **Counsellor:** case management, human-risk coordination, content review/publication, aggregate reports, consent-readiness status, audit viewing, retention policies, and legal holds.

## Disabled personas
Parent/guardian, School Admin, Safeguarding Lead, and Content Reviewer are not supported as interactive login personas. The backend blocks both new logins and already-issued sessions for these roles. Existing database rows, guardian links, consent history, and audit attribution are intentionally retained; no destructive database migration is included.

## Safety and governance boundaries
- Removing the Safeguarding Lead persona does **not** remove the school's safeguarding duty. Each school must name a trained primary and backup human contact, coverage hours, response targets, and an external escalation route. The counsellor role in this MVP is the application-level owner, not a claim of professional qualification.
- Counsellors may view consent readiness but cannot create guardian consent records. Parent login being disabled is not a substitute for valid guardian consent for minors. An approved, verified out-of-band process and audited evidence import/recording procedure must be defined before real minor data is used.
- Content publication is restricted to counsellors and requires the existing reviewer attestation. That checkbox is not equivalent to clinical/safeguarding approval; define an independent review process for live use.
- Retention policies remain off by default. Counsellor access to retention and holds is broad and should be restricted further to named, trained personnel before production if the organization requires separation of duties.
- n8n notifications route to an assigned active staff member first and to an active counsellor only as the tenant-scoped fallback. If no eligible recipient exists, the API returns a failure rather than silently sending to a generic mailbox.

## Migration behavior
No existing users are deleted or re-written. Disabled legacy users are denied access on their next authenticated request and at login. If an old deployment has active sessions, restarting the app is required to load this code; the request guard blocks old role sessions. Historical records continue to refer to their original actor IDs.
