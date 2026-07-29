# pilot.md — how to get Petabyte into a real test, and only then go live

**The mistake to avoid:** flipping `PAYMENTS_MODE=live` because the code is ready. The
code being ready is not the question. The question is whether a stranger's GPU, on a
stranger's home internet, can hold a stranger's workload for six hours without anyone
losing money or getting a letter from their ISP. You cannot find that out in a test suite.

Five stages. **Each has a gate you must pass before the next.** Do not skip. Do not run
two at once. Real money is stage 4, not stage 1.

---

## Stage 0 — Pre-flight (nobody but you, ~1 day)

Everything in `deploy.md`. Specifically, the things that are dangerous to forget:

- [ ] **Canonical domain.** Kill `www` / `space`. The 502 login on the old site is the
      single most damaging thing a visitor can find.
- [ ] **Rotate `SECRET_KEY` and the Fernet key.** They were exposed in chat. Treat them as
      permanently compromised — they are.
- [ ] `TRUSTED_PROXIES=<your nginx>` — without it `X-Forwarded-For` is ignored (safe); with
      a *wrong* value, clients can spoof their IP and country.
- [ ] `REAPER_DISABLED=true` on the API workers + `lumaris-reaper.service` running.
- [ ] `ENVIRONMENT=production` — **the app now refuses to boot with any stub on.** Let it.
- [ ] Run `postgres_test.py` against **your managed Postgres**, not a stock container.
- [ ] Sentry + UptimeRobot on `/health/ready`. Alert on `maintenance.stale == true`.

**GATE 0:** `curl https://petabyte.market/health/ready` is green, `/login` is 200 not 502,
and the app booted with `ENVIRONMENT=production`.

---

## Stage 1 — Prove the tunnel on real machines (half a day)

`docs/vm-runbook.md`, Phase A. Two cheap VMs + your laptop. On the "node", **block all
inbound** — that is what makes it an honest simulation of a home router.

```bash
ssh -p 20017 root@gateway.petabyte.market     # a shell INSIDE the container
```

**GATE 1:** you get that shell, on a box with no inbound ports open. If this fails, nothing
else on this page matters. **Do not proceed to Stage 2 until it passes.**

Then Phase B (`ssh vm-<handle>@petabyte.market`) and the failover test (kill node A, same
handle lands on node B).

---

## Stage 2 — Dogfood: you are the first seller AND the first buyer (1 week)

Now use your own real GPU machine as a seller. Real agent, real install script, real home
internet. **Payments stay in sandbox.** The money is fake; everything else is real.

Run for **72 hours minimum**, and actually use it:

- [ ] Install the agent from the real one-liner on a machine you did **not** develop on.
      (Developing on it hides the bugs — missing Docker, wrong driver, no CUDA.)
- [ ] Launch a real workload you'd actually run. Not a hello-world. ComfyUI, a Blender
      render, an Ollama server. Use it like a customer.
- [ ] Leave a VM running overnight. Does the heartbeat survive a laptop sleeping, a router
      reboot, a Windows update, a dynamic-IP change?
- [ ] **Deliberately kill the seller machine mid-rental.** Watch failover happen. Reconnect
      with the same handle. Verify you land on the snapshot, and that you were billed for
      what you used and refunded the rest.
- [ ] Stop a VM. Check the ledger: `ledger_is_balanced(db)` and
      `account_balance(db, acct_buyer(uid))` matches the wallet.

**What will break first (my predictions, in order):**
1. The agent on a machine that isn't yours — Docker missing, GPU driver mismatch, WSL.
2. The heartbeat across a home router that NATs aggressively or rotates IPs.
3. Snapshot restore. Upload succeeding is not the same as restore working. **Test restore.**

**GATE 2:** 72 hours, at least one real workload, at least one forced failover recovered,
ledger balanced at the end. Zero unexplained money discrepancies.

---

## Stage 3 — Friendly sellers: 3–5 real GPU owners you know (2–3 weeks)

Strangers' hardware, still **sandbox money**. This is where you learn what the product
actually is. You want *hardware diversity*: a gaming PC on Windows, a Linux box, a laptop
that sleeps, someone on bad Wi-Fi.

This stage is not about revenue. It's about answering:

- Does the install actually work for someone who isn't you, without you on a call?
- How often do nodes drop, and does failover cover it or just annoy people?
- Does a seller understand what they're agreeing to?

### The thing that will hurt a seller, and that you have not solved

**A rented VM gets network egress on someone's home connection.** If a buyer port-scans,
spams, joins a botnet, or mines on it, it is *your seller's* IP address and *your seller's*
ISP that gets the abuse complaint. They can lose their home internet. That is a real,
personal cost you are asking a volunteer to bear.

Before a stranger's machine takes an untrusted workload, you need at least:

- [ ] **Egress policy per template.** Batch jobs → `--network none` (already the case for
      some paths). Interactive/serving templates → allow-list, not "the whole internet".
- [ ] **A written, honest warning at install time.** Not buried in the AUP.
- [ ] **A kill switch** (below) so you can stop a bad workload in seconds, not minutes.
- [ ] Abuse reporting route + a plan for what you do at 2am when a seller's ISP calls them.

**GATE 3:** ≥3 non-you sellers online for ≥1 week. ≥10 real rentals. You know your node
drop rate. No seller has had an abuse complaint. At least one seller says the payout
number they'd want — and it isn't insulting.

---

## Stage 4 — Real money, deliberately tiny (4+ weeks)

**Only now** `PAYMENTS_MODE=live`. Constrain everything:

- [ ] **Caps.** Max wallet deposit ($50). Max concurrent VMs per buyer. Max rental length.
      A buyer cannot lose more than they deposited (escrow is prepaid) — but a *surprise*
      is still a churned customer.
- [ ] **Manual payout approval.** `PAYOUT_STUB=false`, but a human (you) approves every
      payout for the first month. This is your fraud tripwire.
- [ ] **Real KYC/AML on sellers before their first payout.** Not at signup — at payout.
- [ ] **Reconcile daily.** Stripe's settled total vs `account_balance(db, EXTERNAL_PAYMENTS)`.
      If they ever disagree, stop and find out why *that day*.
- [ ] Watch `ledger_is_balanced()` on a cron. It should never be false. If it is, halt.

### Before you touch real money: get actual advice

You are taking funds from buyers, holding them, and paying third parties. In most
jurisdictions that is a regulated activity, and Saudi Arabia has its own regime (SAMA).
I am not a lawyer and this is not legal advice — but "we're just a marketplace" is not a
defence anyone accepts, and you should talk to someone who does this for a living **before**
stage 4, not after. Same for the tax treatment of seller earnings.

**GATE 4:** 4 weeks live, daily reconciliation clean every day, zero ledger imbalances,
every payout manually reviewed, no chargebacks you can't explain.

---

## Stage 5 — Open it

Lift the caps gradually. Automate payouts. Keep the reconciliation cron forever.

---

## What you are missing right now (build before Stage 3)

| Gap | Status |
|---|---|
| ~~Kill switch~~ | **DONE** — `POST /admin/bookings/pause`. Stops new bookings; running rentals untouched. |
| ~~Egress policy per template~~ | **DONE** — batch = no network; agent enforces; defaults closed; ports bound to loopback. |
| ~~Email verification~~ | **DONE** — required before payout destination or withdrawal. |
| ~~Payout takeover protection~~ | **DONE** — password re-auth + verified email + 24h cooling-off + audit. |
| ~~Audit log~~ | **DONE** — `GET /admin/audit`. |
| **Reconciliation cron** | still to do: `ledger_is_balanced()` + Stripe vs `external:payments`, daily, alerting. |
| **Restore drill** | still to do: a successful snapshot upload is not a successful backup. Prove restore on a schedule. |
| **Buyer spend caps** | low priority: escrow is prepaid, so a buyer cannot lose more than they deposited. |

---

## The one-line version

**Prove the tunnel (Stage 1). Then be your own first customer (Stage 2). Then let friends
break it (Stage 3). Money is Stage 4 — and only after a lawyer and a kill switch.**
