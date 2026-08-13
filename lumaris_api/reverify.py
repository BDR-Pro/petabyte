"""reverify.py — redundant re-execution of a random fraction of REAL deterministic jobs.

The honest gap in "no seller can fabricate a result": known-answer audits and quorum today
run as a distinct `test` task the agent can branch on. This closes it for deterministic real
work — a fraction of completed render/transcode/stitch jobs are RE-RUN on independent nodes
and their signed content hashes compared. Two honest nodes doing the same fixed render produce
identical output bytes, so an identical `content_hash` is the oracle; a node that returns a
different hash than the majority of honest re-runs is frozen for fraud.

Reuses the QuorumCheck machinery (quorum.compare/finalize): the check is seeded with the
ORIGINAL node's content_hash, then N shadow re-runs on distinct other bookable nodes report
theirs. Freezing needs a majority to agree AGAINST the original, so we dispatch >= 2 shadows
where possible (1 original + 2 honest agreeing = the faker is outvoted and frozen; with only
1 shadow a mismatch is INCONCLUSIVE and holds both for manual review — never a false freeze).

OFF by default (REVERIFY_SAMPLE_RATE=0.0): re-execution costs a second run, so operators opt in.
Deterministic job types only — a notebook/template job is not reproducible and is never sampled.
"""
from __future__ import annotations

import json
import logging
import os
import random

from db import Task, SellerSpec, QuorumCheck
import seller_audit

logger = logging.getLogger("petabyte.reverify")

# Output-deterministic job types: the same fixed inputs produce identical output bytes on any
# honest node, so an identical sha256 content_hash is a valid cross-node oracle.
DETERMINISTIC = {"render", "transcode", "stitch"}


def _rate(rate=None) -> float:
    if rate is not None:
        return float(rate)
    try:
        return float(os.getenv("REVERIFY_SAMPLE_RATE", "0.0"))
    except (TypeError, ValueError):
        return 0.0


def eligible(task) -> bool:
    """A completed, output-deterministic job that carries a signed content hash."""
    return (task is not None and task.status == "completed"
            and task.task_type in DETERMINISTIC and bool(task.result_content_hash))


def _other_bookable_specs(db, exclude_seller_id, limit=2):
    """Up to `limit` live, bookable specs owned by DISTINCT other sellers."""
    out, seen = [], set()
    for s in seller_audit._bookable_specs(db):
        if s.user_id == exclude_seller_id or s.user_id in seen:
            continue
        seen.add(s.user_id)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def open_reverify(db, task, shadows: int = 2, others=None):
    """Open a content-hash quorum for a completed deterministic job: seed the ORIGINAL node's
    hash, then dispatch shadow re-runs (same inputs/params) to `shadows` distinct other
    bookable nodes. Returns the QuorumCheck, or None if there aren't enough independent nodes.
    (`others` may be supplied explicitly; otherwise live bookable nodes are chosen.)"""
    spec = db.query(SellerSpec).filter(SellerSpec.id == task.spec_id).first()
    if spec is None:
        return None
    if others is None:
        others = _other_bookable_specs(db, spec.user_id, limit=shadows)
    if not others:
        return None

    subs = {str(spec.user_id): {"task_id": task.id, "spec_id": spec.id,
                                "hash": task.result_content_hash}}
    for s in others:
        shadow = Task(spec_id=s.id, task_type=task.task_type, buyer_id=task.buyer_id,
                      booking_id=task.booking_id, template=task.template,
                      template_params=task.template_params, code=task.code,
                      status="pending", priority=5)
        db.add(shadow); db.commit(); db.refresh(shadow)
        subs[str(s.user_id)] = {"task_id": shadow.id, "spec_id": s.id, "hash": None}

    need = (len(subs) // 2) + 1                      # a majority of all participants
    chk = QuorumCheck(size=0, seed=0, nonce="reverify:%d" % task.id, min_agree=need,
                      status="open", submissions=json.dumps(subs))
    db.add(chk); db.commit(); db.refresh(chk)
    logger.info("reverify %s opened for task %d across %d shadow node(s), min_agree=%d",
                chk.public_id, task.id, len(others), need)
    return chk


def sample_and_open(db, task, rate=None, shadows: int = 2):
    """With probability `rate` (default REVERIFY_SAMPLE_RATE), open a re-verification for a
    completed deterministic job. No-op (None) when disabled, ineligible, when the task is
    already a quorum replica (don't re-verify a shadow — no infinite fan-out), or when there
    aren't enough independent nodes."""
    r = _rate(rate)
    if r <= 0 or not eligible(task):
        return None
    try:
        import quorum
        if quorum.get_check_for_task(db, task.id)[0] is not None:
            return None                              # this task is itself a replica
    except Exception:
        pass
    if r < 1.0 and random.random() > r:              # noqa: S311 (sampling, not crypto)
        return None
    try:
        return open_reverify(db, task, shadows=shadows)
    except Exception:
        logger.exception("reverify open failed for task %s", getattr(task, "id", "?"))
        return None
