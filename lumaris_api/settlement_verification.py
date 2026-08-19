"""Result-verification-gated settlement (audit killers #4/#8).

Decides whether a completed job's ComputeTransaction may AUTO-SETTLE (capture the buyer + accrue
the seller's held payout), must be DEFERRED to manual admin review, or must FAIL (bill nothing,
release the hold). The point: don't pay a seller for work the platform can't stand behind.

Policy, per job type:
  * VERIFIABLE templates — a server-issued known-answer challenge + a correctness validator
    (today: `pytorch-matmul-v1` via matmul_validation) — are held to that validator: only a
    VALID verdict settles; an INVALID verdict FAILS the tx; anything else (no challenge issued,
    no manifest carried, INCONCLUSIVE/MANUAL_REVIEW) DEFERS to admin. Fail-closed by default.
  * Everything else settles on the existing controls — the result is bound to the real output
    bytes (content_hash, #65) and sampled for async cross-node re-verification that freezes/holds
    divergent sellers (reverify/quorum). That's stated honestly here, not silently trusted.

This module is pure decision logic over a task-like object; the caller wires the three outcomes
to settle_after_result / _auto_fail_compute_tx / (leave to admin). It has no DB or network deps.
"""
from __future__ import annotations

import json
import logging
import os

import matmul_validation as mv

logger = logging.getLogger(__name__)

SETTLE, DEFER, FAIL = "settle", "defer", "fail"

# Templates that carry a server-side correctness oracle (a challenge the seller cannot fake).
VERIFIABLE_TEMPLATES = {mv.TEMPLATE_NAME}   # "pytorch-matmul-v1"


def _require_verification() -> bool:
    """Default ON: a verifiable template that cannot be verified is NEVER auto-paid. An operator
    can only LOOSEN this deliberately (SETTLEMENT_REQUIRE_VERIFICATION=false), never by accident."""
    return os.getenv("SETTLEMENT_REQUIRE_VERIFICATION", "true").strip().lower() not in (
        "0", "false", "no", "off")


def _load_expected(task):
    """The server-issued matmul challenge persisted for this task (ExpectedJob), or None if none
    was issued. Stored as JSON under task.template_params['matmul_challenge'] at task creation —
    absent today (the challenge-issuance path is hardware-dependent), so verifiable jobs fail
    closed (DEFER) until it's wired."""
    try:
        ch = (json.loads(task.template_params or "{}") or {}).get("matmul_challenge")
        return mv.ExpectedJob(**ch) if ch else None
    except Exception:  # noqa: BLE001 — a bad challenge must DEFER, never raise
        # But log it: a malformed challenge (wiring bug / schema drift) must be separable
        # from the ordinary "no challenge issued" state in the DEFER reason.
        logger.warning("settlement: unreadable matmul challenge for task %s",
                       getattr(task, "id", "?"), exc_info=True)
        return None


def _manifest_from_proof(task):
    """The agent-reported matmul manifest, carried inside the signed result proof."""
    try:
        return (json.loads(getattr(task, "result_proof", None) or "{}") or {}).get("manifest")
    except Exception:  # noqa: BLE001 — a bad proof must DEFER, never raise
        logger.warning("settlement: unreadable result proof for task %s",
                       getattr(task, "id", "?"), exc_info=True)
        return None


def decide(task, tx, *, attest_pubkey: str = None, seen_manifest_hashes=()):
    """Return (action, reason) where action ∈ {settle, defer, fail}."""
    template = (getattr(task, "template", "") or "")
    if template not in VERIFIABLE_TEMPLATES:
        return (SETTLE,
                "no server-side correctness oracle for this job type; settlement relies on "
                "content-hash binding + async cross-node re-verification (holds/freezes divergent "
                "sellers)")

    expected = _load_expected(task)
    manifest = _manifest_from_proof(task)
    if expected is None or manifest is None:
        if _require_verification():
            return (DEFER,
                    "verifiable job is missing a server-issued challenge or a result manifest; "
                    "fail-closed — leaving capture/transfer to admin review")
        return (SETTLE, "verification not required (SETTLEMENT_REQUIRE_VERIFICATION=false)")
    if not attest_pubkey:
        return (DEFER, "no attestation pubkey to bind the result to attested hardware")

    res = mv.validate(expected, manifest, attest_pubkey=attest_pubkey,
                      signature=(getattr(task, "result_signature", None) or ""),
                      seen_manifest_hashes=seen_manifest_hashes)
    if mv.may_pay(res.status):
        return (SETTLE, f"verification VALID ({res.validator_version})")
    if res.status == mv.INVALID:
        # Provably wrong work — never pay for it; the caller fails the tx (bills nothing).
        return (FAIL, f"verification INVALID: {res.reason}")
    # INCONCLUSIVE / MANUAL_REVIEW / PENDING — neither pay nor punish; a human decides.
    return (DEFER, f"verification {res.status}: {res.reason}")
