# Runbook: Compromised or malicious seller agent / node

**Severity: P1.** Triggers: a seller node running a tampered/old vulnerable agent, a leaked
agent API key or signing key, anomalous results, or a sandbox-escape report.

Goal: revoke the node's ability to act, quarantine the affected version, and stop dispatch
to it — without disrupting healthy sellers or losing evidence.

## 1. Revoke the node's credentials (first minutes)
- **Revoke the agent API key** (`X-API-KEY`) for the node so heartbeat, `/jobs/next`,
  claim, and result submission are all rejected immediately. Verify a revoked key returns
  401/403 on every agent endpoint (there is a regression test for this).
- If the seller's **JWT / enrollment token** is suspected leaked, invalidate it so no new
  node can enroll under that identity.
- Confirm the node stops appearing in `petabyte_agents_online` and drops out of routable
  supply.

## 2. Quarantine the node and stop dispatch
- Mark the seller's spec(s) offline / ineligible so the router never selects them
  (`can_accept_paid_jobs = false`, or force `status != online`).
- Cancel/reassign any in-flight jobs on that node per policy; release capacity **exactly
  once** (do not let both cancellation and the reaper increment capacity).

## 3. Block the vulnerable version fleet-wide
- Add the compromised agent version to the **update deny/blocklist** so auto-update refuses
  it and the release policy will not serve or downgrade to it.
- Confirm signed update metadata binds `version + artifact digest`; a node must reject any
  artifact whose signature/digest does not match (downgrade + tamper protection).

## 4. If a SIGNING KEY leaked (not just an API key)
- Treat all releases signed with that key as untrusted from the leak window onward.
- **Rotate the signing key**: publish the new public key to agents through the trusted
  channel, re-sign the current known-good release, and revoke the old key per
  `SECURITY.md`'s key-rotation procedure. No single signing key is trusted forever.
- Force fleet re-verification against the new key before further auto-updates.

## 5. Preserve evidence & assess blast radius
- Snapshot the node's last-known agent version, submitted results, and signatures.
- Check whether the node submitted results for tasks it did not own, or replayed a
  previously-signed result (signatures must bind task id + a unique operation context).
- Cross-check any settlements/payouts tied to that node's jobs; if fraudulent results were
  accepted, follow `FINANCIAL_INTEGRITY_INCIDENT.md` to reverse via compensating entries.

## 6. Recover
- Only re-admit the node after it runs a verified, signed, non-blocklisted agent version
  and passes attestation again.
- Add/confirm the regression test that would have caught the vector (ownership check,
  replay binding, digest verification, or sandbox policy) so it cannot recur.

## Do NOT
- Do not simply delete the node record — preserve it for evidence.
- Do not re-enable a leaked key or a blocklisted version.
- Do not trust a result's `metadata` alone as authorization for a seller/payment
  destination; the immutable booking controls the destination.
