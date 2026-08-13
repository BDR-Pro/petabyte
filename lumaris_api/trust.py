"""trust.py — public transparency surfaces: honest live counts + a verifiable per-job receipt.

Two "don't trust, verify" surfaces built entirely from data the platform already holds:

  * trust_summary(db)   — live, honest marketplace counts (no fabrication; zeros mean zero):
                          attested GPUs by trust tier, benchmark-consistency, confidential
                          nodes, jobs completed, content-bound + signed results, quorum
                          outcomes, fraud flags, and whether the double-entry ledger balances.

  * build_receipt(db,t) — the cryptographic receipt for one completed job: the node's Ed25519
                          signature over the exact signed payload, the sha256 of the real
                          output bytes, the node's attested pubkey, the GPU's trust tier +
                          benchmark verdict, and a LIVE server re-verification of that
                          signature — so a buyer can re-check it themselves, offline.

No secrets, no money movement — read-only over existing rows.
"""
from __future__ import annotations

import json


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def trust_summary(db) -> dict:
    """Live, honest transparency counts for the public /trust page. Every number is a real
    DB aggregate; nothing is invented, and zero means zero."""
    from sqlalchemy import func
    from db import SellerSpec, Task, QuorumCheck, trust_level_for, ledger_is_balanced

    tiers = {"agent_verified": 0, "benchmark_consistent": 0, "benchmark_flagged": 0}
    confidential_active = 0
    specs = db.query(SellerSpec).filter(SellerSpec.attested == True).all()  # noqa: E712
    for s in specs:
        lvl = trust_level_for(s)
        if "flagged" in lvl["label"].lower():
            tiers["benchmark_flagged"] += 1
        elif lvl["level"] == "benchmark_verified":
            tiers["benchmark_consistent"] += 1
        else:
            tiers["agent_verified"] += 1
        try:
            from db import spec_confidential_active
            if spec_confidential_active(s):
                confidential_active += 1
        except Exception:
            pass

    jobs_completed = db.query(Task).filter(Task.status == "completed").count()
    results_content_bound = db.query(Task).filter(Task.result_content_hash.isnot(None)).count()
    verifiable_receipts = db.query(Task).filter(Task.result_signature.isnot(None)).count()
    quorum_by_status = dict(
        db.query(QuorumCheck.status, func.count()).group_by(QuorumCheck.status).all())
    sellers_fraud_flagged = db.query(SellerSpec).filter(SellerSpec.fraud_count > 0).count()
    try:
        balanced, broken = ledger_is_balanced(db)
    except Exception:
        balanced, broken = None, []

    return {
        "attested_gpus": len(specs),
        "trust_tiers": tiers,
        "confidential_nodes_active": confidential_active,
        "jobs_completed": jobs_completed,
        "results_content_bound": results_content_bound,     # #65: sha256 of real output bytes
        "verifiable_receipts": verifiable_receipts,         # signature retained for the buyer
        "quorum_checks_by_status": quorum_by_status,        # redundant re-execution outcomes
        "sellers_fraud_flagged": sellers_fraud_flagged,     # payouts frozen pending review
        "ledger_balanced": (bool(balanced) if balanced is not None else None),
        "ledger_broken_tx": len(broken or []),
        "trust_ladder": [
            {"level": "self_reported", "meaning": "registered via the API; nothing proven."},
            {"level": "agent_verified",
             "meaning": "the node signed a hardware report with its Ed25519 device key."},
            {"level": "benchmark_verified",
             "meaning": "agent-verified + a signed benchmark that MATCHES public reference "
                        "data for the claimed GPU model (FP16 TFLOPS / Blender / Cinebench / "
                        "PugetBench)."},
        ],
        "not_claimed": "Hardware TEE attestation is NOT asserted from the software stub; "
                       "'confidential' is a separate, fail-closed badge.",
    }


def build_receipt(db, task) -> dict:
    """The verifiable cryptographic receipt for one job. Re-verifies the stored node signature
    LIVE against the node's attested pubkey (server_reverified), and hands the buyer everything
    needed to repeat that check offline."""
    import utils
    from db import SellerSpec, Booking, trust_level_for

    spec = db.query(SellerSpec).filter(SellerSpec.id == task.spec_id).first()
    booking = (db.query(Booking).filter(Booking.id == task.booking_id).first()
               if task.booking_id else None)

    proof = None
    if task.result_proof:
        try:
            proof = json.loads(task.result_proof)
        except Exception:
            proof = None

    # LIVE re-verification of the node's Ed25519 signature over the EXACT signed payload.
    # (Skip the freshness window on purpose — an old-but-valid signature is still valid.)
    server_reverified = None
    if task.result_signature and proof is not None and spec and spec.attest_pubkey:
        try:
            msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
            utils._ed25519_verify(spec.attest_pubkey, msg, task.result_signature)
            server_reverified = True
        except Exception:
            server_reverified = False

    return {
        "task_id": task.id,
        "job": {"type": task.task_type, "status": task.status,
                "created_at": _iso(task.created_at), "completed_at": _iso(task.completed_at)},
        "gpu": ({"listing_id": spec.public_id, "gpu_model": spec.gpu_model,
                 "provider": spec.provider, "trust": trust_level_for(spec),
                 "benchmark_verdict": getattr(spec, "benchmark_verdict", None)}
                if spec else None),
        "settlement": ({"booking_id": booking.id, "status": booking.status,
                        "amount": str(booking.gross_amount),
                        "custodian": "Petabyte escrow (internal double-entry ledger)"}
                       if booking else None),
        "proof": {
            "algo": "ed25519",
            "node_pubkey_b64": spec.attest_pubkey if spec else None,
            "content_hash_sha256": task.result_content_hash,
            "signature_b64": task.result_signature,
            "signed_payload": proof,
            "server_reverified": server_reverified,
            "verify_recipe": "message = JSON(signed_payload, sort_keys=true, "
                             "separators=(',',':')); ed25519_verify(node_pubkey_b64, message, "
                             "signature_b64).",
        },
        "guarantees": [
            "The result is signed by the key the node attested at enrolment — this output is "
            "cryptographically bound to that node (a forged/tampered signature is rejected and "
            "freezes the seller's payouts).",
            "content_hash is the sha256 of the REAL output bytes, so two honest nodes doing the "
            "same deterministic work produce the same hash (quorum-comparable).",
        ],
        "not_guaranteed": [
            "Unless the listing is confidential (hardware TEE), the node's owner could still see "
            "the plaintext — signing proves attribution, not privacy, and not that the silicon "
            "is the exact advertised die.",
        ],
    }
