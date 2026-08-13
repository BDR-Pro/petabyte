# For sellers

Turn a GPU that's sitting idle into income. Selling happens through the **agent** (a small daemon you
install on the machine) plus the **Console → Nodes & earnings** tab.

## 1. Install the agent

From `/install`, copy the one-line installer (it bakes in a node key + your server URL):

```bash
curl -fsSL https://<your-petabyte-host>/i/<token> | bash      # Linux
# Windows: the same page gives a PowerShell one-liner
```

The installer:

- registers the node and stores its key,
- **sandboxes** the runtime (buyer jobs run in locked-down containers with egress restricted by
  default — hosting a stranger's job won't put your home IP at risk),
- installs the agent as a service that auto-updates.

You can also start **wallet-only** (no signup): paste a payout wallet and get an installer
immediately. That node runs and earns, but you must complete verification before you can withdraw.

## 2. Get verified & listed

The agent automatically:

- **Attests** the GPU (proves it's real and what it claims — an unattested GPU can't be booked),
- runs a **benchmark** that Petabyte re-times server-side (trust is earned from real numbers, never
  self-report),
- lists the GPU with an auto-derived price you can override.

Watch it appear under **Console → Nodes & earnings**.

## 3. Earn

- **Rent the GPU.** When a buyer books it, the escrowed amount is released to you (minus the platform
  fee) when the job completes. Your unified balance grows.
- **Rent spare disk (optional).** Contribute idle disk to a web3/BitTorrent storage network for extra
  income — explicit opt-in with a provider + GB cap. See `docs/DISK_RENTAL.md`.
- **Mine when idle (optional).** Opt in to NiceHash-style mining only while the GPU is unrented, so
  the card never sits truly idle.

These are independent: disk earns whether or not a job is running; idle mining only fills the gaps
between rentals.

## 4. Withdraw

Add a payout method (bank / USDC / gift card) under the earnings page, pass verification (KYC where
required), then withdraw from **Console → Wallet & billing**. Earnings mature after a short hold and
a minimum number of completed jobs, to protect against clawbacks.

## The trust ladder (why verification matters)

Buyers filter by trust. You climb the ladder by doing real work: attested → benchmark-verified
(server-timed) → job-proven (completed real jobs, results bound to output hashes) → optionally
confidential (TEE) or region-verified (GeoIP). Higher trust = more bookings. See
[Payments & trust](payments-and-trust.md).

## Model cache-locality (bonus)

If your node already holds a model in its `~/.petabyte` cache, the scheduler prefers it for jobs that
request that model — so a 20–100 GB weight file isn't re-downloaded. A node reports its cached
models to `POST /nodes/models`; availability is visible at `/api/models/availability`. See
[Models](models.md).

## Seller checklist

1. Install the agent → 2. It attests + benchmarks + lists automatically → 3. Earn as jobs run
(optionally add disk/idle) → 4. Verify a payout method and withdraw.
