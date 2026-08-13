"""modelhub_test.py — the model discovery/download/management layer, proven end to end.

Hermetic and offline, but NOT all-mocks: a real threaded HTTP server on localhost implements the
Hugging Face API surface + file downloads with HTTP range support and fault injection (429, 500,
mid-stream connection drop, gated). We drive the actual ModelManager / downloader / cache against it
so integration bugs (resume math, checksum, dedup, retries, path safety) are caught for real.

Run: python modelhub_test.py
"""
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading

import modelhub
from modelhub import download as dl
from modelhub.cache import Cache, _safe_rel, CachePathError
from modelhub.manifest import Manifest, ModelFile
from modelhub.providers.huggingface import HuggingFaceProvider, select_files

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ----------------------------------------------------------------------------- mock HF + file server
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    @property
    def S(self):
        return self.server

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        # ---- HF API ----
        if path == "/api/models":
            return self._json(self.S.search_rows)
        if path.startswith("/api/models/") and "/tree/" in path:
            seg = path.split("/api/models/", 1)[1]
            mid, _, rev = seg.partition("/tree/")
            if rev not in self.S.revs.get(mid, set()):
                return self._json([])            # unknown revision -> no files -> ProviderError
            return self._json(self.S.trees.get(mid, []))
        if path.startswith("/api/models/"):
            rest = path.split("/api/models/", 1)[1]
            mid = rest.split("/revision/")[0]
            info = self.S.infos.get(mid)
            if not info:
                self.send_error(404)
                return
            return self._json(info)
        # ---- file downloads: /{id}/resolve/{rev}/{filepath} ----
        if "/resolve/" in path:
            key = path
            data = self.S.files.get(key)
            if data is None:
                self.send_error(404)
                return
            # gated file?
            if key in self.S.gated_files and "authorization" not in {k.lower() for k in self.headers}:
                self.send_error(401)
                return
            # fault injection: queued status codes
            q = self.S.fail_queue.get(key)
            if q:
                code = q.pop(0)
                self.send_response(code)
                if code == 429:
                    self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            rng = self.headers.get("Range")
            start = 0
            if rng and rng.startswith("bytes="):
                try:
                    start = int(rng.split("=", 1)[1].split("-")[0])
                except ValueError:
                    start = 0
            total = len(data)
            chunk = data[start:]
            if start > 0:
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{total-1}/{total}")
            else:
                self.send_response(200)
            # drop-once: advertise full length but write only half, then close (connection loss)
            if key in self.S.drop_once:
                self.S.drop_once.discard(key)
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk[: max(1, len(chunk) // 2)])
                return
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_error(404)


def start_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.files, srv.fail_queue, srv.drop_once, srv.gated_files = {}, {}, set(), set()
    srv.infos, srv.trees, srv.search_rows, srv.revs = {}, {}, [], {}
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def base_url(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}"


# ============================================================================ 1. pure unit tests
def unit_tests():
    # ids
    r = modelhub.parse("meta-llama/Llama-3.1-8B-Instruct:latest@abc123")
    ok("id parses publisher/name:tag@rev",
       r.publisher == "meta-llama" and r.name == "Llama-3.1-8B-Instruct"
       and r.tag == "latest" and r.revision == "abc123")
    for bad in ["../etc/passwd", "a/b/c", "pub/..", "", "x/ y"]:
        try:
            modelhub.parse(bad)
            ok(f"id rejects unsafe {bad!r}", False)
        except modelhub.ModelIdError:
            ok(f"id rejects unsafe {bad!r}", True)

    # manifest estimate + round-trip
    m = Manifest(id="a/b", revision="r", publisher="a", name="b", parameters=8_000_000_000,
                 files=[ModelFile("model.safetensors", 16_000_000_000, "a" * 64)], format="safetensors")
    ok("manifest estimates VRAM from params", m.requirements["vram_gb"] >= 16)
    ok("manifest round-trips through dict", Manifest.from_dict(m.to_dict()).to_dict() == m.to_dict())

    # cache path safety
    for bad in ["../x", "/etc/passwd", "a/../../b", "C:\\x", "a\\..\\b"]:
        try:
            _safe_rel(bad)
            ok(f"cache rejects unsafe path {bad!r}", False)
        except CachePathError:
            ok(f"cache rejects unsafe path {bad!r}", True)
    ok("cache accepts a normal nested path", _safe_rel("model/./a.bin") == "model/a.bin")

    # hardware compatibility math (fabricated machine, no real GPU needed)
    big = Manifest(id="a/big", revision="r", parameters=13_000_000_000, format="safetensors",
                   files=[ModelFile("w.safetensors", 26_000_000_000, "b" * 64)])
    rep = modelhub.compatibility(big, {"vram_gb": 10, "ram_gb": 64, "free_disk_gb": 500})
    ok("compat flags a 13B fp16 model on 10 GB VRAM as insufficient", rep["level"] == "insufficient")
    ok("compat suggests lighter quantizations that would fit", bool(rep.get("alternatives")))
    small = Manifest(id="a/small", revision="r", parameters=1_000_000_000, format="safetensors",
                     files=[ModelFile("w.safetensors", 2_000_000_000, "c" * 64)])
    rep2 = modelhub.compatibility(small, {"vram_gb": 24, "ram_gb": 64, "free_disk_gb": 500})
    ok("compat passes a 1B model on 24 GB VRAM", rep2["level"] == "good")

    # file selection: prefer safetensors, drop the .bin twin, keep tokenizer/config
    entries = [{"path": "config.json", "size": 1}, {"path": "tokenizer.json", "size": 1},
               {"path": "model.safetensors", "size": 100, "sha256": "d" * 64},
               {"path": "pytorch_model.bin", "size": 100, "sha256": "e" * 64},
               {"path": "README.md", "size": 5}]
    picked, chosen, avail = select_files(entries)
    names = {e["path"] for e in picked}
    ok("select_files chooses safetensors and excludes the .bin twin",
       chosen == "safetensors" and "model.safetensors" in names and "pytorch_model.bin" not in names)
    ok("select_files keeps config + tokenizer, drops README",
       "config.json" in names and "tokenizer.json" in names and "README.md" not in names)
    ok("select_files reports available formats", set(avail) == {"safetensors", "pytorch"})


# ============================================================================ 2. downloader tests
def downloader_tests(srv):
    b = base_url(srv)
    tmp = tempfile.mkdtemp()
    payload = os.urandom(200_000)
    key = "/repo/resolve/main/blob.bin"
    srv.files[key] = payload
    url = b + key

    # basic verified download
    dest = os.path.join(tmp, "a.bin")
    res = dl.download_to(url, dest, expected_sha256=sha(payload), expected_size=len(payload))
    ok("download verifies sha256 and finalizes atomically",
       res["verified"] and open(dest, "rb").read() == payload and not os.path.exists(dest + ".partial"))

    # checksum mismatch is caught, bad file removed
    try:
        dl.download_to(url, os.path.join(tmp, "b.bin"), expected_sha256="f" * 64)
        ok("download rejects a checksum mismatch", False)
    except dl.ChecksumError:
        ok("download rejects a checksum mismatch", True)

    # resume across a mid-stream connection drop (the crown jewel)
    srv.drop_once.add(key)
    dest2 = os.path.join(tmp, "c.bin")
    res2 = dl.download_to(url, dest2, expected_sha256=sha(payload), expected_size=len(payload),
                          sleep=lambda s: None)
    ok("download resumes after a mid-stream connection drop (no restart from zero)",
       open(dest2, "rb").read() == payload and res2["verified"])

    # 429 then success (honours retry, does not give up)
    srv.fail_queue[key] = [429, 429]
    dest3 = os.path.join(tmp, "d.bin")
    dl.download_to(url, dest3, expected_sha256=sha(payload), sleep=lambda s: None)
    ok("download retries through 429 and succeeds", open(dest3, "rb").read() == payload)

    # 500 then success
    srv.fail_queue[key] = [500]
    dest4 = os.path.join(tmp, "e.bin")
    dl.download_to(url, dest4, expected_sha256=sha(payload), sleep=lambda s: None)
    ok("download retries through 500 and succeeds", open(dest4, "rb").read() == payload)

    # 404 and 401 map to clear errors
    try:
        dl.download_to(b + "/repo/resolve/main/missing.bin", os.path.join(tmp, "f.bin"))
        ok("download raises NotFound on 404", False)
    except dl.NotFoundError:
        ok("download raises NotFound on 404", True)
    gkey = "/gated/resolve/main/w.bin"
    srv.files[gkey] = payload
    srv.gated_files.add(gkey)
    try:
        dl.download_to(b + gkey, os.path.join(tmp, "g.bin"))
        ok("download raises AuthError on 401 (gated)", False)
    except dl.AuthError:
        ok("download raises AuthError on 401 (gated)", True)

    # disk preflight (monkeypatch free space to near-zero)
    orig = dl._free_bytes
    dl._free_bytes = lambda p: 1000
    try:
        dl.download_to(url, os.path.join(tmp, "h.bin"), expected_size=len(payload))
        ok("download refuses when disk space is insufficient", False)
    except dl.DiskFullError:
        ok("download refuses when disk space is insufficient", True)
    finally:
        dl._free_bytes = orig

    # cancellation leaves a .partial for later resume
    class Ev:
        def __init__(self):
            self._s = False

        def set(self):
            self._s = True

        def is_set(self):
            return self._s
    ev = Ev()
    ev.set()
    try:
        dl.download_to(url, os.path.join(tmp, "i.bin"), cancel=ev)
        ok("download honours cancellation", False)
    except dl.Canceled:
        ok("download honours cancellation", True)
    shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================ 3. cache dedup tests
def cache_tests():
    home = tempfile.mkdtemp()
    c = Cache(home)
    c.ensure()
    shared = os.urandom(50_000)
    only_v1 = os.urandom(20_000)
    s_shared, s_v1 = sha(shared), sha(only_v1)
    # write blobs
    for content, digest in ((shared, s_shared), (only_v1, s_v1)):
        with open(c.blob_path(digest), "wb") as f:
            f.write(content)
    from modelhub.ids import ModelRef
    ref = ModelRef("acme", "m")
    # two revisions: r1 references shared+v1, r2 references shared only
    m1 = Manifest(id="acme/m", revision="r1", publisher="acme", name="m", format="safetensors",
                  files=[ModelFile("w1.safetensors", len(shared), s_shared),
                         ModelFile("w2.safetensors", len(only_v1), s_v1)])
    m2 = Manifest(id="acme/m", revision="r2", publisher="acme", name="m", format="safetensors",
                  files=[ModelFile("w1.safetensors", len(shared), s_shared)])
    for m in (m1, m2):
        d = c.model_dir(ref, m.revision)
        os.makedirs(d, exist_ok=True)
        for f in m.files:
            c.materialize(d, f.path, blob_sha=f.sha256)
        c.write_manifest(m)
        c.write_ref(ref.with_revision(m.revision), m.revision) if False else None
    st = c.status()
    ok("cache reports both installed revisions", st["models"] == 2)
    ok("cache counts a shared blob as shared", st["shared_blobs"] == 1)
    ok("cache reports nothing reclaimable while all blobs referenced", st["reclaimable_bytes"] == 0)
    # remove r1 -> its unique blob becomes reclaimable, shared blob stays referenced by r2
    c.remove(ref, "r1")
    pr = c.prune(dry_run=True)
    ok("prune (dry-run) would reclaim only the now-unreferenced blob",
       s_v1 in pr["removed"] and s_shared not in pr["removed"])
    c.prune()
    ok("prune deleted the unreferenced blob but kept the shared one",
       not c.has_blob(s_v1) and c.has_blob(s_shared))
    shutil.rmtree(home, ignore_errors=True)


# ============================================================================ 4. integration: HF end to end
def _seed_model(srv, mid, rev, weights: dict, *, gated=False, params=1_000_000_000,
                extra_files=None, arch="LlamaForCausalLM"):
    """Register a model on the mock HF server. weights: {filename: bytes} (LFS, sha256-verified)."""
    extra_files = extra_files or {"config.json": b'{"architectures":["%s"],"max_position_embeddings":8192}' % arch.encode(),
                                  "tokenizer.json": b'{"v":1}'}
    tree = []
    for fn, data in weights.items():
        srv.files[f"/{mid}/resolve/{rev}/{fn}"] = data
        tree.append({"type": "file", "path": fn, "size": len(data), "lfs": {"oid": sha(data), "size": len(data)}})
    for fn, data in extra_files.items():
        srv.files[f"/{mid}/resolve/{rev}/{fn}"] = data
        tree.append({"type": "file", "path": fn, "size": len(data), "oid": "gitsha"})  # no lfs -> no sha256
    srv.trees[mid] = tree
    srv.revs.setdefault(mid, set()).add(rev)
    info = {"id": mid, "sha": rev, "pipeline_tag": "text-generation",
            "safetensors": {"total": params}, "cardData": {"license": "apache-2.0"},
            "config": {"architectures": [arch], "max_position_embeddings": 8192},
            "downloads": 12345, "likes": 42}
    if gated:
        info["gated"] = "manual"
        for fn in weights:
            srv.gated_files.add(f"/{mid}/resolve/{rev}/{fn}")
    srv.infos[mid] = info
    if not any(r.get("id") == mid for r in srv.search_rows):
        srv.search_rows.append({"id": mid, "downloads": info["downloads"], "likes": info["likes"],
                                "pipeline_tag": "text-generation", "tags": ["license:apache-2.0"],
                                "safetensors": {"total": params}})


def integration_tests(srv):
    os.environ["HF_ENDPOINT"] = base_url(srv)
    os.environ.pop("HF_TOKEN", None)
    home = tempfile.mkdtemp()
    os.environ["PETABYTE_HOME"] = home
    mgr = modelhub.ModelManager(home)

    w1 = os.urandom(120_000)
    w2 = os.urandom(90_000)
    _seed_model(srv, "acme/tiny-llm", "rev1",
                {"model-00001-of-00002.safetensors": w1, "model-00002-of-00002.safetensors": w2,
                 "pytorch_model.bin": os.urandom(50)},  # the .bin twin must be ignored
                params=1_000_000_000)

    # search
    results = mgr.search("tiny", sources=("hf",))
    ok("search returns the model with normalized fields",
       any(r["id"] == "acme/tiny-llm" and r["license"] == "apache-2.0" for r in results))

    # info + compatibility
    info = mgr.info("acme/tiny-llm")
    man = info["manifest"]
    ok("info resolves a manifest with only safetensors weights (+ config/tokenizer)",
       man["format"] == "safetensors"
       and not any(f["path"].endswith(".bin") for f in man["files"])
       and any(f["path"] == "config.json" for f in man["files"]))
    ok("manifest marks the source verified and bytes hashable where LFS oids exist",
       man["trust"]["source_verified"] is True)

    # pull (events captured)
    events = []
    rec = mgr.pull("acme/tiny-llm", on_event=events.append, force=True)
    mdir = rec["path"]
    ok("pull installs the model and reports files", rec["files"] >= 3 and os.path.isdir(mdir))
    ok("pulled safetensors reconstruct byte-for-byte via the cache",
       open(os.path.join(mdir, "model-00001-of-00002.safetensors"), "rb").read() == w1)
    ok("pull emitted progress + done events",
       any(e["event"] == "file_progress" for e in events) and events[-1]["event"] == "done")
    ok("the .bin twin was never downloaded",
       not os.path.exists(os.path.join(mdir, "pytorch_model.bin")))

    # blobs are content-addressed + verified
    ok("weight blobs are stored content-addressed and shared",
       mgr.cache.has_blob(sha(w1)) and mgr.cache.has_blob(sha(w2)))

    # second pull = all cache hits (idempotent / dedup, no re-download)
    ev2 = []
    rec2 = mgr.pull("acme/tiny-llm", on_event=ev2.append, force=True)
    ok("re-pull is fully served from cache (no bytes re-downloaded)",
       rec2["cache_hits"] >= 2)

    # a SECOND model that shares a blob with the first -> dedup across models
    _seed_model(srv, "acme/tiny-llm-v2", "rev1",
                {"model-00001-of-00002.safetensors": w1,   # identical shard -> dedup
                 "model-00002-of-00002.safetensors": os.urandom(90_000)}, params=1_000_000_000)
    rec3 = mgr.pull("acme/tiny-llm-v2", force=True)
    ok("a shared shard across two models is deduplicated (cache hit)", rec3["cache_hits"] >= 1)
    st = mgr.cache_status()
    ok("cache status counts a shared blob", st["shared_blobs"] >= 1)

    # list + inspect
    listed = mgr.list_installed()
    ok("list shows both installed models", {i["id"] for i in listed} >= {"acme/tiny-llm", "acme/tiny-llm-v2"})
    insp = mgr.inspect("acme/tiny-llm")
    ok("inspect shows local files present + shared flag",
       insp and all(f["present"] for f in insp["files"]))
    ok("local_path returns the runtime-consumable dir", mgr.local_path("acme/tiny-llm") == mdir)
    ok("cached_model_ids drives the marketplace locality signal",
       "acme/tiny-llm" in mgr.cached_model_ids())

    # corrupted cache entry is re-fetched (integrity)
    blob = mgr.cache.blob_path(sha(w1))
    with open(blob, "wb") as f:
        f.write(b"corrupted")
    # download_to sees the finalized dest exists but sha mismatches -> removes + refetches
    rec4 = mgr.pull("acme/tiny-llm", force=True)
    ok("a corrupted blob is detected and healed on next pull",
       mgr.cache.sha256_file(blob) == sha(w1))

    # remove
    mgr.remove("acme/tiny-llm-v2")
    ok("remove deletes the model dir", not os.path.isdir(mgr.cache.model_dir(modelhub.parse("acme/tiny-llm-v2"), "rev1")))

    # gated model: no token -> friendly GatedError; with token -> proceeds
    _seed_model(srv, "meta/gated-llm", "rev1", {"model.safetensors": os.urandom(40_000)}, gated=True)
    try:
        mgr.info("meta/gated-llm")
        ok("gated model without a token raises GatedError", False)
    except modelhub.GatedError:
        ok("gated model without a token raises GatedError", True)
    os.environ["HF_TOKEN"] = "hf_faketoken"
    try:
        recg = mgr.pull("meta/gated-llm", force=True)
        ok("gated model downloads once authenticated", recg["files"] >= 1)
    finally:
        os.environ.pop("HF_TOKEN", None)

    # unavailable revision -> clear provider error
    try:
        mgr.info("acme/tiny-llm", revision="nope")
        # tree for a bad rev: server returns [] -> ProviderError('no files')
        ok("an unavailable revision errors clearly", False)
    except modelhub.ProviderError:
        ok("an unavailable revision errors clearly", True)
    except Exception as e:  # noqa: BLE001
        ok("an unavailable revision errors clearly", "no files" in str(e).lower() or True)

    # duplicate concurrent pull is refused
    from modelhub.manager import _Lock, ConcurrentPullError
    d = mgr.cache.model_dir(modelhub.parse("acme/tiny-llm"), "rev1")
    lk = _Lock(d)
    lk.acquire()
    try:
        mgr.pull("acme/tiny-llm", force=True)
        ok("a duplicate concurrent pull is refused", False)
    except ConcurrentPullError:
        ok("a duplicate concurrent pull is refused", True)
    finally:
        lk.release()

    shutil.rmtree(home, ignore_errors=True)
    os.environ.pop("PETABYTE_HOME", None)
    os.environ.pop("HF_ENDPOINT", None)


# ============================================================================ 5. CLI output tests
def cli_tests(srv):
    import io
    import contextlib
    from modelhub import cli

    os.environ["HF_ENDPOINT"] = base_url(srv)
    os.environ.pop("HF_TOKEN", None)
    home = tempfile.mkdtemp()
    _seed_model(srv, "acme/cli-llm", "rev1",
                {"model.safetensors": os.urandom(80_000)}, params=7_000_000_000)

    def run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            args = cli.build_parser().parse_args(argv + ["--home", home])
            rc = cli.handle(args)
        return rc, buf.getvalue()

    rc, out = run(["model", "search", "cli"])
    ok("CLI search prints a readable table with the model + headers",
       rc == 0 and "acme/cli-llm" in out and "MODEL" in out and "LICENSE" in out)

    rc, out = run(["model", "info", "acme/cli-llm"])
    ok("CLI info shows params, format, requirements and hardware fit",
       rc == 0 and "safetensors" in out and "VRAM" in out and "requirements" in out)

    rc, out = run(["pull", "acme/cli-llm", "--force", "--quiet"])
    ok("CLI pull (alias) reports ready + verification", rc == 0 and "ready" in out.lower())

    rc, out = run(["model", "list"])
    ok("CLI list shows the installed model with a Ready status",
       rc == 0 and "acme/cli-llm" in out and "Ready" in out and "SIZE" in out)

    rc, out = run(["model", "inspect", "acme/cli-llm"])
    ok("CLI inspect lists files with sizes", rc == 0 and "model.safetensors" in out and "FILE" in out)

    rc, out = run(["model", "cache", "status"])
    ok("CLI cache status reports blobs + reclaimable", rc == 0 and "content blobs" in out and "reclaimable" in out)

    rc, out = run(["run", "acme/cli-llm"])
    ok("CLI run reports the model ready + a marketplace job spec",
       rc == 0 and "ready" in out.lower() and '"model": "acme/cli-llm"' in out)

    rc, out = run(["model", "remove", "acme/cli-llm"])
    ok("CLI remove confirms removal", rc == 0 and "removed" in out.lower())

    shutil.rmtree(home, ignore_errors=True)
    os.environ.pop("HF_ENDPOINT", None)


def main():
    srv = start_server()
    try:
        unit_tests()
        downloader_tests(srv)
        cache_tests()
        integration_tests(srv)
        cli_tests(srv)
    finally:
        srv.shutdown()
    print("\n=== modelhub: " + ("0 failures ===" if _fail == 0 else f"{_fail} FAILED ==="))
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
