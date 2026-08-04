# Threat Model

Petabyte runs untrusted buyer workloads on untrusted seller hardware and moves money
between them. This document states the trust boundaries, the adversaries, what is
mitigated today, and what is explicitly not yet mitigated. It is deliberately honest;
unresolved items are marked and cross-referenced to PRODUCTION_GAPS.

## Trust boundaries

```
 Buyer (untrusted) ── HTTPS ──►  Control plane (trusted, operator-run)  ◄── HTTPS ── Seller node (untrusted)
                                        │                                             │
                                        │  money, routing, audit                      │ runs buyer code in Docker
                                        ▼                                             ▼
                                   Postgres (trusted)                          buyer workload (untrusted)
```

Both buyers and sellers are untrusted. The control plane and its database are the
only trusted components. **Code execution on seller machines is treated as hostile.**

## Adversaries and mitigations

### A1. Malicious buyer attacking a seller's machine
- **Run in Docker only, no host fallback.** Notebook path: `--network none`,
  `--cap-drop ALL`, `--no-new-privileges`, read-only rootfs, tmpfs, mem/CPU/PID
  limits, wall timeout, output cap (`lumaris_agent/notebook.py`). Refuses if Docker
  is absent rather than running on the host.
- **Path traversal via job inputs**: the buyer-controlled `volume` is validated to a
  strict slug server-side before it reaches a root `tar` on the node (fixed; tested).
- **Egress abuse** (the seller's IP): templates default to closed network; only
  serving templates get a single declared port; batch jobs get no network.
- **Unresolved**: container-escape resistance must be verified on a real Docker host
  (`docs/RLtest.md`); template/render paths need cap-drop/read-only parity with the
  notebook path; micro-VM isolation is roadmap. See PRODUCTION_GAPS.

### A2. Malicious seller faking hardware or results
- **Attestation**: results must be Ed25519-signed by the key that attested the node;
  forged/expired signatures are rejected and recorded as fraud (`/jobs/result`).
- **Known-answer test workloads** verify a node actually computed the expected result
  and feed reputation.
- **Honest trust ladder**: self-reported < agent-verified < benchmark-verified. The
  UI never claims vendor hardware attestation from the Ed25519 stub.
- **Unresolved**: benchmark numbers are self-reported by the node until a fixed
  harness is in place (a signed but node-controlled value); do not treat as attested.

### A3. Attacker manipulating money
- **Double-entry ledger** that refuses unbalanced writes; wallet/earnings are caches
  reconstructable from it. Exact `NUMERIC(20,8)`/`Decimal` money, verified on Postgres.
- **Idempotent** booking (idempotency keys) and settlement (guarded state machine);
  concurrency tests prove no oversell and exact money conservation under parallel
  writers (`adversarial_test.py`).
- **Payments in**: buyer funds enter only via the HMAC-verified webhook, idempotent on
  `event_id`; live-mode `/deposit` is disabled.
- **Payouts out**: sanctions/AML `screen()` **fails closed** in live mode; new payout
  destinations have a 24h cooling-off; state machine reverses on failure.
- **Unresolved**: real KYC/AML/sanctions provider integration; live payment provider
  review; payout worker scheduler in deploy. See PRODUCTION_GAPS.

### A4. Attacker against the control plane
- **AuthN/Z**: JWT (UTC expiry, fail-fast on missing `SECRET_KEY`); encrypted,
  revocable, **scoped** node API keys. Ownership enforced per object (nodes claim only
  their own jobs; buyers act only on their own bookings/tasks) with negative tests.
- **Rate limiting**: nginx zones on `/login`, `/register_user`, key/deposit routes;
  app-level failure-budget limiter on sensitive routes.
- **Request size limits** (nginx `client_max_body_size`), secure headers + CSP,
  ORM-only DB access (no string SQL), list-form subprocess (no shell).
- **Audit log**: append-only `AuditEvent` for security-sensitive actions;
  correlation/request IDs; a kill switch that pauses new bookings without disrupting
  running rentals.
- **Unresolved**: `/login` is not in the app-level limiter (nginx-only); CSRF is N/A
  for the bearer-token flows but must be added if cookie flows are introduced;
  SSRF review of any user-supplied URLs before enabling live upload/fetch.

### A5. Supply-chain / update channel
- **Highest-consequence known risk**: the agent auto-update channel is not
  cryptographically signed. It is now **opt-in only**, the systemd unit is hardened,
  and `update.sh` has a pinned-key signature-verification hook ready for a signing
  pipeline. Release signing is required before fleet-wide auto-update — see
  PRODUCTION_GAPS (must-fix before executing untrusted workloads at scale).
- Historically committed secrets: `SECURITY.md` documents the leaked `.env` and the
  rotation procedure; template/`.env.example` carry only placeholders and git history
  contains no real key literals.

## Residual risk summary

The software money path, attestation, isolation design, and control-plane authz are
implemented and tested. The unresolved items are hardware-dependent (sandbox escape,
micro-VM, TEE), operational (payout scheduler, TLS-by-default, deploy test-gate), and
compliance (KYC/AML) — all enumerated with severity in PRODUCTION_GAPS. None are
hidden behind a false "verified" claim.
