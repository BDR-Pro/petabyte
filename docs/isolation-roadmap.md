# isolation-roadmap.md — Docker now, Firecracker later

The decision, why, and the concrete migration path. This is the single most
important technical choice in the product, because **isolation strategy and
product scope are the same decision**.

---

## The problem

Petabyte runs **arbitrary buyer code on strangers' machines**, and puts
**strangers' data on buyer-chosen hardware**. That is a two-way trust problem:

1. Protect the **seller's** machine from malicious buyer workloads.
2. Protect the **buyer's** data/model from a snooping or tampering seller.

The container/VM boundary is what enforces both. Get it wrong and someone's rig
gets cryptomined, or someone's model/dataset gets stolen.

---

## Decision: **Docker now (hardened), Firecracker/Kata later**

### Phase 1 — NOW: Docker, scoped to managed templates + hardened

Ship with Docker because the agent, job runner, and templates are already built
on it. To make it safe enough to launch, we constrain **scope** and **harden the
runtime**:

- **Scope:** offer **managed templates only** (Blender, ComfyUI, SD, vLLM,
  Ollama, FFmpeg, game servers, notebooks) — **not raw root SSH into arbitrary
  VMs**. When we control the image and entrypoint, a container is a reasonable
  boundary. This maps exactly to the `/gamers` and `/artists` product surfaces.
- **Harden the Docker runtime** on seller nodes:
  - `--read-only` rootfs where possible, `--cap-drop=ALL` then add back only what
    a template needs, `--security-opt=no-new-privileges`.
  - seccomp + AppArmor profiles; drop `SYS_ADMIN`, `NET_ADMIN`, etc.
  - `--pids-limit`, `--memory`, `--cpus`, `--gpus` caps; no host network; no
    `--privileged`; no docker socket mount.
  - user namespaces (`userns-remap`) so container root != host root.
  - **gVisor (`runsc`) as the runtime** — a user-space kernel that intercepts
    syscalls. Much stronger isolation than stock Docker, keeps the OCI/Docker
    workflow, and supports GPUs (with caveats). This is the cheapest real
    isolation upgrade and should be the default runtime on nodes.

**Why this is enough to launch:** with a fixed image + entrypoint and gVisor, the
buyer can't run arbitrary escape attempts against the host kernel, and the seller
can't trivially read the container's memory. Not perfect, but shippable and
honest for a v1 managed-workload marketplace.

### Phase 2 — LATER: microVMs (Firecracker / Cloud Hypervisor / Kata)

When we want **raw VM rental** (root SSH, custom kernels, "feels like a real
machine") or **enterprise-grade isolation** for sensitive models, move to
microVMs:

- **Firecracker** (AWS Lambda/Fargate) or **Cloud Hypervisor**: real KVM
  hardware isolation (a **separate kernel per tenant**), ~125 ms boot, tiny
  overhead. VM-grade isolation at container-grade density.
- **Kata Containers**: keep the Docker/OCI interface, but each container is
  transparently backed by a lightweight VM. Easiest migration — the agent's
  existing `docker run` calls mostly survive; you swap the runtime.
- **Why not plain KVM/QEMU:** slow boot, heavy RAM, and brutal GPU passthrough on
  consumer/home nodes. microVMs are the compromise.

**The hard part, stated plainly:** **GPU passthrough into a microVM on
heterogeneous consumer hardware** (VFIO/IOMMU, driver control, seller loses the
GPU while passed through) is the single hardest problem in the product. It is
exactly why Vast.ai / RunPod are valuable. It is NOT a weekend swap and should
not block Phase 1.

### Migration cost (why Phase 1 code survives)

| Layer | Phase 1 (Docker+gVisor) | Phase 2 (Kata/Firecracker) | Reuse |
|---|---|---|---|
| Agent job runner | `docker run` | `docker run` w/ `runtime=kata`, or Firecracker via containerd | High |
| Templates | OCI images | same OCI images | Full |
| Escrow / booking / marketplace | unchanged | unchanged | Full |
| Attestation | Ed25519 (see stub.md) | + TEE measurement (SEV-SNP/TDX) | Extend |
| Networking/tunnel | frp/WireGuard (see vm-rental) | same | Full |
| Checkpoint/restore | `docker commit`/volume tar → S3 | VM snapshot → S3 | Rework |

The only real rework is **checkpoint/restore** (containers snapshot poorly; VMs
snapshot cleanly) and **attestation** (add real hardware measurement). Everything
else — the marketplace, money, routing — is runtime-agnostic.

---

## What to build in Phase 1 (actionable)

1. Ship the **gVisor runtime** in the seller agent install (`runsc` +
   `--runtime=runsc` on template launches). Fall back to hardened stock Docker if
   `runsc` unavailable, and record which runtime a node uses (surface it as a
   trust signal in the marketplace).
2. Apply the **hardening flags** above to every template launch in the agent.
3. Keep the product to **managed templates** (no raw SSH) until Phase 2.
4. Document the boundary honestly to buyers: "managed workloads, isolated with
   gVisor; confidential-compute attestation is Ed25519 software attestation today
   (see stub.md), hardware TEE is on the roadmap."

## What to build in Phase 2

1. Kata runtime on capable nodes; Firecracker for the managed fleet.
2. Real TEE attestation (SEV-SNP / TDX report verification) replacing
   `_verify_stub` in `utils.py`.
3. VM snapshot→S3 + restore for the failover model (see vm-rental doc).
4. GPU passthrough into microVMs — the big spike; prototype on a single known
   GPU/driver combo before promising it in the marketplace.

---

## One-line summary

**Sell managed workloads on hardened Docker + gVisor now; add microVMs
(Kata → Firecracker) and real TEE attestation when we sell raw VMs or need
enterprise isolation. The marketplace, escrow, and routing don't change — only
the runtime and the checkpoint layer do.**
