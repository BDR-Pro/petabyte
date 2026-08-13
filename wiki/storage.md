# Persistent storage

VMs on Petabyte are **ephemeral** — when an instance ends, its disk is gone. **Persistent volumes**
give a buyer storage that outlives any single VM: datasets, checkpoints and model weights that
survive across runs and restore onto a fresh instance later.

> Summary here; full reference in [`docs/PERSISTENT_STORAGE.md`](../docs/PERSISTENT_STORAGE.md).

## The idea: incremental, not a mirror

A volume is **not** a full-disk copy. It's a **content-addressed** store:

- files are addressed by their `sha256`, so identical/unchanged content is stored **once**
  (deduplication) — within a snapshot and across every snapshot;
- a new snapshot uploads only the **delta** (the blobs it doesn't already have);
- restoring *"since"* an earlier snapshot returns only the files that **changed** — "once you need
  it, send the delta."

You pay for **unique bytes held**, never for the logical size of every copy.

```
snapshot v1  a.bin b.bin a_copy.bin        stored:  [A] [B]         (a_copy dedups to A)
snapshot v2  a.bin B2    a_copy.bin d.bin  uploaded: only [B2] [D]  (a.bin unchanged)
restore v2 "since v1"                       sent:     only b.bin + d.bin
```

## Using it

**In the console:** *Storage* tab — create a volume, see snapshots with per-snapshot delta vs
logical size, and how much dedup saved. Snapshots are taken from a VM with the agent/CLI; a restore
ships only the delta.

**Concepts you'll see:**

- **Volume** — your named persistent store.
- **Snapshot** — a point-in-time manifest of files (`path → sha256`).
- **Blob** — one piece of content, stored once and shared.
- **Delta** — the new bytes a snapshot added / a restore still needs.

## Where the bytes live

Content blobs live in **object storage** (the same `S3_BUCKET` used for backups; a local stub is used
in dev/tests). The database keeps only the index and manifests, so deleting a volume is a clean wipe.
Tenants are isolated — a foreign volume id returns *not found*, and content addressing means a hash
collision can never cross-read another tenant.

## Related: seller spare-disk rental

Different feature, same neighbourhood: a **seller** can rent out **spare disk** to a decentralized
storage network for extra income (see [For sellers](sellers.md)). That's about earning from unused
disk; persistent volumes are about a **buyer** keeping data between runs.
