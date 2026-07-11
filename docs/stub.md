# stub.md — what's stubbed right now

Every place the code stands in for real external infrastructure: why it's stubbed,
the env flag that controls it, the file, and exactly what to swap for production.
**Nothing here is a bug** — these are deliberate seams so the logic is testable
without GPUs / TEEs / clouds / banks. The smoke suite (`lumaris_api/smoke_test.py`,
**231 assertions, all green**) drives the real code paths around these seams.

A stub is either **on** (safe/simulated) or **off** (calls the real thing). Fresh
deploys default the risky ones to **on** so the app runs without external creds;
you flip each to **off** as you wire that integration. See `template.env` /
`deploy/HARDENING.md`.

---

## 1. Payments — deposits (`PAYMENTS_MODE`)
- **Flag:** `PAYMENTS_MODE=sandbox` (default) vs `live`. File: `main.py`.
- **Stubbed behaviour:** `/deposit` mints test credit directly into the wallet;
  no card is charged. Bookings made in sandbox are tagged `test=true` and
  **excluded from GMV** (marketplace stats + admin + investor numbers).
- **Go live:** set `PAYMENTS_MODE=live`, set `STRIPE_API_KEY` +
  `PAYMENT_WEBHOOK_SECRET`, and route deposits through Stripe Checkout + webhook.

## 2. Payouts to sellers (`PAYOUT_STUB`)
- **Flag:** `PAYOUT_STUB=true` (default). File: `payout_providers.py`.
- **Stubbed behaviour:** `StubProvider` returns `{"status":"confirmed", ...}` —
  no real money leaves. Also the **sanctions/AML screen** (`screen_destination`)
  is a stub that always passes.
- **Go live:** set `PAYOUT_STUB=false` + provider creds (Tremendous / Circle /
  Stripe bank), and wire a real AML screen (Chainalysis/TRM) in
  `screen_destination`.

## 3. KYC / AML (payout onboarding)
- **File:** `main.py` (`/wallet/methods` verify flow, ~line 1374).
- **Stubbed behaviour:** verification is a stub screen in sandbox.
- **Go live:** wire Persona / Sumsub for identity, Chainalysis / TRM for chain
  screening, before real payouts.

## 4. Email / notifications (`NOTIFY_STUB`)
- **Flag:** `NOTIFY_STUB=true` (default). File: `notify_providers.py`.
- **Stubbed behaviour:** `StubEmailProvider` records the message, sends nothing.
- **Go live:** set `NOTIFY_STUB=false`, `EMAIL_PROVIDER` (ses|sendgrid|postmark)
  + that provider's creds. Adapters already exist.

## 5. Google sign-in (`GOOGLE_OAUTH_STUB`)
- **Flag:** `GOOGLE_OAUTH_STUB=true`. File: `main.py` (~639, 656).
- **Stubbed behaviour:** `/auth/google/login` short-circuits to the callback and
  logs in `demo@petabyte.market` — **do not run this in production**, it's an
  open door. Default in generated env is `false`.
- **Go live:** keep `false`, set `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`.

## 6. Object storage for backups (`S3_STUB`)
- **Flag:** `S3_STUB=true` (default). File: `utils.py` (~298, 311).
- **Real path (S3_STUB unset + creds):** `mint_presigned_put/get` generate **real
  presigned S3 URLs** via boto3 — the node uploads/downloads the snapshot directly
  and **never receives your S3 credentials** (only a short-lived permission to one
  object). Server-side encryption is on by default (`S3_SSE=AES256`, which works on
  both AWS S3 and DigitalOcean Spaces; set `aws:kms` for AWS KMS, empty to disable).
- **Stub path (`S3_STUB=true`):** returns a fake `*.s3.stub.local` URL so tests run
  without a bucket. This is the ONLY simulated part.
- **Go live:** unset `S3_STUB`, set `S3_BUCKET/S3_REGION/S3_ENDPOINT` +
  `AWS_ACCESS_KEY_ID/SECRET` (DO Spaces: set `S3_ENDPOINT` to the Spaces endpoint).
  Needed for the VM failover model (see vm-rental).

## 7. GeoIP data-residency (`GEOIP_STUB`)
- **Flag:** `GEOIP_STUB` set. File: `utils.py` (~255).
- **Stubbed behaviour:** region/country detection returns a fixed value, so
  `region_verified` and residency gating can be exercised without a GeoIP DB.
- **Go live:** unset the stub, provide a `GEOIP_DB` (MaxMind) path.

## 8. NiceHash idle-fallback pricing (`NICEHASH_STUB`)
- **Flag:** `NICEHASH_STUB=true` (default). File: `nicehash.py`.
- **Stubbed behaviour:** the pricing pull returns `{}`; tests inject the map into
  `reconcile` directly. The signing/reconcile logic is real.
- **Go live:** set `NICEHASH_STUB=false` + `NICEHASH_API_KEY/SECRET/ORG_ID`.

## 9. Confidential-computing / TEE attestation (`_verify_stub`)
- **File:** `utils.py` (~193-225).
- **Stubbed behaviour:** `/prove` verifies an **Ed25519-signed report** (real
  signature + nonce freshness checks) but **does not verify real hardware
  measurements**. So "confidential" today means "software-attested," not
  "TEE-attested." Honest software attestation, not a hardware root of trust.
- **Go live:** replace `_verify_stub` with a real verifier (AMD SEV-SNP / Intel
  TDX report verification against a trusted root + measurement allowlist:
  `TEE_MEASUREMENT_ALLOWLIST`, `TEE_TRUSTED_ROOT`). Tracked in isolation-roadmap
  Phase 2.

## 10. WireGuard tunnel apply (`WG_APPLY`)
- **File:** `utils.py` (~67).
- **Stubbed behaviour:** applying WG peer config is a **no-op unless
  `WG_APPLY=true`** and `wg` is on PATH with privileges. The API records config
  but doesn't touch the network in sandbox.
- **Go live:** `WG_APPLY=true` on a host with `wireguard-tools` — but note the
  real reachable-VM path (gateway + reverse tunnel + failover) is **not built
  yet** (see vm-rental.md / RLtest.md).

---

## Not a stub, but "not built yet" (so nobody confuses the two)

These aren't seams with a flag - they're **unbuilt** or **need real machines**:

- **Reachable interactive VM / SSH gateway / NAT traversal** - the control plane is
  built (`VMRoute`, `/launch`, `/vm/register_tunnel`, `/vm/{id}/route`, metering,
  failover), but the physical **frp gateway + reverse tunnel** are not - so a real
  buyer can't yet connect through a stable address. Runbook: `docs/vm-runbook.md`.
- **S3 checkpoint/restore agent loop** - presign is real (item 6); the agent-side
  snapshot-to-S3 + restore-on-failover loop needs a real node.
- **Real Docker/GPU execution** - the agent DOES run real `docker run` (GPU flags,
  model caching, ollama/vLLM) with Phase-1 isolation (`_isolation_flags`: gVisor
  `runsc` when present, `no-new-privileges`, `pids-limit`, memory cap). This needs a
  real GPU box + adversarial testing to verify; the automated suite still simulates
  the agent (signed results injected). See RLtest.md §23, §26.
- **Kata/Firecracker microVMs + real TEE attestation** - Phase 2 (isolation-roadmap).

**Now BUILT + tested in software (no longer gaps):** VM routing + stable opaque URLs,
failover (same URL, new node), **metering + extend + auto-stop-on-expiry**,
**demand-based auto-pricing** (opt-in, clamped to seller bounds + cloud reference),
**seller earnings dashboard**, DB indices on hot columns.

---

## How to see it live
`/marketplace/stats`, `/admin`, and the Trust Center reflect real (non-test) data.
Flip stubs off one integration at a time; the surrounding logic is already tested.
