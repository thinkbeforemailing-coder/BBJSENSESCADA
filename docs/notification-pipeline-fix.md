# Notification Pipeline — Fixed (2026-08-08)

**Status:** Email is live and verified. WhatsApp is built but not yet configured (pending Meta template approval). SMS is deliberately unimplemented.

## What was wrong

`app/services/notification_sender.py` on the backend was a complete placeholder for all three channels — every "send" function printed a log line and unconditionally returned `True`. The rest of the pipeline (settings, history, the 5s scheduler, alarm-triggering, tenant scoping) was all real and correctly wired — only the very last step, actually contacting a provider, was fake.

**Impact discovered while investigating**: every alarm notification that had ever fired (email + WhatsApp, 3 each recorded as `"sent"` in `notification_history`) had silently gone nowhere. This predates any of this session's work — the pre-existing Low Frequency / High Voltage threshold alarms had been "notifying" nobody the whole time, with the database claiming success throughout.

## What was fixed (backend commit `25f4d6f`)

- **Email**: real SMTP send via `smtplib`, using Gmail SMTP with an app password. Gated on `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD` being set in `.env` — unconfigured means an honest recorded failure, not a fake success.
- **WhatsApp**: implemented against Meta's Cloud API directly. Business-initiated WhatsApp messages can't use freeform text, so this sends a pre-approved message template (assumed to be a single body parameter, e.g. `"BBJ Sense Alert: {{1}}"`, with the full formatted alarm message passed as that parameter) — a template needs to be created and approved in Meta Business Manager before this does anything. Recipient numbers are stripped to digits-only (Meta's API rejects a leading `+`). **Not live yet** — waiting on `WHATSAPP_PHONE_NUMBER_ID`/`WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_TEMPLATE_NAME` being set once that Meta-side setup is done.
- **SMS**: no provider chosen. Left unimplemented, but now honestly reports failure instead of the old stub's fake success. Zero live impact — no `NotificationSetting` currently has `sms_enabled=True`.

All new `Settings` fields default to `""` so existing `.env` files and CI keep working unchanged. Documented in `.env.example` (previously an empty file).

## A separate bug found while verifying it

The first live test send (to `admin@bbjsense.com`, the address on file for the admin account) returned success with no error, but never arrived. Root cause: `bbjsense.com` has **no MX records at all** — the domain's DNS was only ever configured for the web app (the A records from the earlier TLS work), never for receiving mail. `admin@bbjsense.com` had always been a placeholder string from initial account seeding, not a real mailbox — an SMTP send "succeeding" only proves the receiving server accepted the message for relay, not that the destination domain can receive mail at all.

Fixed by updating the live `NotificationSetting` for the admin account to a real address (`bbjsense@gmail.com`) — a one-time data correction, not a design change. The notification code already correctly uses whatever email is on file per user (populated at registration); this only fixes stale seed data that predated any real user registration.

## Verified live

Sent a real test email through `send_email_notification()` directly — confirmed received. Ran ruff/pytest, deployed, restarted the service, and did a 10-minute soak check with no errors in the logs.
