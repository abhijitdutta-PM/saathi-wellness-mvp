# Incident response runbook (MVP template)

This is an operational template, not legal advice. Each school and the platform operator must name real owners, coverage times, escalation contacts, and statutory reporting responsibilities before live student use.

## Severity levels

- **P0 – immediate student safety risk:** A concerning disclosure or an urgent case not acknowledged within the school's approved response target. Follow the safeguarding runbook now; do not rely on ordinary IT email.
- **P1 – suspected privacy/security incident:** Suspected unauthorized access, cross-school data exposure, compromised staff account, leaked transcript/audio, or provider misuse.
- **P2 – service or workflow outage:** Conversation safety service, case dashboard, n8n notification delivery, speech provider, or database/backup service unavailable.
- **P3 – non-urgent defect:** Cosmetic or low-risk workflow issue with no known student safety or data-protection impact.

## Immediate response checklist

1. **Protect students first.** A safeguarding incident goes to the designated school safeguarding contact and the responsible human coverage path. If someone may be in immediate danger, use the school's approved emergency procedure and appropriate local emergency services. The app is not a monitored emergency service by itself.
2. **Contain access.** Disable a compromised account/session, revoke affected credentials, isolate the relevant integration or tenant if necessary, and stop unsafe outbound workflows. Do not delete records to hide an incident.
3. **Preserve evidence.** Preserve access/security logs, n8n execution metadata, incident timeline, relevant resource IDs, and configuration state. Avoid copying entire student messages into email or general incident channels.
4. **Assess the scope.** Identify which tenants, record categories, processors, users, and time window may be affected. Use tenant-scoped queries and audited privileged access.
5. **Notify the right owners.** Contact the platform security owner, privacy/legal owner, school safeguarding contact, and affected school contacts according to the approved plan. Counsel should determine any required CERT-In, DPDP, contractual, guardian, regulator, or other notification duties and timelines.
6. **Recover safely.** Rotate secrets and revoke sessions as required; validate patched code/configuration; restore from a tested backup only after confirming its integrity and tenant boundaries.
7. **Communicate accurately.** Do not promise that an incident is contained before verification. Student/guardian notices and regulator reports must be reviewed by the responsible legal/privacy owner.
8. **Learn and remediate.** Record root cause, scope, impact, response times, missed controls, corrective actions, owners, and due dates. Update tests and run a tabletop exercise.

## Incident contact register to complete before pilot

| Responsibility | Named owner | Backup | Contact / coverage |
|---|---|---|---|
| Platform incident commander | TBD | TBD | TBD |
| Security/engineering lead | TBD | TBD | TBD |
| Privacy/legal owner | TBD | TBD | TBD |
| Designated school safeguarding contact | Per school | Per school | Per school's approved coverage |
| Clinical advisor | TBD | TBD | TBD |
| Cloud/database owner | TBD | TBD | TBD |
| n8n/notification owner | TBD | TBD | TBD |

## Exercises before go-live

- Cross-tenant data leak tabletop.
- Compromised teacher/school-admin account.
- Urgent case with no assigned staff member.
- n8n down, SMTP failure, duplicate event, and dead-letter scenario.
- AI and speech provider outage or unexpected region/retention change.
- Accidental deletion and database restore.
- Guardian withdrawal request and record-retention/legal-hold decision.
