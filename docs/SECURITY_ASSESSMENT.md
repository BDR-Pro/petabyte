# SECURITY_ASSESSMENT.md

Assessment of the Petabyte codebase (API + agent). Method: automated static scan,
auth-coverage analysis, review of crypto/payment/isolation paths, and the 169-assertion
functional suite. Verdict: **no code-level vulnerabilities found**; residual risk is in
the hardware-facing paths that require live adversarial testing (see §9 + RLtest §17).

## 1. Method
- Static scan for `eval/exec/os.system/pickle/yaml.load/shell=True`, string-formatted
  SQL, string/shell subprocess, and hardcoded secrets.
- Auth-coverage: every route checked for an auth dependency (67 routes).
- Manual review of: attestation/signature verification, payment/payout money paths,
  multi-tenant isolation, and idle-mining preemption.
- Full functional regression (169 assertions).

## 2. Findings
| Severity | Finding | Status |
|----------|---------|--------|
| — | No `eval`/`exec`/`os.system`/`pickle`/`yaml.load`/`shell=True` anywhere | Clean |
| — | No string-formatted SQL — all DB access via SQLAlchemy ORM (bound params) | Clean |
| — | 20 subprocess calls, all **list-form** (no shell) → no shell injection | Clean |
| — | No hardcoded secrets; all via `os.getenv`/`os.environ` | Clean |
| Info | `GET /verify_api_key` has no `Depends` guard | Accepted: it is authenticated *by the key it validates* — it only decodes the caller-supplied key and returns that key's own claims; reveals nothing without a valid key. |

All other 65 state/data routes require `get_current_user` (JWT), `api_key_user`
(node key), or are intentionally public (`/`, `/healthz`, `/readyz`, `/login`,
`/register_user`, `/marketplace/stats`, `/templates`, `/webhooks/payment` which is
HMAC-verified).

## 3. AuthN / AuthZ
- JWT (UTC expiry, fail-fast on missing `SECRET_KEY`) for users; encrypted, revocable,
  **scoped** API keys for nodes (`require_scope`).
- **Ownership boundaries enforced and tested**: nodes claim jobs only for specs they
  own; buyers act only on their own tasks/bookings/checkpoints; org actions gated by
  role; a node can't attest/benchmark/back-up/checkpoint another node's spec. These
  are covered by explicit negative tests in the suite.

## 4. Remote code execution surface (agent)
- Untrusted buyer code runs ONLY in a Docker sandbox: `--network none`, `--cap-drop
  ALL`, `--no-new-privileges`, read-only rootfs, mem/CPU/PID limits, **no host
  fallback** (refuses if Docker absent). Same for templates/render/transcode.
- The agent never shells out with a string; all container invocations are argv lists.
- **Residual:** sandbox-escape resistance must be verified on a real Docker host
  (RLtest §17) — the isolation flags are coded but a live daemon is needed to attack.

## 5. Cryptographic integrity
- **Attestation & proof-of-work:** Ed25519; results bind to the attested key; forged/
  expired signatures rejected and recorded as fraud (tested).
- **Payment webhook:** HMAC-SHA256 over the raw body, constant-time compare,
  idempotent on `event_id` (tested).
- **Per-task backup keys** sealed at rest with the server key (Fernet); backups
  client-side encrypted before leaving the node.
- **TEE:** stub verifier is a real Ed25519 check; the real vendor chain (NRAS/SEV-SNP)
  is a documented seam (stub.md #3) — until wired, do not market hardware
  confidentiality as verified.

## 6. Money-path integrity
- Escrow, org wallets, payouts, and idle-mining credits all use **guarded atomic
  conditional updates** (debit only if sufficient) and settle **exactly once**
  (booking state machine; payout state machine; idempotent webhook + idle settlement
  on `(worker, period)`). Refund-on-failure returns funds. All tested.
- Live-mode `/deposit` is disabled (402/403); funds enter only via the verified
  webhook. Gift cards accepted payout-side only (never buyer funding).

## 7. Multi-tenant isolation
- Object storage: per-object pre-signed URLs, keys namespaced by
  `backups|inputs/{buyer_or_task}/…`; nodes hold no standing credentials; a node can
  write/read only the single key granted. Restore verifies a signed content hash.
- Per-task encryption keys isolate backup contents between tenants.

## 8. Idle mining safety
- Opt-in, off by default. **Paid work preempts unconditionally** — the miner is
  killed before any claimed job runs (RLtest §21 verifies on real hardware). Mining
  never holds the GPU against a paying job. Earnings attributed by unique worker id
  and credited idempotently.

## 9. Residual risks (require live/adversarial testing — not code bugs)
1. **Sandbox escape** — verify container isolation on a real Docker host (RLtest §17).
2. **TEE authenticity** — swap the stub for the vendor verifier before claiming
   confidentiality (stub.md #3).
3. **Idle-mining preemption** — confirm on real GPU that mining yields instantly to
   paid work (RLtest §21); if not, disable the feature.
4. **Third-party integrations** — payout (KYC/AML/sanctions), email (deliverability),
   NiceHash (org key), Stripe: the adapters are now functional real-API code but need
   credentials + a security review of each provider relationship before launch.
5. **Rotate the originally-committed secrets** (SECURITY.md) before any real deploy.

## 10. Recommendations before production
- Run RLtest §17 (sandbox), §21 (preemption), and the payment/payout/residency real
  tests.
- Add rate-limiting at the edge (nginx) on `/login`, `/register_user`, and the upload/
  URL-minting endpoints.
- Scope the API's IAM role to `arn:aws:s3:::$BUCKET/{backups,inputs}/*` only.
- Turn on WAF + request-size limits; keep `WG_APPLY=false` unless a VPN host exists.
- Complete KYC/AML/sanctions + legal review for payouts and idle-mining revenue flow.
