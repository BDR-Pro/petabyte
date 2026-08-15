"""Quorum verification: redundant re-execution across independent sellers.

For a deterministic workload the platform can't cheaply compute itself, dispatch the SAME
seeded challenge to several independent sellers and compare their results. Honest sellers
agree; a seller who fakes or corrupts the result diverges from the majority and is flagged
(fraud -> payouts frozen). Seller agreement is the oracle.

Verdicts:
  * AGREED       — a majority (>= min_agree) returned the same result -> that's the truth;
                   sellers who diverge from it are frozen for fraud.
  * INCONCLUSIVE — no majority agreement (e.g. a 1-vs-1 split): we can't tell who is right,
                   so ALL participants are held for manual review (never auto-paid).

(Here the replica payload is the integer-deterministic known-answer `test` workload so the
flow is fully runnable offline; in production the replica would be a real GPU workload for
which the platform has no server-side oracle — which is exactly when quorum matters.)
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from collections import Counter

import db as dbmod
from db import QuorumCheck, Task, TestWorkload, SellerSpec, compute_test_hash, _utcnow
import seller_audit

logger = logging.getLogger("petabyte.quorum")

_DIFF_SIZE = {"easy": 5000, "medium": 20000, "hard": 100000}


def compare(subs: list, *, min_agree: int = 2) -> dict:
    """Pure engine. `subs`: [{seller_id, hash}]. The largest cluster of identical results
    of size >= min_agree is the trusted answer; everyone outside it diverges. Returns
    {verdict, agreed_hash, agree:[ids], diverge:[ids], reason}."""
    have = [s for s in subs if s.get("hash")]
    if not have:
        return {"verdict": "INCONCLUSIVE", "agreed_hash": None, "agree": [],
                "diverge": [], "reason": "no submissions"}
    counts = Counter(s["hash"] for s in have)
    top_hash, top_n = counts.most_common(1)[0]
    if top_n >= min_agree:
        agree = [s["seller_id"] for s in have if s["hash"] == top_hash]
        diverge = [s["seller_id"] for s in have if s["hash"] != top_hash]
        return {"verdict": "AGREED", "agreed_hash": top_hash, "agree": agree,
                "diverge": diverge, "reason": f"{top_n}/{len(have)} agree"}
    return {"verdict": "INCONCLUSIVE", "agreed_hash": None, "agree": [],
            "diverge": [s["seller_id"] for s in have],
            "reason": f"no {min_agree}-way agreement among {len(have)} results"}


def open_check(db, specs, *, difficulty: str = "easy", min_agree: int = None) -> QuorumCheck:
    """Dispatch one identical seeded challenge to several DISTINCT sellers as replica
    `test` tasks. Requires >= min_agree distinct sellers (default: a majority)."""
    distinct, seen = [], set()
    for s in specs:
        if s.user_id in seen:
            continue
        seen.add(s.user_id); distinct.append(s)
    need = min_agree if min_agree else (len(distinct) // 2 + 1)
    if len(distinct) < 2 or len(distinct) < need:
        raise ValueError(f"need >= {max(2, need)} distinct sellers for a quorum; "
                         f"have {len(distinct)}")
    size = _DIFF_SIZE.get(difficulty, 5000)
    # The seed is the anti-fraud basis of the quorum challenge: predictable seeds let a seller
    # precompute the expected hash and pass without replicating the work. Use a CSPRNG.
    seed = secrets.randbelow(2_000_000_000) + 1
    nonce = "%016x" % secrets.randbits(63)
    expected = compute_test_hash(size, seed)
    subs = {}
    for s in distinct:
        task = Task(spec_id=s.id, task_type="test",
                    code=json.dumps({"size": size, "seed": seed}), status="pending")
        db.add(task); db.commit(); db.refresh(task)
        db.add(TestWorkload(task_id=task.id, spec_id=s.id, seller_id=s.user_id,
                            size=size, seed=seed, expected_hash=expected,
                            difficulty=difficulty, trigger="quorum", status="pending"))
        subs[str(s.user_id)] = {"task_id": task.id, "spec_id": s.id, "hash": None}
    chk = QuorumCheck(size=size, seed=seed, nonce=nonce, min_agree=need, status="open",
                      submissions=json.dumps(subs))
    db.add(chk); db.commit(); db.refresh(chk)
    logger.info("quorum %s opened across %d sellers (size=%d, min_agree=%d)",
                chk.public_id, len(distinct), size, need)
    return chk


def get_check_for_task(db, task_id: int):
    for chk in db.query(QuorumCheck).filter(QuorumCheck.status == "open").all():
        subs = json.loads(chk.submissions or "{}")
        for sid, rec in subs.items():
            if rec.get("task_id") == task_id:
                return chk, sid
    return None, None


def record_submission(db, task_id: int, output_hash: str):
    """Attach a seller's reported result to its quorum check; finalize once all replicas
    have reported. No-op if the task isn't part of a quorum."""
    chk, sid = get_check_for_task(db, task_id)
    if not chk:
        return None
    subs = json.loads(chk.submissions or "{}")
    if sid in subs and subs[sid].get("hash") is None:
        subs[sid]["hash"] = output_hash
        chk.submissions = json.dumps(subs); db.add(chk); db.commit()
    if all(r.get("hash") for r in subs.values()):
        return finalize(db, chk)
    return chk


def finalize(db, chk: QuorumCheck) -> QuorumCheck:
    subs = json.loads(chk.submissions or "{}")
    result = compare([{"seller_id": int(sid), "hash": r.get("hash")}
                      for sid, r in subs.items()], min_agree=chk.min_agree)
    chk.status = result["verdict"]
    chk.agreed_hash = result.get("agreed_hash")
    chk.finalized_at = _utcnow()
    db.add(chk); db.commit()

    if result["verdict"] == "AGREED":
        # sellers who disagree with the majority faked/corrupted the result -> fraud freeze
        for sid in result["diverge"]:
            spec_id = subs.get(str(sid), {}).get("spec_id")
            spec = db.query(SellerSpec).filter(SellerSpec.id == spec_id).first() if spec_id else None
            seller_audit.freeze_for_fraud(
                db, spec, "quorum divergence (result disagrees with the majority)",
                seller_id=sid)
    elif result["verdict"] == "INCONCLUSIVE" and len(subs) >= 2:
        # can't tell who's right -> hold everyone for manual review (not marked fraud)
        for sid in subs:
            try:
                dbmod.place_payout_hold(db, int(sid),
                                        reason=f"quorum inconclusive ({chk.public_id})")
            except Exception:
                logger.exception("quorum hold failed for seller %s", sid)
    logger.info("quorum %s finalized: %s (%s)", chk.public_id, result["verdict"], result["reason"])
    return chk


def run_quorum_audit(db, *, replicas: int = 3, difficulty: str = "easy") -> QuorumCheck | None:
    """Open a quorum check across up to `replicas` distinct live, bookable sellers.
    Returns the check, or None if there aren't enough distinct sellers."""
    specs = seller_audit._bookable_specs(db)
    # one spec per distinct seller
    distinct, seen = [], set()
    for s in specs:
        if s.user_id in seen:
            continue
        seen.add(s.user_id); distinct.append(s)
        if len(distinct) >= max(2, replicas):
            break
    if len(distinct) < 2:
        return None
    return open_check(db, distinct, difficulty=difficulty)
