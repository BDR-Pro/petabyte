# Security Policy

We run a marketplace where strangers rent each other's compute and real money moves
through escrow. Security is the product, not a feature. We would rather hear about a
flaw from you than from an incident — and we commit to handling your report seriously,
quickly, and without legal threats when you follow this policy.

## Reporting a vulnerability

**Please report privately — do not open a public issue or PR for a security bug.**

- **Preferred:** GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  on this repository (**Security → Report a vulnerability**). It creates a private
  advisory only maintainers can see.
- **Email:** `security@petabyte.market` (if it bounces, `info@petabyte.market`). For a
  sensitive report, ask for a key and send it encrypted.

Please include: what the issue is, the impact you can demonstrate, and the minimal steps
(or a short PoC) to reproduce. A working reproduction is the single most useful thing you
can send.

### Our response commitments

| Stage | Target |
|---|---|
| Acknowledge your report | within **3 business days** |
| Initial severity assessment + triage | within **7 business days** |
| Fix or mitigation for Critical/High | as fast as we can — days, not months |
| Coordinated public disclosure | within **90 days**, sooner once a fix ships, coordinated with you |

If we go quiet, nudge us — a missed SLA is a bug in *our* process, and we want to know.

## Safe harbor

We will not pursue or support legal action against researchers who, in good faith:

- follow this policy and report privately, giving us reasonable time to fix before disclosure;
- only interact with **accounts and data you own or have explicit permission to test**;
- avoid privacy violations, data destruction, and service degradation for other users;
- do not exfiltrate more data than necessary to prove a finding (a single record is proof; a database dump is not).

If you are unsure whether something is allowed, ask first at `security@petabyte.market`.
Acting in good faith under this policy is authorized conduct; we will not treat it as a
violation of the Terms of Service or as unlawful access.

## Scope

**In scope**
- The marketplace API (`lumaris_api`) — authentication, authorization/IDOR, tenant
  isolation, the payment/escrow and payout logic, the double-entry ledger.
- The node agents (`lumaris_agent`, `desktop-app`) — container isolation, host egress,
  the update channel, and result/benchmark signing.
- Hardware attestation, the benchmark-vs-public-reference authenticity check, and the
  seller-fraud paths — bypasses that let a seller fake a GPU, a result, or a benchmark.
- The web app and any petabyte.market surface — XSS, CSRF, SSRF, injection, auth bypass.

**Out of scope** (please don't report these unless you can show real user impact)
- Volumetric denial of service / traffic floods, and load-generated resource exhaustion.
- Social engineering, phishing, or physical attacks against staff or hosts.
- Findings in third-party services we depend on (Stripe, GitHub, cloud providers) — report
  those to the vendor; tell us if our integration misuses them.
- Missing "best-practice" headers, cookie flags, or TLS config **without** a demonstrated
  exploit; self-XSS; clickjacking on pages with no state-changing action.
- Reports from automated scanners with no verified, reproducible impact.
- The `test.petabyte.market` / demo environment's *test-mode* payment objects (these are
  Stripe **test** objects by design; no real money — see below).

**Never do this**, even in scope: run real DoS, access another user's real data beyond a
single proof record, move real money, or degrade the service for others.

## A note on payments

Live money is gated behind explicit configuration (`PAYMENTS_LIVE_ENABLED`,
`STRIPE_MODE`) and the test/demo environments use Stripe **test** mode only. If you find a
way to make the platform move **real** money without authorization, or to cross the
test/live boundary, that is Critical — report it immediately.

## Recognition

We keep a security acknowledgements list and will credit you (or keep you anonymous — your
choice) for a valid, previously-unknown report. We are an early-stage company; a monetary
bounty is discretionary and scaled to severity and report quality as budget allows. We will
always tell you honestly whether a report qualifies before you spend more time on it.

## Supported versions

Petabyte is a continuously-deployed service; the security-supported version is whatever is
running in production, tracked by the `main` branch. There are no older maintained releases —
fixes ship forward.

## What we do on our side

- Every change runs the full test suite (money invariants, tenant isolation, the sandbox and
  attestation checks) before merge; see [`docs/TRUST_MODEL.md`](docs/TRUST_MODEL.md) for what
  is enforced in code vs. what needs hardware.
- We state our security posture honestly, including what we do **not** yet guarantee, at
  [petabyte.market/security](https://petabyte.market/security) and
  [petabyte.market/trust](https://petabyte.market/trust).
- If a secret is ever exposed, we follow [`docs/SECRET_ROTATION.md`](docs/SECRET_ROTATION.md).

Thank you for helping keep Petabyte's users — buyers and hosts alike — safe.
