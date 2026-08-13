"""models_routes.py — the Models API + web pages (model discovery / download / management).

Backed by the provider-independent `modelhub` library (same code the CLI uses). Search + info are
public discovery. Pull/remove operate on THIS node's cache and require auth + an explicit opt-in
(MODEL_PULL_ENABLED), because a server-side pull writes tens of GB to the host — appropriate for a
self-hosted or inference node pre-warming models, gated so it can't be abused to fill a disk.

Downloads run in a background thread with a live-progress job store the web UI polls.
"""
import os
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from deps import get_current_user, _username
from db import get_db, SellerSpec, specs_with_model_cached
import modelhub
from modelhub import ModelManager, parse, ModelIdError, CompatibilityError, ConcurrentPullError
from modelhub.providers import GatedError, ProviderError
from modelhub.download import DownloadError
from modelhub.hardware import detect, compatibility
from modelhub.manifest import Manifest
from pages import MODELS_HTML, MODEL_DETAIL_HTML, MODELS_INSTALLED_HTML

router = APIRouter(tags=["models"])

MODEL_PULL_ENABLED = os.getenv("MODEL_PULL_ENABLED", "false").lower() == "true"
MODEL_MAX_PULL_GB = float(os.getenv("MODEL_MAX_PULL_GB", "200"))

# A small curated set so the catalog is useful before anyone types a query. These are well-known
# open models; the real files are always fetched live from the upstream provider.
FEATURED = [
    {"id": "meta-llama/Llama-3.1-8B-Instruct", "parameters": 8_000_000_000, "license": "llama3.1",
     "pipeline": "text-generation", "architecture": "LlamaForCausalLM"},
    {"id": "Qwen/Qwen3-8B", "parameters": 8_000_000_000, "license": "apache-2.0",
     "pipeline": "text-generation", "architecture": "Qwen3ForCausalLM"},
    {"id": "mistralai/Mistral-7B-Instruct-v0.3", "parameters": 7_000_000_000, "license": "apache-2.0",
     "pipeline": "text-generation", "architecture": "MistralForCausalLM"},
    {"id": "meta-llama/Llama-3.2-3B-Instruct", "parameters": 3_000_000_000, "license": "llama3.2",
     "pipeline": "text-generation", "architecture": "LlamaForCausalLM"},
    {"id": "microsoft/Phi-3-mini-4k-instruct", "parameters": 3_800_000_000, "license": "mit",
     "pipeline": "text-generation", "architecture": "Phi3ForCausalLM"},
    {"id": "google/gemma-2-9b-it", "parameters": 9_000_000_000, "license": "gemma",
     "pipeline": "text-generation", "architecture": "Gemma2ForCausalLM"},
    {"id": "Qwen/Qwen2.5-Coder-7B-Instruct", "parameters": 7_000_000_000, "license": "apache-2.0",
     "pipeline": "text-generation", "architecture": "Qwen2ForCausalLM"},
    {"id": "BAAI/bge-large-en-v1.5", "parameters": 335_000_000, "license": "mit",
     "pipeline": "feature-extraction", "architecture": "BertModel"},
]

_mgr = None
_mgr_lock = threading.Lock()
_jobs = {}
_jobs_lock = threading.Lock()


def mgr() -> ModelManager:
    global _mgr
    with _mgr_lock:
        if _mgr is None:
            _mgr = ModelManager(os.getenv("PETABYTE_HOME"))
        return _mgr


def _machine():
    return detect(cache_home=mgr().cache.home)


def _compat_for_params(params, hw=None):
    """Rough compatibility from a parameter count alone (no manifest fetch) for catalog cards."""
    m = Manifest(id="x", revision="x", parameters=int(params or 0), format="safetensors")
    return compatibility(m, hw or _machine(), cache_home=mgr().cache.home)


def _installed_ids():
    try:
        return {i["id"] for i in mgr().list_installed() if i["installed"]}
    except Exception:  # noqa: BLE001
        return set()


# =============================================================================== API: discovery
def _search_payload(q, limit, filters, source):
    """Shared search/featured logic (plain function — safe to call internally without FastAPI DI)."""
    installed = _installed_ids()
    hw = _machine()
    if not (q or "").strip():
        rows = [{**f, "publisher": f["id"].split("/")[0], "name": f["id"].split("/")[-1],
                 "source": "hf", "size": 0, "downloads": 0} for f in FEATURED]
        rows = _filter_featured(rows, filters)
    else:
        try:
            rows = mgr().search(q, limit=limit, filters=filters,
                                sources=(source,) if source else ("hf",))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"search failed: {e}")
    for r in rows:
        r["installed"] = r["id"] in installed
        r["compatibility"] = _compat_for_params(r.get("parameters"), hw)["level"]
    return {"models": rows, "machine": hw, "query": q}


@router.get("/api/models/search")
def api_search(q: str = Query("", max_length=200), limit: int = Query(25, ge=1, le=100),
               license: str = Query(None), architecture: str = Query(None),
               max_params: int = Query(None), source: str = Query("hf")):
    filters = {k: v for k, v in (("license", license), ("architecture", architecture)) if v}
    if max_params:
        filters["max_params"] = max_params
    return _search_payload(q, limit, filters, source)


@router.get("/api/models/featured")
def api_featured():
    return _search_payload("", 25, {}, "hf")


@router.get("/api/models/machine")
def api_machine():
    return {"machine": _machine()}


@router.get("/api/models/installed")
def api_installed():
    return {"models": mgr().list_installed(), "machine": _machine()}


@router.get("/api/models/availability")
def api_availability(id: str = Query(..., max_length=200), db: Session = Depends(get_db)):
    """Cache-locality signal: how many online seller nodes already hold this model. The scheduler
    favours these nodes so a job doesn't re-download tens of GB when an equally-good node has it."""
    nodes = specs_with_model_cached(db, id)
    total = db.query(SellerSpec).filter(SellerSpec.status == "online").count()
    return {"id": id, "nodes_cached": len(nodes), "nodes_online": total}


@router.get("/api/models/downloads/{job_id}")
def api_download_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="download job not found")
    return job


@router.post("/api/models/pull")
def api_pull(body: dict, user: dict = Depends(get_current_user)):
    if not MODEL_PULL_ENABLED:
        raise HTTPException(status_code=503, detail=(
            "server-side model pull is disabled on this deployment (set MODEL_PULL_ENABLED=true). "
            "Use the CLI locally: petabyte model pull <id>"))
    mid = (body or {}).get("id")
    if not mid:
        raise HTTPException(status_code=422, detail="id is required")
    try:
        ref = parse(mid)
    except ModelIdError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # size preflight (against the resolved manifest) before we start writing to the host
    try:
        man = mgr().resolve_manifest(ref, fmt=body.get("format"),
                                     quantization=body.get("quantization"),
                                     revision=body.get("revision"))
    except GatedError as e:
        raise HTTPException(status_code=403, detail={
            "code": "GATED", "message": f"{e} — open {getattr(e, 'url', '') or 'the model page'} "
            "to accept the license, then authenticate."})
    except (ProviderError, ModelIdError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if man.total_size and man.total_size / (1024 ** 3) > MODEL_MAX_PULL_GB:
        raise HTTPException(status_code=413, detail=(
            f"{man.id} is {round(man.total_size / 1024**3, 1)} GB; exceeds the "
            f"{MODEL_MAX_PULL_GB} GB per-pull cap on this node"))

    job_id = uuid.uuid4().hex[:16]
    job = {"job_id": job_id, "id": man.id, "revision": man.revision, "status": "pending",
           "total": man.total_size, "downloaded": 0, "percent": 0, "file": None,
           "files_total": len(man.files), "files_done": 0, "cache_hits": 0,
           "message": "queued", "actor": _username(user), "started": time.time(),
           "path": None, "error": None}
    with _jobs_lock:
        _jobs[job_id] = job
    t = threading.Thread(target=_run_pull, args=(job_id, ref, body), daemon=True)
    t.start()
    return {"job_id": job_id, "id": man.id, "total_size": man.total_size,
            "poll": f"/api/models/downloads/{job_id}"}


@router.delete("/api/models/{model_id:path}")
def api_remove(model_id: str, revision: str = Query(None), user: dict = Depends(get_current_user)):
    try:
        res = mgr().remove(parse(model_id), revision=revision)
    except ModelIdError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not res["removed"]:
        raise HTTPException(status_code=404, detail="model not installed")
    return {"status": "ok", **res}


@router.get("/api/models/{model_id:path}")
def api_info(model_id: str, format: str = Query(None), quantization: str = Query(None),
             revision: str = Query(None), db: Session = Depends(get_db)):
    try:
        info = mgr().info(model_id, fmt=format, quantization=quantization, revision=revision)
    except GatedError as e:
        raise HTTPException(status_code=403, detail={
            "code": "GATED", "message": f"{e} — open {getattr(e, 'url', '') or 'the model page'} "
            "to accept the license, then authenticate."})
    except (ProviderError, ModelIdError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    info["installed"] = mgr().is_installed(model_id, revision=info["manifest"]["revision"])
    info["availability"] = {"nodes_cached": len(specs_with_model_cached(db, info["manifest"]["id"]))}
    return info


def _run_pull(job_id, ref, body):
    def on_event(ev):
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            e = ev.get("event")
            if e == "manifest":
                job.update(status="downloading", total=ev.get("total_size", job["total"]),
                           files_total=ev.get("files", job["files_total"]), message="downloading")
            elif e == "file_start":
                job["file"] = ev.get("file")
            elif e == "file_progress":
                job["downloaded"] = ev.get("overall_downloaded", job["downloaded"])
                tot = ev.get("overall_total") or job["total"] or 1
                job["percent"] = round(min(100, 100 * job["downloaded"] / tot), 1)
            elif e == "file_done":
                job["files_done"] += 1
                if ev.get("cache_hit"):
                    job["cache_hits"] += 1
            elif e == "done":
                job.update(status="done", percent=100, message="ready", path=ev.get("path"),
                           downloaded=job["total"])
    try:
        mgr().pull(ref, fmt=body.get("format"), quantization=body.get("quantization"),
                   revision=body.get("revision"), force=bool(body.get("force")), on_event=on_event)
    except CompatibilityError as e:
        _fail_job(job_id, "incompatible", str(e), report=e.report)
    except GatedError as e:
        _fail_job(job_id, "gated", str(e), url=getattr(e, "url", None))
    except ConcurrentPullError as e:
        _fail_job(job_id, "busy", str(e))
    except (DownloadError, ProviderError) as e:
        _fail_job(job_id, "error", str(e))
    except Exception as e:  # noqa: BLE001
        _fail_job(job_id, "error", str(e))


def _fail_job(job_id, status, message, **extra):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(status=status, error=message, message=message, **extra)


def _filter_featured(rows, filters):
    def ok(r):
        if filters.get("license") and (r.get("license") or "").lower() != filters["license"].lower():
            return False
        if filters.get("architecture") and (r.get("architecture") or "").lower() != filters["architecture"].lower():
            return False
        if filters.get("max_params") and r.get("parameters") and r["parameters"] > int(filters["max_params"]):
            return False
        return True
    return [r for r in rows if ok(r)]


# =============================================================================== web pages
@router.get("/models", response_class=HTMLResponse)
def models_page():
    return HTMLResponse(MODELS_HTML)


@router.get("/models/installed", response_class=HTMLResponse)
def models_installed_page():
    return HTMLResponse(MODELS_INSTALLED_HTML)


@router.get("/models/{publisher}/{model}", response_class=HTMLResponse)
def model_detail_page(publisher: str, model: str):
    return HTMLResponse(MODEL_DETAIL_HTML)
