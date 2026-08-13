# Distributed compute — Petabyte is another provider, not an infra change

Big-corp, academic, and government workloads (NASA, national labs, universities) already run on a
scheduler they trust — **Slurm**, **MPI/OpenMPI**, **Ray**, or **Kubernetes**. They are not going to
rewrite their stack to use a new vendor. So Petabyte plugs in the way an extra cloud does: it
supplies **GPU nodes on different machines, wired into one cluster over the VPN**, and hands the
cluster back as the exact artifacts your launcher already consumes. Your control plane stays put.

## What Petabyte gives you

`POST /distributed` gang-schedules N GPUs across **distinct machines** (one rank per provider — never
two ranks on the same PC), escrows them all-or-nothing, assigns ranks `0..N-1`, and coordinates
rendezvous over the VPN. Once each rank has registered its VPN address (`POST /jobs/rendezvous`),
the cluster is exportable:

| Endpoint | What you get |
|---|---|
| `GET /jobs/{job_id}/hostfile` | An **MPI / torchrun hostfile** — `<vpn_host> slots=<gpus>` per line |
| `GET /jobs/{job_id}/cluster` | The full node list + master address + **ready-to-run launch commands** |
| `GET /jobs/manifest/{job_id}` | Per-rank status (running / done / failed) |

Everything travels over the WireGuard mesh, so the nodes talk to each other exactly as if they were
on one LAN — that is what makes NCCL/MPI collectives work across machines.

## MPI / OpenMPI

Zero code change — feed the hostfile straight into `mpirun`:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://petabyte.market/jobs/$JOB/hostfile > hostfile
mpirun --hostfile hostfile -np $(wc -l < hostfile) ./my_mpi_app
```

## PyTorch (torchrun / DDP / FSDP)

Take the master address from `/cluster` and run torchrun on each node with its rank:

```bash
torchrun --nnodes=$N --nproc_per_node=$GPUS_PER_NODE \
  --node_rank=$RANK --rdzv_backend=static \
  --master_addr=$MASTER_HOST --master_port=$MASTER_PORT \
  train.py
```

`/cluster.launch.torchrun` prints this line pre-filled for the running cluster.

## Ray

```bash
# rank 0
ray start --head --port=$MASTER_PORT
# every other rank
ray start --address=$MASTER_HOST:$MASTER_PORT
```

Both commands come back from `/cluster.launch` (`ray_head`, `ray_worker`).

## Slurm (cloud-bursting — keep slurmctld, add Petabyte capacity)

Slurm's elastic computing already knows how to grow into a cloud. Point its power-save hooks at
Petabyte so `slurmctld` provisions Petabyte nodes on demand and they join your existing controller:

```ini
# slurm.conf (elastic / power-save)
SuspendProgram=/etc/slurm/petabyte-suspend.sh
ResumeProgram=/etc/slurm/petabyte-resume.sh
PartitionName=petabyte Nodes=pb[0-99] MaxTime=INFINITE State=CLOUD
```

`petabyte-resume.sh` calls `POST /distributed` (or provisions individual nodes) for the requested
node count; the nodes come up, register, and report to `slurmctld` like any other cloud node.
`petabyte-suspend.sh` releases them. Your users keep running `sbatch`/`srun` unchanged — Petabyte is
just another partition.

## Kubernetes

Join the Petabyte GPU nodes to your cluster as autoscaled workers behind your existing scheduler
(Volcano / Kubeflow / the default scheduler). Your `Job`/`PyTorchJob`/`MPIJob` manifests are
unchanged; Petabyte only adds schedulable GPU capacity.

## SkyPilot

The same model SkyPilot uses for clouds applies here: Petabyte is another provider of GPU nodes.
Point your job at the pool and let the cluster spec + hostfile drive the launcher.

## Execution — what each node actually does (not just scheduling)

The endpoints above assemble and export the cluster. **Execution** is the other half: when a node's
agent claims its rank (`task_type: distributed`), `lumaris_agent/task_fetcher._run_distributed`:

1. **registers** its own VPN-reachable address (`POST /jobs/rendezvous`) so the whole cluster
   becomes addressable — rank 0's registration also elects it master (server-enforced; no other
   rank can hijack it);
2. **resolves the master** — rank 0 is its own master immediately; every other rank polls
   `GET /jobs/rendezvous/{job_id}` until rank 0 is up (a master that never appears fails the rank,
   and gang-scheduled, the whole cluster);
3. **executes** — either
   * launches your container under `torchrun` wired to `--master_addr / --node_rank / --nnodes`
     (`distributed_run.build_torchrun_cmd`), or
   * runs the built-in **cluster self-test** (`selftest: true`): a real cross-process all-reduce; and
4. **reports a signed result** — the same attested-key path every job uses, so a distributed run is
   cryptographically bound to real hardware. The cluster is marked complete only once every rank's
   signed result arrives; any rank reporting `failed` fails the whole gang-scheduled run.

The coordination logic (rendezvous resolution, the torchrun command, the all-reduce collective)
lives in `lumaris_agent/distributed_run.py`, dependency-free (Python stdlib only), so it runs and is
tested on any box — no GPU, no torch, no Docker, no WireGuard.

### The cluster self-test (`selftest: true`)

A no-GPU, no-image "does my cluster actually work end-to-end?" smoke test. Each rank performs a real
all-reduce (reduce→broadcast through the master over TCP): every rank contributes a distinct vector,
and every rank must end holding the identical, correct element-wise sum. `distributed_run_test.py`
proves this with **real OS processes** — N independent processes, each a rank, rendezvous through the
master and reduce over real sockets — asserting all converge on the right answer and that a missing
rank fails the run (no false success). Production GPU jobs use NCCL's ring all-reduce over the
WireGuard mesh; this built-in exists to validate the wiring, not to replace NCCL.

---

**Honesty note.** Gang-scheduling, rendezvous, hostfile/cluster export, escrow, and gang-failure are
implemented and tested in `lumaris_api/distributed_test.py`. **Execution is now implemented and
tested too**: the agent-side rank execution path (`_run_distributed` → register → resolve master →
`torchrun` launch / built-in all-reduce → signed result), the real signed-result completion + gang
failure through the live `/jobs/result` endpoint (`distributed_test.py`), and a real multi-process
all-reduce where every rank converges on the correct answer (`lumaris_agent/distributed_run_test.py`).
What is still a **recipe you run against these endpoints** (not first-party code): the external
launcher integrations (mpirun / torchrun / ray / Slurm `ResumeProgram`) — Petabyte supplies the
addressable, executing cluster; your scheduler drives it. Deep first-party plugins (a packaged Slurm
burst daemon, a K8s device plugin, a SkyPilot cloud adapter) are the natural next step and are not
claimed to ship today. The **built-in all-reduce self-test runs on CPU over TCP** and is a wiring
validator; **NCCL/GPU collectives over the mesh** are what a real training job uses.
