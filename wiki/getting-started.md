# Getting started

Two five-minute paths, depending on why you're here. Everything below works in **TEST MODE** (the
default sandbox) — no real money moves.

## I want to rent GPUs (buyer)

**In the browser**

1. Open the site and **Sign in** (or register). 
2. Go to the **Console** (`/console`).
3. Open **Wallet & billing** → **Add funds** (test credit in the sandbox).
4. Open **Compute** → paste code → **Run on cheapest GPU**. Petabyte books the cheapest matching
   GPU, escrows the hour, runs it, and streams the result back.

**On the command line**

```bash
pip install httpx                    # the CLI's only dependency
export PETABYTE_API_URL=http://localhost:8000   # or your Petabyte host
python cli/petabyte.py register -u alice -p 'correct horse battery'
python cli/petabyte.py login    -u alice -p 'correct horse battery'
python cli/petabyte.py deposit  50
python cli/petabyte.py specs                     # see available GPUs
python cli/petabyte.py run hello.ipynb --gpu H100 --hours 1
```

More in [For buyers](buyers.md) and the [CLI](cli.md).

## I want to earn from my GPU (seller)

1. On the machine with the GPU, install the **agent** (one line from `/install`):
   ```bash
   curl -fsSL https://<your-petabyte-host>/i/<token> | bash
   ```
   The installer bakes in a node key and the server URL, sandboxes the runtime, and starts the
   agent as a service.
2. The agent **attests** the GPU, benchmarks it, and lists it. Watch it come online in the
   **Console → Nodes & earnings** tab.
3. Earnings accrue as jobs run; withdraw from **Wallet & billing** once you've verified a payout
   method. (Optional: also rent **spare disk** and mine when **idle** — see [For sellers](sellers.md).)

## I just want an AI model on my machine

You don't even need an account for this:

```bash
petabyte model search qwen
petabyte model pull Qwen/Qwen3-8B     # downloads + verifies + caches locally
petabyte model list
```

See [Models](models.md).

## I want to run my own Petabyte

See [Self-hosting](self-hosting.md) — one database URL and a handful of env vars to start; the app
runs with everything optional turned off.
