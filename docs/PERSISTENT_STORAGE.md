# PERSISTENT_STORAGE.md — buyer volumes with incremental, deduplicated snapshots

VMs on Petabyte are ephemeral: when an instance ends, its disk is gone. **Persistent volumes**
give a buyer storage that **outlives any single VM** — datasets, checkpoints, and model weights
that survive across runs and can be restored onto a fresh instance later.

The design goal, stated by the requirement, is **cheap**: *"only deltas and important stuff, not a
whole disk mirror — and once a user needs it, send the delta."* So a volume is **not** a block
device we mirror byte-for-byte. It is a **content-addressed store** where:

- each snapshot is a **manifest** of the files you chose to keep (`path → sha256 → size`);
- content is addressed by its **sha256**, so identical/unchanged content is stored **exactly once**
  (deduplication) — within one snapshot and across every snapshot of the volume;
- a new snapshot only uploads the **delta** — the blobs it doesn't already have;
- a restore *"since"* an earlier snapshot returns **only the files that changed** — the delta the
  client still needs, not the whole tree.

You are billed for **unique bytes held** (`bytes_stored`), never for the logical size of every copy.

```
snapshot v1  a.bin b.bin a_copy.bin        blobs stored:  [A] [B]          (a_copy dedups to A)
snapshot v2  a.bin B.bin a_copy.bin d.bin  blobs added:      [B2] [D]      (a.bin/a_copy unchanged)
                                           delta uploaded:   only B2 + D
restore v2 "since v1"                       sent:            only b.bin + d.bin
```

## Where the bytes live

Content blobs live in **object storage** (the same `S3_BUCKET` used for backups; `S3_STUB=true`
writes to a local dir for tests). Each blob is one object, namespaced per tenant and volume:

```
volumes/<buyer_id>/<volume_id>/blobs/<sha256>
```

The database keeps only the **index** — which blobs a volume holds (`volume_blobs`), and the
per-snapshot manifests (`volume_snapshots`). Deleting a volume is a clean prefix wipe.

## The API

All routes require the buyer's bearer token. A buyer only ever sees their own volumes (a foreign id
returns `404`, so ids aren't enumerable across tenants).

| Route | What it does |
|---|---|
| `POST /volumes` `{name, size_limit_gb?}` | create a volume |
| `GET /volumes` | list your volumes (deduped bytes held, snapshot count, dedup savings) |
| `GET /volumes/{id}` | one volume + its snapshots + `dedup_saved_bytes` |
| `DELETE /volumes/{id}` | delete the volume, all snapshots, and every blob from object storage |
| `POST /volumes/{id}/snapshot/plan` `{files:[…]}` | **which blobs are missing** (the delta to upload) |
| `PUT /volumes/{id}/blobs/{sha256}` (raw body) | upload one blob; **sha is verified server-side** |
| `GET /volumes/{id}/blobs/{sha256}` | download one blob |
| `POST /volumes/{id}/snapshot` `{files:[…], label?, vm_id?}` | record a snapshot; returns `delta_bytes` |
| `GET /volumes/{id}/snapshots/{sid}/restore?since=<sid>` | restore manifest; with `since`, only the delta |

A file entry is `{"path": "...", "sha256": "<64 hex>", "size": <bytes>}`.

### Two-phase write — "only send the delta"

Snapshots are taken from a VM (by the agent or CLI), not from the browser. The flow is:

1. **Plan.** Hash the files you want to keep and `POST …/snapshot/plan`. The server compares your
   manifest against the blobs the volume already holds and returns `missing` — the blobs it does
   **not** have. That is your delta.
2. **Upload the delta.** For each missing blob, `PUT …/blobs/<sha256>` with the raw bytes. The
   server recomputes the sha256 of the body and **rejects** it if it doesn't match the URL
   (`400 SHA_MISMATCH`) — content addressing is enforced server-side, so a client can't mislabel
   content. A blob already in storage is an idempotent no-op (`deduped: true`).
3. **Finalize.** `POST …/snapshot` with the full manifest. Every referenced blob must be present in
   object storage (uploaded now, or held from an earlier snapshot) — otherwise `400 BLOB_MISSING`,
   so there are no phantom snapshots. The response's **`delta_bytes`** is the new unique bytes this
   snapshot added — that's all it cost.

### Restore — full, or just the delta

`GET …/snapshots/{sid}/restore` returns the manifest with a `download_path` on each file. Fetch each
blob and write it to `path` to reconstruct the snapshot byte-for-byte.

With **`?since=<earlier snapshot id>`**, the server diffs the two manifests by `path` and returns
**only the files whose content changed** — the delta a client that already has the earlier snapshot
still needs. `delta_size` vs `full_size` shows the saving.

## Worked example (mirrors `volumes_test.py`)

```
# v1: two distinct files + one duplicate  -> 3 files, 2 unique blobs
plan   -> missing = [A, B]         (nothing held yet)
PUT A ; PUT B
snap1  -> delta_bytes = |A|+|B| ,  total_bytes = 2|A|+|B|   (the duplicate cost nothing)

# v2: change b.bin, add d.bin, a.bin/a_copy.bin unchanged
plan   -> missing = [B2, D]        (a.bin dedups; only the 2 changed/new blobs)
PUT B2 ; PUT D                     (upload ONLY the delta)
snap2  -> delta_bytes = |B2|+|D| ; volume bytes_stored grew by EXACTLY that

restore v2            -> all 4 files
restore v2 since v1   -> only b.bin + d.bin        (the delta)
```

## Accounting

- `bytes_stored` — sum of **unique** blob sizes actually held. The real cost.
- `snapshot.total_bytes` — the **logical** size of the snapshot (sum of all its file sizes,
  duplicates included).
- `snapshot.delta_bytes` — the **new** unique bytes that snapshot added.
- `dedup_saved_bytes` — `Σ(snapshot.total_bytes) − bytes_stored`: what dedup + incrementality saved.

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `S3_BUCKET` | — | object-storage bucket for blobs (required; volumes 503 without it) |
| `S3_STUB` | `true` | write blobs to a local dir instead of S3 (tests/dev) |
| `S3_SSE` | `AES256` | server-side encryption for blob objects |
| `VOLUME_MAX_BLOB_MB` | `1024` | cap on a single blob uploaded through the API |

## Scale note (through-API vs. presigned)

The `PUT/GET …/blobs/{sha}` path streams blob bytes **through the API**, which is simple and fully
testable with `S3_STUB`. It buffers a blob in memory, so it is bounded by `VOLUME_MAX_BLOB_MB`. At
larger scale the same content-addressed protocol works **direct-to-S3**: `…/snapshot/plan` can hand
back presigned `PUT` URLs for the missing blobs and restore can hand back presigned `GET` URLs, so
bytes never transit the API. The DB index, dedup, delta accounting, and manifests are unchanged —
only the transport moves. (`utils.mint_presigned_put/get` already exist for this.)

## Security

- **Tenant isolation** — every route checks the volume belongs to the caller; blob keys are
  namespaced by `buyer_id`, so a sha collision across tenants can never cross-read.
- **Content addressing** — the server verifies `sha256(body) == url` on every upload, and a blob
  download is refused unless the sha is in that volume's index. Integrity is verifiable end-to-end:
  a restored file's sha256 must equal the manifest entry.
- **No phantom state** — finalizing a snapshot whose blobs weren't uploaded is refused.
- **Audit** — volume create / snapshot / delete are written to the tenant audit log.

## Tests

`lumaris_api/volumes_test.py` (hermetic, `S3_STUB`, in CI) proves the whole loop: intra- and
cross-snapshot dedup, delta-only upload, delta-only restore, byte-for-byte reconstruction,
content-addressing enforcement, tenant isolation, and blob wipe on delete.
