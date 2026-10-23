# Student registration 409 troubleshooting

This build flushes the student row before adding the registration audit event, while keeping student creation, audit logging, and invitation redemption in the same transaction. If the transaction fails, all changes are rolled back. Integrity errors are logged with a traceback and return HTTP 409; other persistence failures are logged and return HTTP 500.

## After deploying

1. Restart the app and reproduce the registration once.
2. Read the terminal running `scripts\\run-local.ps1` (or the hosting platform's application logs).
3. Find `Student registration integrity failure` or `Student registration persistence failure` at the matching timestamp.
4. Share the traceback text with secrets, passwords, invitation codes, and personal student data removed.
5. Do not reset the database or manually delete rows. If registration succeeded despite a browser error, try signing in with that email before retrying.

The endpoint does not log the submitted password or invitation code.
