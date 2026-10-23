# Parent/guardian login retirement

Parent/guardian sign-in is permanently disabled in this application build, along with the School Admin, Safeguarding Lead, and Content Reviewer login personas. The backend blocks new login attempts and previously issued sessions for all four role values.

The application intentionally retains existing parent/guardian user rows, guardian links, consent records, and audit references. No database migration or deletion is performed. New demo seeds do not advertise or create the retired staff personas; the synthetic guardian record remains only to exercise historical consent relationships.

This change does **not** replace guardian consent for minors. Student assent alone is not treated as guardian consent. Before real minor data is processed, the school must implement an approved, identity-verified consent process and define how verified evidence is recorded and audited. The current counsellor view is status-only and cannot record guardian consent.
