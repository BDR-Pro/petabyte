"""disk_node.py — rent a node's SPARE DISK to a web3/BitTorrent storage network.

The disk analogue of the idle NiceHash miner: a seller pledges unused disk to an existing
decentralized storage network (Storj / BTFS / Sia) and earns a background trickle. It runs
ALONGSIDE paid GPU jobs (disk is not the GPU), so it is never preempted.

Attribution — the NiceHash model: every node contributes under a UNIQUE node name
(`pbdisk-<spec_id>`) and points at PETABYTE's platform wallet, so a settled provider payout maps
1:1 back to the seller (`db.reconcile_disk_earnings`) and lands in their unified balance. There is
no per-seller storage wallet.

This module is the pure, dependency-free (stdlib-only) part — the exact `docker run` argv for a
storage node and the provider table — so it is unit-testable on any box with no Docker, no network,
and no provider account. `task_fetcher` calls it to start/stop/remove the container.

HONEST STATUS: this builds the container-launch + attribution scaffold. Bringing a real Storj/BTFS/
Sia node fully online also needs provider onboarding (identity/auth tokens, a funded platform
wallet) — the operator step documented in docs/DISK_RENTAL.md, exactly like NiceHash needs org
credentials. The node name + reconcile path are real and tested.
"""
import os

# import name -> the storage-node image each provider ships.
PROVIDER_IMAGES = {
    "storj": "storjlabs/storagenode:latest",
    "btfs": "btfs/node:latest",
    "sia": "ghcr.io/siafoundation/hostd:latest",
}


def provider_supported(provider: str) -> bool:
    return bool(provider) and provider.lower() in PROVIDER_IMAGES


def container_name(node_name: str) -> str:
    return f"petabyte-disk-{node_name}"


def data_dir_for(node_name: str) -> str:
    base = os.getenv("DISK_DATA_DIR", "/var/lib/petabyte/disk")
    return os.path.join(base, node_name)


def build_disk_cmd(*, provider: str, node_name: str, alloc_gb: int, data_dir: str,
                   wallet: str = None, image: str = None, extra_env: dict = None,
                   isolation_flags=None) -> list:
    """The `docker run` argv for a storage node. Pure (no subprocess), so it is unit-testable.

    * `alloc_gb` is the seller's HARD cap on pledged space — it bounds every provider's max-storage
      flag, so the node can never exceed what the seller allowed.
    * `node_name` (`pbdisk-<spec_id>`) is the attribution key, passed to every provider.
    * `wallet` is PETABYTE's platform wallet (earnings pool centrally, credited per node) — never a
      per-seller wallet.
    """
    provider = (provider or "").lower()
    if not provider_supported(provider):
        raise ValueError(f"unsupported storage provider: {provider!r}")
    alloc_gb = int(alloc_gb)
    if alloc_gb < 1:
        raise ValueError("alloc_gb must be >= 1")
    image = image or PROVIDER_IMAGES[provider]
    cmd = ["docker", "run", "-d", "--rm", "--name", container_name(node_name),
           "-v", f"{data_dir}:/data",
           "-e", f"PB_NODE_NAME={node_name}",       # attribution key (all providers)
           "-e", f"PB_ALLOC_GB={alloc_gb}"]
    # Provider-specific: cap max storage at the seller's alloc, name the node, point at the wallet.
    # (Exact flags per image are documented in docs/DISK_RENTAL.md; kept minimal + provider-agnostic.)
    if provider == "storj":
        cmd += ["-e", f"STORAGE={alloc_gb}GB", "-e", f"WALLET={wallet or ''}",
                "-e", f"STORJ_NODE_NAME={node_name}"]
    elif provider == "btfs":
        cmd += ["-e", f"BTFS_STORAGE_MAX={alloc_gb}GB", "-e", f"BTFS_NODE_NAME={node_name}"]
    elif provider == "sia":
        cmd += ["-e", f"HOSTD_MAX_STORAGE={alloc_gb}GB", "-e", f"HOSTD_WALLET={wallet or ''}"]
    for k, v in (extra_env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    cmd += list(isolation_flags or [])
    cmd += [image]
    return cmd


def data_dir_bytes_gb(path: str) -> float:
    """Best-effort used space (GB) under the node's data dir, for the seller's usage report.
    Never raises — returns 0.0 if the dir is absent or unreadable."""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        return 0.0
    return round(total / 1e9, 4)


def est_daily_usd(alloc_gb: int, usd_per_tb_month: float) -> float:
    """A planning estimate of the daily trickle from `alloc_gb` at a $/TB/month reference — the
    seller sees this before opting in. Not a payout figure; real earnings come from the provider."""
    return round((float(alloc_gb) / 1000.0) * float(usd_per_tb_month) / 30.0, 4)
