# Production-readiness gates

Do not enable real student traffic until each gate has an owner and evidence of completion.

## Product / safeguarding
- [ ] Approved age-band UX and child-friendly notice.
- [ ] Named primary and backup safeguarding contacts per school, with coverage hours and response targets.
- [ ] Tested immediate-risk escalation route that does not depend on n8n.
- [ ] POCSO/statutory reporting procedure and local emergency guidance reviewed by counsel and safeguarding professionals.
- [ ] Qualified child/adolescent mental-health professional reviewed buddy prompt, resource library, and response examples.
- [ ] Synthetic scenario test set covers direct/indirect disclosures, sarcasm, negation, regional language, false positives, and model outage.

## Privacy / legal
- [ ] Data-processing role and contract for each school and vendor.
- [ ] Current DPDP Act/Rules commencement and applicability reviewed for the actual launch date and service model.
- [ ] Guardian identity and parental-authority verification implemented; demo boolean link is not sufficient.
- [ ] Consent notice, assent, withdrawal, rights/grievance, deletion, retention, legal-hold, and disclosure rules approved.
- [ ] AI/speech provider data region, logs, subprocessors, training, retention, access, and transfer terms reviewed.
- [ ] Pinecone index region and processing of student-derived query vectors reviewed; public serverless region list does not currently include India, so query vectors remain disabled until cross-border approval.
- [ ] Data protection impact/risk assessment and school contracts completed.

## Security / engineering
- [ ] Production `APP_ENV=production`, `SEED_DEMO_DATA=false`, secure cookies behind HTTPS, unique strong secrets, and no exposed DB/n8n ports.
- [ ] School IdP/SSO or secure onboarding, MFA for privileged users, recovery process, session revocation and staff offboarding.
- [ ] PostgreSQL row-level security integration tests pass against the exact deployed role and schema.
- [ ] Reviewed migrations, dependency/image scanning, secret scanning, threat model, penetration test, and API abuse/rate-limit review.
- [ ] AI outputs, embeddings, logs, and telemetry never use student content for provider training unless separately and properly approved.
- [ ] n8n Cloud credentials scoped, execution data retention restricted, workflow errors monitored, and tenant-specific SMTP/report recipients verified.
- [ ] n8n workflows do not call localhost or expose the local app; only backend-to-cloud outbound webhooks are configured.
- [ ] Backup encryption, off-site copy, key recovery, restore drill, RPO/RTO, and incident runbook validated.
- [ ] Retention policy legally approved and dry-run reconciled before deletion is enabled.

## Operations
- [ ] n8n success is distinguished from email delivery and human acknowledgement.
- [ ] On-call/coverage rota and fallback for unassigned cases validated in a live drill.
- [ ] Student-facing UI clearly states whether any human team is monitoring and how to obtain urgent help.
- [ ] Metrics do not rank students or treat lower disclosure as evidence of better wellbeing.
