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

## Pilot safety rails (built before letting a stranger's GPU on the network)

**1. Kill switch.** `POST /admin/bookings/pause {"paused":true,"reason":"..."}` stops NEW
bookings immediately and returns `503 BOOKINGS_PAUSED` + `Retry-After`. **Running rentals
are untouched and settle normally** — stopping the world must never destroy someone's
six-hour render. Enforced at the one chokepoint every booking path converges on, and
checked *before* capacity is reserved or money moves. Audited.

**2. Egress policy — this one protects the SELLER, not the buyer.**
A rented container runs on a stranger's home connection, behind their IP. If a workload
spams, port-scans, or joins a botnet, it is the **host** who gets the abuse complaint and
the host who can lose their internet. So:
- every template declares `egress`: `none` (batch — blender, ffmpeg get **no network at
  all**), `limited` (outbound ok; inbound only via our tunnel), or `open` (nothing uses it)
- **the agent enforces it**, and **defaults CLOSED** if a template forgets to declare one
- container ports are published to **`127.0.0.1` only** — the reverse tunnel is the sole
  ingress
- the policy is visible to buyers in `/templates`

**3. Email verification.** Not ceremony — it's how you reach a human at 2am when their
node is emitting abuse traffic. Tokens are single-use, **hashed at rest**, expire in 15
minutes; disposable domains rejected. **Required before adding a payout destination or
withdrawing.**

**4. Payout destination changes = the fraud vector.** Take over an account, swap the bank
details, drain the earnings. Now:
- **password re-auth** (a stolen session token is not enough)
- **verified email required** (so the real owner is told, out-of-band)
- **24h cooling-off** — a freshly-added destination *cannot receive money*. This turns an
  account takeover from "instant drain" into "you get an email and a day to stop it"
- the full destination is **never returned by the API**, not even to its owner — it was
  previously being leaked in full by `GET /wallet/methods`
- every change is audited (redacted)

**5. Audit log.** `AuditEvent`, append-only: who did what, when, from where, with the
request id. Covers payout changes, withdrawals, email verification, kill-switch use, and
denied re-auth attempts. **Never stores secrets or full destinations.** Read it via
`GET /admin/audit` when money is disputed.

**6. Passwords.** Floor raised 8 → 12, plus rejection of the most-guessed passwords.
Length beats complexity theatre. (A full HIBP k-anonymity check is the right next step.)

## Product: onboarding, cost transparency, seller diagnostics

Built from the UX review — but only the parts that work with the inventory we actually
have. Comparison views, saved-search alerts, favorites, and websocket availability were
deliberately SKIPPED: they all need supply and churn that doesn't exist yet. A comparison
table across three nodes is a table.

**Also skipped on purpose: the 7-step deployment wizard.** `/launch` is one click. The
competitors make you configure hardware -> image -> storage -> networking -> SSH key ->
review. Adding six steps to match them would be a regression. One-click IS the product.

**1. `/onboarding`** — two funnels, because a buyer and a host want completely different
things and one dashboard serves neither. Returns the checklist for whichever they are,
with the NEXT step marked. This became necessary the moment email verification started
gating payouts: without it a seller hits that wall with no idea why.

**2. `/estimate`** — the price BEFORE the buyer commits. Total, hourly rate, what happens
if they stop early (charged vs refunded, exactly), and a cloud comparison **only where we
can compare like for like**. The Launch button now shows this and asks for confirmation.

**3. `/seller/dashboard`** — utilization, earnings per node, and crucially a **diagnosis**.
Every pilot seller asks "my GPU is on, why is nothing running?" within a day, and a
dashboard that answers with a zero tells them nothing. So it names the blocker and the fix:
not attested / offline (sleep+hibernate does this) / fully booked / **priced above the
market median** (with the suggested price) / reputation gate / email unverified. If the
blocker list is empty, it says so plainly — then it's demand, not them.

**4. Jupyter + PyTorch templates.** The template list had games and image generation but
nothing for a researcher who wants a notebook on a real GPU — the highest-intent GPU
renter there is. Jupyter is `stateful`, so it gets snapshotted.

**5. Landing intent split** — "What are you here for?" -> *I need GPUs* / *I have a GPU to
rent out*. One CTA cannot serve both sides of a marketplace.

## Frontend round 2 (items 9, 14–18)

**Item 9 was a real bug, not a missing feature.** The templates existed and rendered, but
there was no browsable catalog *page*. Now `/catalog`: filter chips (Notebooks / AI / Art /
Render / Games), the full launch-card grid, an hours selector, and an honest "templates are
a convenience, not a limit — here's how to launch any Docker image" block. Linked from the
primary nav. Jupyter and PyTorch got their own `notebook` category and icons.

**14 — buyer burn rate.** `/buyer/spend`. The number a buyer actually wants isn't "balance",
it's *what is costing me money right now while I'm not looking*: live burn/hour, 24h
projection, hours of runway, what's held in escrow (and refundable). Rendered as a live
strip on `/account`.

**15 — mobile.** A host checks "is my node earning?" from their phone, in bed. A 7-column
table scrolled sideways is useless there. Under 720px every `.tbl` **collapses into stacked
cards**, each cell labelled from its header via `data-l`. Applied to marketplace, pricing,
account, and the seller dashboard.

**16 — actionable errors.** The UI literally rendered `Could not launch (error 503)`. Now
every booking error carries a code, a human explanation, **and where to go next**:
> *"That host just went offline — it stopped sending heartbeats. **Nothing was charged.**
> Try another verified host."* → **[Find another GPU]**

Covers HOST_OFFLINE, GPU_NOT_VERIFIED, NO_CAPACITY, INSUFFICIENT_FUNDS, OWN_HARDWARE,
GPU_NOT_FOUND. Every failure says whether money moved.

**18 — command palette.** ⌘K / Ctrl+K anywhere: fuzzy search, arrow keys, enter to jump.

**19 — dark mode** was already done properly (designed dark-first, with a real light theme,
not an inversion).

### Deliberately NOT built, with reasons
- **20 Global search** — searching across hosts/sellers/models needs inventory that doesn't
  exist. ⌘K covers navigation, which is the real need today.
- **21 API playground** — `/docs` (Scalar) already does exactly this: try requests live,
  copy cURL, view multi-language examples.
- **23 Trust badges — REFUSED on honesty grounds.** "Enterprise Ready", "Green Energy",
  "Fast Network" are badges we **cannot verify**. Inventing them is precisely the
  overclaiming we deleted from the site earlier. We show what we can prove: verified
  hardware, region-verified, confidential-computing, measured reputation, real success rate.
- **24 Performance history charts** — we don't record time-series yet. A 30-day uptime chart
  drawn from no data is a lie with axes. Needs a metrics table first; worth doing later.
- **8 The 7-step deployment wizard** — still a regression. One-click IS the product.

## Frontend/backend audit — what it found

Two new auditors, both wired into CI (`.github/workflows/tests.yml`, job `frontend`):

- **`audit_frontend.py`** — diffs the UI against the API. Dead calls (JS fetches an
  endpoint that doesn't exist), dead links, dead DOM ids (`getElementById` on an element
  that isn't there — the script throws and everything below it never runs), and orphan
  routes (backend works, no UI reaches it).
- **`audit_js.py`** — renders every page and runs `node --check` on each `<script>`.

### The big one: a broken `<script>` returns HTTP 200
Every Python test passed while **17 of 41 script blocks failed to parse**. Escaping a
quote through Python → HTML attribute → JS string is a minefield: one lost backslash
makes the string unterminated, the browser throws a SyntaxError, and **every function
defined below it silently ceases to exist**. Pages looked fine and did nothing.

Root causes, all now fixed:
- `pbCmd()` emitted an unterminated string — long-standing, broke the shared script on
  *every* page.
- Generated `onclick="fn(\'…\')"` handlers lost their backslashes.
- Apostrophes (`don't`, `Couldn't`) inside JS string literals.

**Permanent fix: no inline `onclick` with nested quotes anywhere.** Elements declare
`data-act` / `data-a1` / `data-a2` and one delegated listener dispatches. There is no
escaping left to get wrong, and a smoke test now fails if the pattern reappears.

### Working backend features with no frontend at all
The orphan-route scan found three, one serious:
- **Email verification had no UI** — while it *gates payouts*, and the onboarding
  checklist told users to "verify your email → /account" where nothing existed. Every
  seller would have hit a dead end at withdrawal. Now built; `/me` returns
  `email_verified`.
- **Notifications** — the backend has been emitting payout/refund/node-offline events
  all along and the app never displayed one. Now shown on `/account`.
- **VM event timeline** — `created → tunnel_registered → migrated`. This is the failover
  proof, the most convincing thing we can show a buyer, and it was invisible. Now a
  Timeline button on every instance, live or finished.

Result: 0 dead calls, 0 dead links, 0 dead DOM ids, 0 broken script blocks.

## The "enterprise redesign" brief — what we took and what we refused

**Built (honest, and genuinely missing):**
- **SEO / social.** Every page now has a meta description, canonical URL, Open Graph +
  Twitter card, and schema.org Organization data. Before this, a link to petabyte.market
  shared in a DM rendered as a bare URL with no title, summary or image.
- **Arabic + RTL.** Direction is set before paint (no flash). Our CSS uses logical
  properties throughout, so the layout mirrors. Critically, RTL is *not* "flip
  everything": money, code, curl commands and monospace identifiers stay LTR inside
  Arabic text — otherwise a price reads backwards. Translation is in-place via `data-ar`,
  so there is no separate Arabic build to drift out of sync.
- **`/contact`.** Real addresses, including a security channel with a no-legal-action
  promise for good-faith research. An honest teams/volume path for the things the
  self-serve product genuinely does not do yet (reserved capacity, invoicing, org billing).
- **A real 404** that says *"nothing is wrong with your account or your instances"* and
  offers a way out. API clients still get JSON.

**Refused, on purpose:**
- **Placeholder partner logos, customer logos and testimonials.** We have no customers.
  Placeholders here are fabricated social proof. One fake logo spotted by an investor ends
  the evaluation of everything else.
- **A metrics wall** (availability, providers, countries, GPUs, jobs completed). We would
  be publishing numbers we do not have.
- **Trust badges** ("Enterprise Ready", "High Availability", "Green Energy"). Unverifiable.
  Same refusal as before.
- **Replacing self-serve with a demo-booking funnel.** This is a strategic pivot dressed as
  a design brief. One-click launch IS the differentiator — the reason to choose us over
  Vast.ai or RunPod. An enterprise demo motion needs SOC 2, an SLA, capacity and a sales
  team; we have none of those, and booking demos we cannot service burns leads permanently.
  Enterprise is a *later* motion. The honest version — a "talk to us about capacity" path
  for teams — is on /contact.
- **"Look like a credible enterprise platform rather than an early-stage startup."** We are
  an early-stage startup. What earns credibility is the ledger that reconciles to zero, the
  escrow that refunds to the cent, the tunnel that survives a host dying, and a test suite
  that catches bugs competitors ship. Not a costume.

## Accelerator feedback — the funding-critical round

The "enterprise redesign" brief came from the accelerator weighing funding. Took the
honest 80%, adapted the 20% that would have hurt.

**Built:**
- **`/demo` + demand capture.** A real book-a-demo page with an honest pitch ("see it run,
  not slides"). `POST /demo/request` (public, IP-rate-limited, email-validated) stores each
  lead in a `demo_requests` table and notifies admins. `GET /admin/demo-requests` is the
  founder's demand dashboard — the single most useful artifact for the next investor
  conversation. Leads are never fabricated; each row is a real person who filled the form.
- **Credibility strip** on the landing page: escrow-protected / survives host failure /
  verified hardware / isolated workloads — each claim backed by an existing test.
- Demo CTA in nav + landing, Arabic throughout the new page.

**Adapted, on purpose (documented in outputs/accelerator-response.md):**
- Demo bookings run *alongside* self-serve, not replacing it. One-click launch is the moat.
- Trust section states test-backed truths, not unverifiable badges.
- No placeholder customer logos / testimonials / vanity metrics. Sections built and ready
  to populate the moment there's something true to show (accelerator's own logo first).

A written response to the accelerator is in `outputs/accelerator-response.md` — frames the
three adaptations as founder judgment, not defiance, and offers to reverse any of them.

## Cal.com demo scheduling + Arabic marketing pages

**Cal.com self-scheduling (the "calendar link" flow the founder asked for).**
Set `CAL_BOOKING_URL` in the env once your Cal.com account exists, e.g.
`CAL_BOOKING_URL=https://cal.com/petabyte/demo`. Then on a demo request we (1) email the
requester their booking link and (2) show a "Pick your time" button on the success screen,
so they self-book a slot that lands on both calendars. Left unset, the flow degrades to the
honest "we'll email you within a business day" path — no dead links. Wiring is in
`_email_booking_link()` + `request_demo()`; tests cover both configured and unset.

**Arabic coverage.** Static copy on the main marketing/product pages is now translated via
`data-ar`: landing, install, marketplace, pricing, security, contact, catalog, demo, 404,
and /app (which also gained the RTL system + language toggle). ~145 strings, up from ~43.
Money, code, curl commands and monospace stay LTR under RTL so nothing reads backwards.

**Known remaining Arabic gaps (deliberate):**
- JS-generated strings (e.g. the marketplace "N GPUs match" line, pbEmpty states) are NOT
  translated — `data-ar` only covers static DOM. These need a small JS string dictionary;
  do it as one focused pass rather than scattering ternaries.
- Legal pages (Terms / Privacy / Acceptable-use) are intentionally NOT machine-translated —
  a subtly-wrong Arabic legal text is a liability, not a polish item. Get these
  professionally translated for compliance.
- developers page, gamers/artists landing variants, account console internals: partial.

## Env template + deploy sync (important)

There are TWO env files, and they must both include every var the code reads:
- **`lumaris_api/template.env`** — human reference ("every var the app reads").
- **`lumaris_api/deploy/deploy.sh`** — GENERATES `/etc/lumaris/lumaris.env` on first run
  from its own heredoc. This is what actually reaches production.

Note: `deploy/update.sh` (the routine redeploy) rsyncs code but EXCLUDES `.env` and never
touches `/etc/lumaris/lumaris.env` — so a redeploy does NOT overwrite live secrets. New
vars reach prod either by first-run generation (deploy.sh) or by you editing the live env
by hand using template.env as the reference.

Audited both against the code and added six missing vars to each: `ENVIRONMENT`,
`TRUSTED_PROXIES`, `LEGACY_KEYS_FULL_ACCESS`, `PAYOUT_COOLING_OFF_H`, `EMAIL_TOKEN_TTL_MIN`,
`CAL_BOOKING_URL`. The generated env ships `ENVIRONMENT=development` on purpose — setting
production makes the app refuse to boot while stubs are on, so a fresh box would brick.
Flip it to production only after every stub is off (that refusal is the safety feature).

deploy.sh's debug report now prints ENVIRONMENT / LEGACY_KEYS_FULL_ACCESS / TRUSTED_PROXIES
/ CAL_BOOKING_URL so a misconfig is visible at deploy time.

A smoke test now FAILS if the code ever reads an env var missing from template.env or from
deploy.sh's generated env — so this drift can't silently happen again.
