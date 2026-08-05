# Sender logo in Gmail (BIMI) — setup guide

## What this is about

When a Petabyte email arrives in Gmail, the round icon next to **Petabyte
Support** shows a generic coloured letter (a purple "P") instead of our logo:

```
(P)  Petabyte Support — Petabyte Mailgun Integration Test
 ^ Gmail's auto-generated placeholder avatar
```

**That avatar is not controlled by the email HTML, the template, or Mailgun.**
Nothing we send in the message body can change it. It is the *sender identity*
image, and the only standard way to put a brand logo there for external
recipients (a personal `@gmail.com`, etc.) is **BIMI** — Brand Indicators for
Message Identification.

> The molecule logo *inside* the email body is separate and already renders
> (it is embedded inline as `cid:petabyte-logo.png`). This document is only
> about the **sender avatar**.

BIMI is a DNS + certificate configuration on the `petabyte.market` domain. It is
not a code change — the one code-side artefact (the logo file) is already in this
repo and served; everything else below is done in the DNS zone and with a
certificate authority.

---

## The hard truth about Gmail specifically

Many mailbox providers (Yahoo, Apple Mail, Fastmail) will show a BIMI logo with
just a hosted SVG + a DNS record. **Gmail will not.** Gmail requires the BIMI
record to reference a **verified mark certificate**:

- **VMC** (Verified Mark Certificate) — requires a **registered trademark** for
  the logo. Issued by DigiCert or Entrust. Roughly **~$1,000–1,500 / year**.
- **CMC** (Common Mark Certificate) — for logos that are **not** trademarked
  (e.g. in use for 12+ months). Also issued by Entrust/DigiCert, similar cost.
  Gmail began honouring CMCs in 2024.

So the realistic path to "our logo in the Gmail avatar" is: **enforce DMARC →
publish the BIMI record → buy a VMC or CMC**. Without the certificate, Gmail
keeps showing the letter avatar no matter what else is in place.

There is no free/instant way to make our logo appear in an external Gmail
recipient's avatar. Anyone claiming otherwise is describing the Google Workspace
profile-photo path (below), which does **not** apply to external recipients.

---

## Prerequisites (must all be true before BIMI does anything)

1. **SPF passes and is aligned.** ✅ Already the case — the integration test
   email showed `mailed-by: petabyte.market`.
2. **DKIM passes and is aligned.** ✅ Already the case — the test email showed
   `signed-by: petabyte.market`. (This is Mailgun's DKIM on the sending domain.)
3. **DMARC at enforcement.** ⛔ This is the usual missing piece. BIMI is ignored
   unless DMARC is published with `p=quarantine` or `p=reject` (**not**
   `p=none`), applied to the whole domain.

### Check what you have today

I could not read live DNS from the build environment (outbound DNS is blocked
here). Check these yourself — e.g. at https://mxtoolbox.com or with `dig`:

```
dig +short TXT petabyte.market            # look for "v=spf1 ... include:mailgun.org ..."
dig +short TXT _dmarc.petabyte.market     # look for "v=DMARC1; p=..."
dig +short TXT default._bimi.petabyte.market
```

---

## Step 1 — Get DMARC to enforcement

If `_dmarc.petabyte.market` is absent or `p=none`, move it to enforcement.
Ramp up so you don't silently drop legitimate mail:

1. Start at monitoring and collect reports for ~1–2 weeks:
   ```
   _dmarc.petabyte.market  TXT  "v=DMARC1; p=none; rua=mailto:dmarc@petabyte.market; fo=1"
   ```
2. Confirm from the aggregate reports that all your legitimate senders (Mailgun,
   Google Workspace if used, any others) pass SPF **and** DKIM aligned to
   `petabyte.market`.
3. Then enforce (BIMI requires this):
   ```
   _dmarc.petabyte.market  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc@petabyte.market; adkim=s; aspf=s"
   ```
   `p=reject` is stronger and also satisfies BIMI. Do not enforce before step 2
   passes, or you will quarantine your own mail.

---

## Step 2 — The BIMI logo (already in this repo)

BIMI requires the logo as **SVG Tiny 1.2 Portable/Secure (SVG Tiny PS)**, square,
with a solid background and a `<title>`. That file already exists and is served:

- File in repo: [`lumaris_api/static/petabyte-bimi.svg`](../lumaris_api/static/petabyte-bimi.svg)
  (white Petabyte molecule on the brand-dark background, `baseProfile="tiny-ps"`).
- Served at: **`https://petabyte.market/static/petabyte-bimi.svg`**
  (whitelisted in `main.py`; a smoke test asserts it is served as
  `image/svg+xml`).

Validate it before publishing the DNS record — e.g. the BIMI Group inspector at
https://bimigroup.org/bimi-generator/ or https://svg.bimigroup.org — and confirm
it reports a valid SVG Tiny PS.

> If the mark ever changes, regenerate this file, keep it square + SVG Tiny PS,
> and re-validate. The certificate in step 4 is tied to the exact logo, so a
> logo change means re-issuing the certificate.

---

## Step 3 — Publish the BIMI DNS record

Once DMARC is enforced and the SVG validates:

```
default._bimi.petabyte.market  TXT  "v=BIMI1; l=https://petabyte.market/static/petabyte-bimi.svg; a=https://petabyte.market/static/petabyte-vmc.pem"
```

- `l=` — the SVG URL (above; already live).
- `a=` — the certificate URL (the `.pem` you get in step 4). Host it over HTTPS
  on the same domain. **Until you have the certificate, Gmail will not show the
  logo** — you can publish the record with only `l=` and non-Gmail clients that
  don't require a certificate may show it, but Gmail needs `a=`.

---

## Step 4 — Buy a VMC (or CMC) — required for Gmail

1. Choose an issuer: **DigiCert** or **Entrust**.
2. Provide the same square logo (they accept SVG Tiny PS). For a **VMC** you must
   show a **registered trademark** for the mark (national trademark office
   registration). If the logo isn't trademarked, ask for a **CMC** instead.
3. Complete organisation validation (similar to an OV/EV cert — they verify the
   company is real and that you control the domain and the mark).
4. They issue a `.pem` (the mark certificate). Host it at the `a=` URL from
   step 3 — e.g. add `petabyte-vmc.pem` next to the SVG and whitelist it in the
   `/static` route the same way `petabyte-bimi.svg` is.
5. Re-check `default._bimi.petabyte.market` with a validator; then send yourself
   a test email. Gmail avatar propagation can take hours to a couple of days.

---

## Interim / alternative options

- **Google Workspace profile photo / organisation logo.** If `support@` (or the
  people sending) are on a Google Workspace tenant for `petabyte.market`, an
  admin can set an org logo / the user can set a profile photo. Gmail then shows
  it **but only to recipients in the same Workspace org** (and some Google
  contacts). It will **not** reliably show to an external `@gmail.com`. So this
  helps internal mail only — it does not solve the case in the screenshot
  (external recipient).
- **Do nothing.** The letter avatar is cosmetic; deliverability, DKIM, and SPF
  are already correct. BIML/VMC is a brand-polish investment, not a delivery
  fix.

---

## Summary / checklist

| Step | Where | Status |
|------|-------|--------|
| SPF aligned | DNS | ✅ done (Mailgun) |
| DKIM aligned | DNS | ✅ done (`signed-by: petabyte.market`) |
| BIMI SVG (Tiny PS) authored + served | repo / app | ✅ done — `/static/petabyte-bimi.svg` |
| DMARC at `p=quarantine`/`reject` | DNS | ⛔ verify / add (step 1) |
| `default._bimi` TXT record | DNS | ⛔ add (step 3) |
| VMC or CMC certificate | CA + DNS `a=` | ⛔ purchase, **required for Gmail** (step 4) |

Steps 1, 3, and 4 are DNS/certificate actions on `petabyte.market` and must be
done by whoever controls the domain and budget — they are outside the codebase.
The repo already provides the validated logo asset and serves it at a stable
HTTPS URL so the DNS record can point at it.
