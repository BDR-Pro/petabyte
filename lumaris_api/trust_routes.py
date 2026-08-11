"""trust_routes.py — public trust & transparency API (the verifiable-receipt surface).

Second slice of the staged main.py -> domain-routers split, and the first that depends on the
DATABASE and AUTH: it imports the shared dependencies from deps.py, so it extracts cleanly with
no circular import. Proves the pattern works for authenticated/DB routes, not just static pages.

Routes:
  GET /trust/summary          public honest transparency counts (trust.trust_summary)
  GET /jobs/{task_id}/receipt buyer-scoped cryptographic receipt (trust.build_receipt)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db, get_user_by_username, Task
from deps import get_current_user, _username
import trust

router = APIRouter(tags=["trust"])


@router.get("/trust/summary")
def trust_summary_endpoint(db: Session = Depends(get_db)):
    """Public, honest transparency counts (no fabrication; zeros mean zero) — the data behind
    the /trust page: attested GPUs by tier, benchmark consistency, jobs completed, content-bound
    + signed results, quorum outcomes, fraud flags, and whether the ledger balances."""
    return trust.trust_summary(db)


@router.get("/jobs/{task_id}/receipt")
def job_receipt(task_id: int, user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """The BUYER's cryptographic receipt for their own job: the node's Ed25519 signature over
    the exact signed payload, the sha256 of the real output bytes, the node's attested pubkey,
    the GPU's trust tier + benchmark verdict, and a LIVE server re-verification of that
    signature. Buyer-scoped: only the job's buyer can read it."""
    me = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or me is None or task.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return trust.build_receipt(db, task)
