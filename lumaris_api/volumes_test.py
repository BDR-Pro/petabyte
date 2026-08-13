"""volumes_test.py — persistent volumes are INCREMENTAL, not a full-disk mirror.

Proves the whole content-addressed snapshot loop, hermetically (TestClient + S3_STUB, offline):
  * a snapshot's manifest is planned -> the server reports only the MISSING blobs (the delta);
  * identical content is stored ONCE (intra-snapshot and across snapshots) — dedup;
  * a second snapshot that changes one file + adds one file uploads ONLY those two blobs (the
    delta) — unchanged content is never re-uploaded or re-billed;
  * content addressing is enforced server-side: a body whose sha256 != the URL is rejected;
  * finalizing a snapshot that references an un-uploaded blob is refused;
  * restore returns the full manifest; restore `since` an earlier snapshot returns ONLY the
    changed files (the delta the client still needs) — "once a user needs it, send the delta";
  * a snapshot can be reconstructed byte-for-byte from the manifest + blob downloads;
  * a foreign buyer cannot see, plan, or delete another buyer's volume;
  * deleting a volume wipes every content blob from object storage.

Run: python volumes_test.py
"""
import hashlib
import os
import shutil
import tempfile

os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///./volumes_test.db"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["REAPER_DISABLED"] = "true"
# Object storage: the local stub writes blobs to a temp dir instead of talking to S3.
os.environ["S3_STUB"] = "true"
os.environ["S3_BUCKET"] = "petabyte-volumes-test"

for f in ("volumes_test.db", "volumes_test.db-wal", "volumes_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
_STUB_ROOT = os.path.join(tempfile.gettempdir(), "petabyte-s3-stub", os.environ["S3_BUCKET"])
if os.path.isdir(_STUB_ROOT):
    shutil.rmtree(_STUB_ROOT)

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def buyer(name):
    c.post("/register_user", json={"username": name, "password": "pw-correct-horse-1"})
    tok = c.post("/login", data={"username": name, "password": "pw-correct-horse-1"}).json()["access_token"]
    return {"Authorization": "Bearer " + tok}


def manifest(files):
    """files: {path: bytes} -> ([{path,sha256,size}], {sha256: bytes})."""
    ents, blobs = [], {}
    for path, data in files.items():
        h = sha(data)
        ents.append({"path": path, "sha256": h, "size": len(data)})
        blobs[h] = data
    return ents, blobs


def upload_missing(vid, JH, plan, blobs):
    """PUT exactly the blobs the plan says are missing — the delta, nothing more."""
    for m in plan["missing"]:
        r = c.put(f"/volumes/{vid}/blobs/{m['sha256']}", headers=JH, content=blobs[m["sha256"]])
        assert r.status_code == 200, r.text


A = buyer("volbuyerA")
B = buyer("volbuyerB")

# ---- create a volume ----
v = c.post("/volumes", headers=A, json={"name": "checkpoints", "size_limit_gb": 10}).json()
VID = v["id"]
ok("a buyer creates a volume", v["status"] == "ok" and VID and v["bytes_stored"] == 0)
ok("a fresh volume has no snapshots", v["snapshots"] == 0)

# ---- snapshot #1: two distinct files + a THIRD file with identical content to file A ----
# proves intra-snapshot dedup: 3 files, 2 unique blobs.
A1 = b"AAAA-weights-layer-0\n" * 8
B1 = b"BBBB-weights-layer-1\n" * 8
files_v1 = {"model/a.bin": A1, "model/b.bin": B1, "model/a_copy.bin": A1}
m1, blobs1 = manifest(files_v1)

plan1 = c.post(f"/volumes/{VID}/snapshot/plan", headers=A, json={"files": m1}).json()
ok("plan #1: 3 files collapse to 2 unique blobs (intra-snapshot dedup)",
   plan1["unique_blobs"] == 2 and len(plan1["missing"]) == 2)
ok("plan #1: nothing is held yet, so both unique blobs are the delta to upload",
   plan1["reused_blobs"] == 0 and plan1["missing_bytes"] == len(A1) + len(B1))
ok("plan #1: total logical bytes counts all 3 files (incl. the duplicate)",
   plan1["total_bytes"] == 2 * len(A1) + len(B1))
ok("plan #1: each missing blob carries an upload path",
   all(mm["upload_path"] == f"/volumes/{VID}/blobs/{mm['sha256']}" for mm in plan1["missing"]))

# content addressing is enforced: a body whose sha != the URL is refused.
some_sha = plan1["missing"][0]["sha256"]
bad = c.put(f"/volumes/{VID}/blobs/{some_sha}", headers=A, content=b"not the real content")
ok("a blob whose body sha256 != the URL is rejected (400, content addressing enforced)",
   bad.status_code == 400 and bad.json().get("error", {}).get("code") == "SHA_MISMATCH")

# finalizing before uploading the blobs is refused (no phantom snapshots).
early = c.post(f"/volumes/{VID}/snapshot", headers=A, json={"files": m1, "label": "v1"})
ok("finalizing a snapshot whose blobs were never uploaded is refused (400)",
   early.status_code == 400 and early.json().get("error", {}).get("code") == "BLOB_MISSING")

upload_missing(VID, A, plan1, blobs1)
# a re-PUT of an already-stored blob is an idempotent no-op reported as deduped.
redup = c.put(f"/volumes/{VID}/blobs/{some_sha}", headers=A, content=blobs1[some_sha]).json()
ok("re-uploading an existing blob is an idempotent no-op (deduped)", redup["deduped"] is True)

snap1 = c.post(f"/volumes/{VID}/snapshot", headers=A, json={"files": m1, "label": "v1"}).json()
ok("snapshot #1 records; delta_bytes = the 2 unique blobs only (not the 3 files)",
   snap1["delta_bytes"] == len(A1) + len(B1) and snap1["seq"] == 1)
ok("snapshot #1: total_bytes is the logical size incl. the duplicate file",
   snap1["total_bytes"] == 2 * len(A1) + len(B1))
ok("snapshot #1: nothing held before, so no cross-snapshot reuse yet",
   snap1["reused_blobs"] == 0)

vol = c.get(f"/volumes/{VID}", headers=A).json()
ok("volume bytes_stored = unique bytes held (the real cost), < logical size",
   vol["bytes_stored"] == len(A1) + len(B1) and vol["bytes_stored"] < snap1["total_bytes"])
ok("volume reports dedup savings", vol["dedup_saved_bytes"] == len(A1))

# ---- snapshot #2: change ONE file, keep two, add ONE new file ----
B2 = b"BBBB-weights-layer-1-RETRAINED\n" * 9   # b.bin changed
D2 = b"DDDD-optimizer-state\n" * 12            # brand new file
files_v2 = {"model/a.bin": A1, "model/b.bin": B2, "model/a_copy.bin": A1, "model/d.bin": D2}
m2, blobs2 = manifest(files_v2)

plan2 = c.post(f"/volumes/{VID}/snapshot/plan", headers=A, json={"files": m2}).json()
ok("plan #2: only the CHANGED file + the NEW file are missing — the delta (2 blobs)",
   len(plan2["missing"]) == 2 and plan2["missing_bytes"] == len(B2) + len(D2))
missing_shas2 = {mm["sha256"] for mm in plan2["missing"]}
ok("plan #2: the delta is exactly the new b.bin + new d.bin content",
   missing_shas2 == {sha(B2), sha(D2)})
ok("plan #2: the unchanged a.bin/a_copy.bin blobs are reused, not re-uploaded",
   sha(A1) not in missing_shas2)

before = c.get(f"/volumes/{VID}", headers=A).json()["bytes_stored"]
upload_missing(VID, A, plan2, blobs2)   # uploads ONLY the 2 delta blobs
snap2 = c.post(f"/volumes/{VID}/snapshot", headers=A, json={"files": m2, "label": "v2"}).json()
after = c.get(f"/volumes/{VID}", headers=A).json()["bytes_stored"]
ok("snapshot #2 delta_bytes = only the changed + new content",
   snap2["delta_bytes"] == len(B2) + len(D2) and snap2["seq"] == 2)
ok("snapshot #2 reused the unchanged a.bin blob from snapshot #1 (cross-snapshot dedup)",
   snap2["reused_blobs"] == 1)
ok("volume grew by EXACTLY the delta (unchanged content stored once, never re-billed)",
   after - before == len(B2) + len(D2))

# ---- restore: full vs delta ----
full = c.get(f"/volumes/{VID}/snapshots/{snap2['id']}/restore", headers=A).json()
ok("full restore of #2 returns all 4 files", full["file_count"] == 4 and not full["is_delta"])
ok("full restore annotates each file with a blob download path",
   all(f["download_path"] == f"/volumes/{VID}/blobs/{f['sha256']}" for f in full["files"]))

delta = c.get(f"/volumes/{VID}/snapshots/{snap2['id']}/restore",
              headers=A, params={"since": snap1["id"]}).json()
ok("delta restore (#2 since #1) returns ONLY the 2 changed files (b.bin + d.bin)",
   delta["is_delta"] and delta["delta_count"] == 2
   and {f["path"] for f in delta["files"]} == {"model/b.bin", "model/d.bin"})
ok("delta restore ships far fewer bytes than a full restore",
   delta["delta_size"] < full["full_size"] and delta["delta_size"] == len(B2) + len(D2))

# ---- reconstruct snapshot #2 byte-for-byte from the manifest + blob downloads ----
recon = {}
for f in full["files"]:
    blob = c.get(f["download_path"], headers=A)
    recon[f["path"]] = blob.content
ok("snapshot #2 reconstructs byte-for-byte from downloaded blobs", recon == files_v2)
ok("a downloaded blob's sha256 verifies against its content (integrity)",
   all(sha(v) == f["sha256"] for f in full["files"] for v in [recon[f["path"]]]))

# ---- cross-tenant isolation ----
ok("a foreign buyer cannot read another's volume (404)",
   c.get(f"/volumes/{VID}", headers=B).status_code == 404)
ok("a foreign buyer cannot plan a snapshot on another's volume (404)",
   c.post(f"/volumes/{VID}/snapshot/plan", headers=B, json={"files": m1}).status_code == 404)
ok("a foreign buyer cannot download another's blob (404)",
   c.get(f"/volumes/{VID}/blobs/{sha(A1)}", headers=B).status_code == 404)
ok("a foreign buyer cannot delete another's volume (404)",
   c.delete(f"/volumes/{VID}", headers=B).status_code == 404)

# ---- delete wipes every blob from object storage ----
uniq_blobs = {sha(A1), sha(B1), sha(B2), sha(D2)}
dele = c.delete(f"/volumes/{VID}", headers=A).json()
ok("deleting the volume removes every unique content blob from object storage",
   dele["status"] == "ok" and dele["blobs_removed"] == len(uniq_blobs))
ok("the deleted volume is gone (404)", c.get(f"/volumes/{VID}", headers=A).status_code == 404)
_remaining = sum(len(fs) for _d, _ds, fs in os.walk(os.path.join(_STUB_ROOT, "volumes")))
ok("no blob objects remain in object storage for the deleted volume", _remaining == 0)

print("\n=== volumes: " + ("0 failures ===" if _fail == 0 else f"{_fail} FAILED ==="))
import sys  # noqa: E402
sys.exit(1 if _fail else 0)
