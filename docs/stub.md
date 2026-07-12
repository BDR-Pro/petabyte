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

## Frontend honesty rules (enforced by tests)

The public site must never claim more than we can back up. Locked in `smoke_test.py`:
- **Savings are like-for-like or absent.** `cloud_reference_for()` maps a GPU to its own
  class's on-demand rate. An unknown GPU returns `None` and we show *no* savings figure —
  never a global H100 rate quoted against a 4090 (that manufactures a fake ~97% discount).
- **No empty metrics.** The landing page shows real inventory; counters only appear when
  non-zero. An empty `—` reads to a visitor as "this platform does not work".
- **Listings are opaque handles.** Public ids are random (`jhk32mcb11tw`), never the
  sequential int — so listings can't be enumerated and our volume isn't leaked.
- **/security states what is NOT live** (hardware-backed attestation, benchmark
  verification, external audit, formal data residency) alongside what is.

## Hardening (added after the architecture review)

**Now enforced in code + tests:**
- **Security headers** on every response: CSP, `nosniff`, `X-Frame-Options: DENY`,
  Referrer-Policy, Permissions-Policy, HSTS on https, `no-store` on authenticated responses.
- **Request IDs**: every response carries `X-Request-ID`, logged server-side. Users can
  quote it; we can find the exact request.
- **Structured errors**: `{"error":{"code","message","request_id"}}` with stable codes
  (`INSUFFICIENT_BALANCE`, `NOT_FOUND`, `RATE_LIMIT_EXCEEDED`...). Stack traces never
  reach a caller. Legacy `detail` field kept so existing clients don't break.
- **Rate limiting**: failed `/login` throttled per **(IP, username)** — guessing one
  account cannot lock out a colleague behind the same office NAT, and only FAILED
  attempts burn budget. Signup + withdraw throttled per IP.
- **Health split**: `/health/live` (process) vs `/health/ready` (database).
- **`/api/v1` resource API** (`/api/v1/deployments`, `/marketplace/nodes`, `/wallet`...)
  aliased onto the same handlers as the legacy verb routes — one implementation, no drift.
  This is what an OpenAPI-generated client should target.

**Verified already correct (no change needed):**
- Agent builds Docker commands as **argv lists** — no `os.system`, no `shell=True`,
  no string concatenation. Not injectable.
- CORS is an explicit allow-list, never `*` with credentials.
- Ledger (`LedgerEntry`), organizations, idempotency keys, price snapshot on booking,
  and atomic capacity reservation (conditional UPDATE) all already exist.

**Top remaining architectural debt — money is stored as `Float`.**
Balances/escrow/earnings are `Column(Float)`. Conservation is proven to the cent by
`adversarial_test.py`, but float is the wrong type for money and the right time to fix it
is *before* real funds. Plan: migrate to `NUMERIC(20,8)` (Postgres) + Python `Decimal`,
expand-and-contract (add column -> dual-write -> backfill -> read new -> drop old).

## Money is Decimal, not float (migration complete)

All monetary columns are **`NUMERIC(20,8)`** and all monetary arithmetic is Python
`Decimal`. Floats are gone from the money paths.

- `db.Money` = `Numeric(20, 8)`; helpers `D()` (lift to Decimal via `str`, never through
  binary float), `q()` (quantize to 8dp), `qc()` (quantize to cents). `PLATFORM_TAKE_RATE`
  is a Decimal.
- **Postgres**: true exact NUMERIC. **SQLite** (tests only): no decimal type, so SQLAlchemy
  round-trips through float — tests verify the *logic* exactly; exact *storage* is a
  Postgres property. Re-run `adversarial_test.py` against Postgres before real money.
- Non-money floats are deliberately still `Float`: benchmark tokens/sec, latency sums,
  utilization ratios, mining hashrate, frame ranges. Those aren't accounting.
- Router *scoring* coerces price to float — a ranking heuristic, not accounting.

**Guards in the suite (so this can't regress):**
- every money column is `Numeric`, never `Float`
- `PLATFORM_TAKE_RATE` is a `Decimal`
- `fee + payout == gross` exactly
- 10,000 micro-charges of $0.001 sum to **exactly** $10 (float drifts by ~1e-13)
- `adversarial_test.py` now asserts **exact** conservation (`==`), not "within a cent"

## The reachable-VM loop is now proven in software

`lumaris_gateway/` contains a working reverse-tunnel gateway and an end-to-end test
(`tunnel_test.py`, **12/12**, stable over repeated runs) that proves the one thing that
had never been tested:

- two nodes traverse NAT with **outbound-only** control channels (no inbound port, ever)
- a workload bound to **127.0.0.1** on a node is reached by a buyer who knows **only the
  opaque VM handle**
- node A is killed -> the real reaper fails the VM over -> **the same handle** reaches
  node B, and the buyer's connection string is byte-identical
- the event timeline records `created -> tunnel_registered -> migrated -> tunnel_registered`

This exercises the real API, the real reaper, and the real `/vm/register_tunnel` and
`GET /vm/{id}/route` seams. No mocks in the path that matters.

**Still needs real machines:** the same flow across the internet, a real home router, and
real SSH — using **frp** + **sshpiper** rather than our reference gateway. Configs and the
exact pass/fail criteria are in `docs/vm-runbook.md`. `gateway.py` is a reference and a CI
harness; it is not hardened to serve production traffic (frp is).

## P0 fixes from the backend architecture review

**1. Maintenance no longer runs in every API worker.**
Gunicorn runs N workers; the reaper lived inside the app, so N workers meant N reapers
racing to fail over the same node and settle the same booking every 20s. Now exactly one
process does the work, guarded by a Postgres advisory lock (`pg_try_advisory_lock`), and
`deploy/lumaris-reaper.service` runs it as a dedicated scheduler with
`REAPER_DISABLED=true` on the API workers.

**2. Maintenance can no longer fail silently.**
`except Exception: pass` meant the reaper could be dead for weeks while the API reported
healthy — VMs never expiring, dead nodes still listed, bookings never settling. Every
failure is now logged, and `/health/ready` exposes
`maintenance.{is_leader,last_success_age_s,failures,stale}`. **Alert on `stale == true`.**

**3. API-key scopes are default-DENY.**
`scopes == []` used to mean *full access* (back-compat). That turns any parsing bug, bad
migration, or truncated column into root. Now: an empty scope list is denied; `"*"` is an
explicit, deliberate privilege; new keys are minted with real scopes (`node`, `jobs` — a
machine in someone's living room cannot move money). Legacy keys can be honoured only via
an explicit `LEGACY_KEYS_FULL_ACCESS=true` migration flag. Scopes gate **API keys only** —
a JWT session is an authenticated human and is governed by role/ownership checks instead.

**4. `X-Forwarded-For` is only trusted from a declared proxy.**
The old code trusted the header unconditionally, so any client could send
`X-Forwarded-For: 1.1.1.1` to defeat rate limiting and fake their country for the
data-residency gate. Now only peers in `TRUSTED_PROXIES` (default `127.0.0.1,::1`) may set
it. **Set `TRUSTED_PROXIES` to your nginx address on the droplet.**

**5. Production refuses to boot with stubs on.**
`ENVIRONMENT=production` + any of `GOOGLE_OAUTH_STUB`, `PAYOUT_STUB`, `S3_STUB`,
`LEGACY_KEYS_FULL_ACCESS`, `PAYMENTS_MODE != live`, or a default `SECRET_KEY` → the app
raises at startup instead of quietly serving a demo as if it were a marketplace.

### Where the review was wrong about us
- **API keys are already SHA-256 hashed**, not reversibly encrypted (the Fernet usage it
  spotted is per-task backup encryption, which genuinely does need to be reversible).
- Atomic reservation, idempotency, price snapshots, and organizations already existed.

### Honest remaining gaps (not yet done)
- ~~The ledger is an append-only journal, not strict double-entry.~~ **DONE** — see below.
- **Marketplace filtering happens in Python**, not SQL — fine at 20 nodes, painful at
  10,000. Needs SQL filtering, a reputation projection table, and cursor pagination.
- **`main.py` / `db.py` are too large** and should be split into domain modules.
- ~~CI runs SQLite~~ **DONE** — the whole suite now runs against Postgres too. See below.


## The ledger is now real double-entry

`LedgerTx` (a financial event) + `LedgerEntry` (its legs). **The only door into the ledger
is `post()`, and it refuses to write when debits != credits** — there is deliberately no
API for appending a single-sided entry. An unbalanced transaction raises
`UnbalancedTransaction` and the operation fails loudly rather than losing a cent.

**Accounts:** `buyer_available:<uid>`, `escrow:<booking_id>`, `seller_earnings:<uid>`,
`org_available:<oid>`, `platform_revenue`, and `external:{payments,payouts,mining}`.
Balance = `SUM(credits) - SUM(debits)`. Because money entering the system debits an
`external:` account, **the whole ledger sums to zero.**

**Every money movement is now a balanced transaction:** deposit, org deposit, escrow hold,
extend, metered settlement (escrow -> seller + platform + refund), full settlement, full
refund, idle-mining income, and **payouts — which previously never touched the ledger at
all; seller earnings simply vanished from the books when withdrawn.**

**`users.balance` / `users.earnings` / `platform.revenue` are now caches.** The ledger is
the source of truth. If they ever disagree, the ledger is right — and the tests prove they
don't:

- every transaction balances; the whole ledger sums to zero
- every wallet, every seller's earnings, and platform revenue are **reconstructible from
  the ledger** (0 mismatches)
- settled bookings **drain escrow to exactly zero**
- transactions always have entries on both sides
- `post()` **refuses** an unbalanced write
- and all of the above still holds **after the concurrent-abuse adversarial test**

Reconstruct any balance with `account_balance(db, acct_buyer(uid))`; audit the whole book
with `ledger_is_balanced(db)`.


## Tests now run on Postgres, not just SQLite

SQLite was the wrong engine to be confident on. It has **no decimal type** (so
`NUMERIC(20,8)` round-trips through a float — "exact money" was unproven no matter how
green the suite looked), it **serialises writers** (so whole classes of race condition
cannot occur), and it has **no advisory locks** (so the maintenance leader election that
stops every gunicorn worker running its own reaper was a silent no-op).

```bash
cd lumaris_api
./run_tests.sh              # sqlite only — fast inner loop
./run_tests.sh --postgres   # both engines — what CI runs
```

`.github/workflows/tests.yml` runs both. **Results on real Postgres 16:**

| suite | result |
|---|---|
| smoke | **306 passed** |
| adversarial (money + races) | **14 passed** |
| postgres-only invariants | **12 passed** |
| tunnel (NAT + failover) | **12 passed** |

`postgres_test.py` asserts what SQLite structurally cannot:
- `users.balance` really is `NUMERIC(20,8)` **in the database**, precision/scale enforced
  by Postgres itself
- `0.1 + 0.2` stored and re-read from Postgres is **exactly** `0.3`, and comes back a
  `Decimal`, not a float
- 200 × `$0.001` accumulated **inside Postgres** is exactly `$0.20`
- **`pg_try_advisory_lock` elects exactly ONE leader out of 4 simulated workers** — this
  is the "4 gunicorn workers = 4 reapers" fix, and it had never actually been exercised
  because it is a no-op on SQLite
- the lock is reacquirable after the leader exits (no permanent deadlock)
- **50 threads racing to debit $10 from a $100 wallet: exactly 10 win**, balance lands on
  exactly `$0.00`, never negative — a genuine parallel race, not a serialised queue
- the double-entry ledger balances and refuses unbalanced writes on the real engine too
