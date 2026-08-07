# Newsletter setup (Mailgun mailing list)

The homepage newsletter form (`POST /newsletter/subscribe`) records every signup in
Postgres (the authoritative record) and syncs the address into a **Mailgun mailing list**.
This is separate from Titan, which continues to run the human mailboxes
(`info@`, `support@`); Mailgun handles programmatic/transactional/newsletter delivery.

## What already exists (no new secrets)

The integration **reuses** the existing Mailgun configuration — no new API key:

| Variable | Where | Purpose |
|---|---|---|
| `MAILGUN_API_KEY` | **GitHub Secret** | Same key used for transactional email. Never a plain Variable. |
| `MAILGUN_API_BASE` | code default (`https://api.mailgun.net`) | Honored so US/EU regions both work. Set to `https://api.eu.mailgun.net` for EU. |
| `NEWSLETTER_PROVIDER` | `ENV_VARS` (Variable) | `mailgun` (default). `mailchimp`/`none` also supported. |
| `NEWSLETTER_LIST_ADDRESS` | `ENV_VARS` (Variable) | The Mailgun mailing-list address signups are added to, e.g. `newsletter@petabyte.market`. This is the list var referred to elsewhere as `MAILGUN_NEWSLETTER_LIST`; the repo's canonical name is `NEWSLETTER_LIST_ADDRESS` (already in the manifest), so no duplicate variable is introduced. |

`MAILGUN_API_KEY` stays in GitHub **Secrets**; the two non-secret Variables live in the
consolidated `ENV_VARS` bundle. The signup form needs no other new configuration.

## One-time Mailgun-side setup

1. In the Mailgun dashboard, under **Sending → Mailing lists**, create a list.
   Suggested address: `newsletter@petabyte.market` (or on your sending subdomain, e.g.
   `newsletter@news.petabyte.market`).
2. Configure the list's **From name/address and Reply-To** on the list itself in Mailgun
   (the app does not set these). Optionally add a Mailgun Route to forward replies to
   `info@petabyte.market`.
3. Do **not** change MX records. Newsletter sending uses the Mailgun sending-domain/DNS
   already configured for transactional email; the Titan inbound-mail (MX) setup is
   untouched.

## Deploy

4. Set `NEWSLETTER_LIST_ADDRESS` to the list address in the `ENV_VARS` bundle (and
   `NEWSLETTER_PROVIDER=mailgun`). Ensure `MAILGUN_API_KEY` is present as a Secret. Deploy.

## Verify

5. Open `https://petabyte.market/`, enter a test address in the newsletter field, click
   **Subscribe** → you should see **“Thanks — you're subscribed.”**
6. Verify the member appears in the Mailgun list:
   ```bash
   curl -s --user "api:$MAILGUN_API_KEY" \
     "https://api.mailgun.net/v3/lists/newsletter@petabyte.market/members/pages" | jq '.items[].address'
   # EU: use https://api.eu.mailgun.net
   ```
7. Verify the authoritative DB record:
   ```sql
   SELECT email, status, mailgun_synced, source, created_at
   FROM newsletter_subscribers ORDER BY created_at DESC LIMIT 5;
   ```
   The address should appear once with `status = subscribed` and `mailgun_synced = true`.
8. Submit the **same address again** → still a friendly success, and **no** second row
   (idempotent; the `email` column is unique).

## Notes

- Postgres is the source of truth. If Mailgun is briefly unreachable, the signup is still
  recorded (`mailgun_synced = false`) and can be reconciled to the list later; the user
  still gets a clean success rather than an error they'd retry (which would email-bomb).
- The endpoint is IP rate-limited (anti-abuse / no email bombing) via the existing limiter.
- Signup is currently **single opt-in**. The schema (`status` includes `pending`, plus
  `confirmed_at`) is structured so double opt-in can be added later without a breaking change.
- Metrics: `petabyte_newsletter_subscribe_requests_total`, `_success_total{outcome}`,
  `_failures_total{reason}`. Emails are never used as metric labels and are hashed in logs.
