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

---

**Honesty note.** The endpoints above (gang-scheduling, rendezvous, hostfile/cluster export,
escrow, gang-failure) are implemented and tested in `lumaris_api/distributed_test.py`. The launcher
integrations (mpirun / torchrun / ray / Slurm ResumeProgram) are **recipes you run against those
endpoints** — Petabyte supplies the addressable cluster; your scheduler drives it. Deep first-party
plugins (a packaged Slurm burst daemon, a K8s device plugin, a SkyPilot cloud adapter) are the
natural next step and are not claimed to ship today.
