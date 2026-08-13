# dynamic_dns.md — a stable per-VM address that survives a node dying

**Question this answers:** *"Can I `ssh root@<id>.vm.petabyte.market`, so when a VM's machine goes
down a backup takes over WITHOUT me handling a new IP?"*

**Answer: yes — that's the whole design.** Each VM has a **stable, opaque id** (e.g.
`q7bk2mrelpza`). Every buyer-facing address is derived only from that id, never from the node's IP.
When the hosting machine dies, the platform restores the VM on another node **keeping the same id**,
so the address you were given is byte-identical. You never edit DNS per VM, and you never run a
dynamic-DNS updater. One static wildcard record covers every VM forever; the **control plane**, not
DNS, follows the VM.

**Use the per-VM subdomain `<id>.vm.petabyte.market`, not `vm-<id>@petabyte.market`.** A VM usually
needs **more than one login user** (`root@` to set up, `app@`/`ubuntu@`/`jupyter@` to run). Putting
the id in the **host** keeps the SSH **username free** for any of them; putting the id in the
username (the `vm-<id>@` form) burns that slot and forces a separate handle per user. The subdomain
also works for HTTP/scp/rsync, not just SSH. See [§3](#3-ssh--and-why-the-subdomain-is-the-canonical-form).

This doc is the **non-code / DNS-records** half. The code side is already built and tested — see
[§6](#6-whats-already-built--tested). The server software to install (frp + sshpiper) is in
[`vm-runbook.md`](vm-runbook.md); this doc is the DNS + client + operator setup around it.

---

## 1. Why no per-VM DNS and no dynamic-DNS updater

The naïve approach would be: give each VM its own DNS A record pointing at the node's IP, and on
failover rewrite that record to the new node's IP (classic "dynamic DNS"). **Don't.** That path is
slow (DNS TTL/propagation), racy, and needs write access to your DNS zone from the control plane.

Petabyte does it at the app layer instead:

```
ssh root@<id>.vm.petabyte.market
        │
        ▼  (DNS: one wildcard record, never changes)
   *.vm.petabyte.market  ─────────────►  GATEWAY (fixed public IP)
        │
        ▼  gateway asks the control plane, per connection:
   GET /vm/<id>/route  (X-Gateway-Token)  ──►  "id <id> is on node N right now"
        │
        ▼  gateway opens a channel down node N's existing outbound tunnel
   buyer  ⇄  gateway  ⇄  node N  ⇄  the VM's sshd / app port
```

On failover the control plane returns a **different** node for the **same** id. The wildcard record
still points at the gateway. **Nothing in DNS changes.** That is why a backup works without a new IP.

---

## 2. The DNS records you actually add

You need exactly **two** kinds of record, both static. Replace `petabyte.market` with your domain
and `203.0.113.10` / `2001:db8::10` with your **gateway** host's public IP(s).

| Type | Name | Value | TTL | Why |
|---|---|---|---|---|
| `A` | `gw.petabyte.market` | `203.0.113.10` | 300 | the gateway host (fixed) |
| `AAAA` | `gw.petabyte.market` | `2001:db8::10` | 300 | IPv6 (optional but nice) |
| `A` | `*.vm.petabyte.market` | `203.0.113.10` | 300 | **wildcard** — every VM subdomain resolves to the gateway |
| `AAAA` | `*.vm.petabyte.market` | `2001:db8::10` | 300 | wildcard IPv6 |

That's it. `q7bk2mrelpza.vm.petabyte.market`, `abc123xyz.vm.petabyte.market`, and every future VM all
resolve to the gateway via the single wildcard. You never add a record when a VM is created or moved.

> **CNAME variant:** point `*.vm.petabyte.market` at `gw.petabyte.market` with a `CNAME` instead of
> duplicating the IPs, if your DNS provider allows wildcard CNAMEs (most do). Then you only ever
> change one record — `gw` — if the gateway itself moves.

**Config knobs (code side):** the app builds the hostname as `<id>.<VM_DNS_ZONE>`.
Set `VM_DNS_ZONE=vm.petabyte.market` (defaults to `BASE_DOMAIN`) so the emitted address matches the
wildcard zone above. `GATEWAY_TOKEN` must be set (shared secret the gateway uses to call
`/vm/<id>/route`). See [`GITHUB_CONFIGURATION_REFERENCE.md`](GITHUB_CONFIGURATION_REFERENCE.md).

---

## 3. SSH — and why the subdomain is the canonical form

A VM often has **more than one login user**: you SSH in as `root` to install a driver, as `app`
(or `ubuntu`, `jupyter`, `postgres`, …) to run the workload, and a script may use a third. The
naming has to leave room for **`<user>@`** to vary. That is the deciding factor between the two
strategies:

| | `<user>@<id>.vm.petabyte.market` (subdomain — **canonical**) | `vm-<id>@petabyte.market` (username routing — fallback) |
|---|---|---|
| **Login user** | **free** — `root@`, `app@`, `ubuntu@`, `jupyter@` all work, same VM | **taken** — the id *is* the username, so there's no slot left for the user |
| **Multiple users** | one address, any user | needs a **separate handle per user** (`vm-<id>-root`, `vm-<id>-app`), each pre-registered in the router |
| **HTTP / browser / scp / rsync** | works (real hostname) | SSH-only |
| **DNS** | one wildcard `*.vm.petabyte.market` | one A record |
| **Client setup** | one-time `~/.ssh/config` line (SSH has no SNI) | none |

So the address the API advertises (`url.ssh` / `url.hostname`) is the **subdomain**. The username
form is kept only as a zero-config fallback for buyers who won't touch their ssh config — and it is
explicitly labelled `url.ssh_username_fallback` because it cannot carry a login user.

### A. Subdomain (canonical) — any login user

```bash
ssh root@<id>.vm.petabyte.market      # driver / setup
ssh app@<id>.vm.petabyte.market       # run the workload
scp file app@<id>.vm.petabyte.market:~/     # and scp/rsync/browsers all work too
```

The id is the **host**; the part before `@` is a normal SSH username the VM's `sshd` authenticates
(the buyer's key is injected at launch as `ssh_pubkey`, and mapped to whichever users the image
allows). Raw SSH sends no hostname, so the buyer's client hands the target to the gateway once via
`~/.ssh/config`:

```ssh-config
Host *.vm.petabyte.market
    # do NOT hard-code User here — leave it free so `root@`, `app@`, ... all work
    ProxyCommand petabyte-connect %h %p
    # petabyte-connect is a ~15-line helper: open a TCP conn to gw.petabyte.market and send %h
    # (the VM host) as the handle — exactly lumaris_gateway/gateway.py:buyer_connect. The gateway
    # resolves %h -> current node; the USERNAME is passed through untouched to the VM's sshd.
```

- **DNS:** wildcard `*.vm.petabyte.market` → gateway (from [§2](#2-the-dns-records-you-actually-add)).
- **Config:** `VM_DNS_ZONE=vm.petabyte.market`.

### B. Username routing (fallback — zero client config, single user)

```bash
ssh vm-<id>@petabyte.market      # e.g. ssh vm-q7bk2mrelpza@petabyte.market
```

- **DNS:** one `A` record for `petabyte.market` (or `gw.petabyte.market`) → gateway. No wildcard.
- **Gateway:** `sshpiperd` reads the id from the `vm-<id>` username, then calls `/vm/<id>/route`.
- **Limitation — this is the whole reason it's the fallback:** the id occupies the username, so it
  logs into **one implicit user**. To offer `root` *and* `app`, you'd mint distinct handles
  (`vm-<id>-root@`, `vm-<id>-app@`) and register each in sshpiper — clumsy. Use the subdomain when
  users vary.

> **Login user vs routing are separate concerns.** *Routing* (which machine) is done by the
> hostname (A) or the `vm-<id>` username (B). The *login user* (`root`/`app`/…) is authenticated by
> the VM's own `sshd` against the injected key. Only the subdomain keeps both independent.

---

## 4. HTTP/HTTPS — cleaner (Host header + SNI exist)

For a VM that serves a web app/port, HTTP does carry the hostname, so pure subdomain routing works:

```
https://<id>.vm.petabyte.market
```

- **DNS:** the same wildcard `*.vm.petabyte.market` → gateway.
- **Gateway:** a reverse proxy (Caddy / nginx / `frps` vhost) routes by the `Host` header →
  `/vm/<id>/route` → current node's tunnel.
- **TLS (wildcard cert):** you cannot get a public cert per random VM host on demand, so issue one
  **wildcard certificate** for `*.vm.petabyte.market` via **Let's Encrypt DNS-01** (HTTP-01 can't do
  wildcards). Caddy/Traefik do this automatically given a DNS-provider API token; certbot does it
  with `--preferred-challenges dns`. Renewal is automatic; nothing per VM.

---

## 5. Operator checklist (non-code)

1. **Stand up a gateway host** with a fixed public IP (a small always-on VM). Open the gateway
   control port + `22`/`80`/`443`. Install `frps` + `sshpiperd` (see [`vm-runbook.md`](vm-runbook.md)).
2. **Add the DNS records** in [§2](#2-the-dns-records-you-actually-add) at your registrar / DNS
   provider (Cloudflare, Route 53, etc.). Keep TTL small (300s) — you'll rarely change them, but a
   small TTL makes the one-time gateway-IP change fast if you ever migrate the gateway.
3. **Issue the wildcard TLS cert** for `*.vm.petabyte.market` via DNS-01 (needs a DNS-provider API
   token for the ACME client).
4. **Set the app env:** `VM_DNS_ZONE=vm.petabyte.market`, `GATEWAY_TOKEN=<shared secret>`,
   `BASE_DOMAIN=petabyte.market`.
5. **Point the gateway at the API:** `PETABYTE_API_URL` + the same `GATEWAY_TOKEN` so
   `GET /vm/<id>/route` authorizes.
6. **(Buyers)** for the `root@<id>.vm.petabyte.market` UX, ship them the `~/.ssh/config` snippet from
   [§3B](#b-hostname-routing-the-rootidvmpetabytemarket-ux-you-asked-for). For the username form
   ([§3A](#a-username-routing-simplest-dns--the-built-in-default)) they need nothing.
7. **Verify:**
   ```bash
   dig +short q7bk2mrelpza.vm.petabyte.market      # -> your gateway IP (via the wildcard)
   ssh vm-q7bk2mrelpza@petabyte.market             # strategy A
   ssh root@q7bk2mrelpza.vm.petabyte.market        # strategy B (after the ~/.ssh/config snippet)
   ```

---

## 6. What's already built & tested (the code side)

You are plugging DNS + a gateway into seams that already work and are covered in CI:

| Piece | Where | Proven by |
|---|---|---|
| Stable opaque VM id (non-enumerable) | `db.VMRoute.id` (`_rand_vm_id`) | `vm_dns_test.py` |
| Address derived only from the id (`<user>@<id>.<zone>`, `https://<id>.<zone>`, fallback `vm-<id>@…`) | `main._vm_url` | `vm_dns_test.py` |
| Hostname carries **no login user** — `root@`/`app@`/`ubuntu@` all reach the same VM | `main._vm_url` | `vm_dns_test.py` |
| Buyer endpoint never leaks the node IP / placement | `GET /vm/{id}` | `vm_dns_test.py` |
| Gateway-only id→node resolution (token-gated) | `GET /vm/{id}/route` | `vm_dns_test.py` |
| Failover keeps the id (restore on a new node) | `db.failover_vm` / `reap_and_failover` | `vm_dns_test.py`, `tunnel_test.py` |
| Address byte-identical after failover | `main._vm_url` | `vm_dns_test.py` ("no new IP to handle") |
| Reverse tunnel over NAT (no inbound port on the node) | `lumaris_gateway/gateway.py` | `tunnel_test.py` (12/12) |

Run them:

```bash
cd lumaris_api  && python vm_dns_test.py      # stable-address / DNS-naming contract (fast, no sockets)
cd lumaris_gateway && python tunnel_test.py   # full NAT-traversal + failover network path
```

`tunnel_test.py` literally kills node A mid-session and shows the **same handle** reach node B, with
the connection string unchanged. `vm_dns_test.py` pins the naming contract this DNS setup relies on:
`root@<id>.vm.petabyte.market` is stable across failover and carries no node IP.

---

## 7. Honest status

- **Control plane + naming + failover:** implemented and green in CI (the tests above).
- **DNS + gateway on real machines:** this is the deploy step — a wildcard record, a gateway host,
  frp + sshpiper, a wildcard cert. Nothing here needs new application code; it's the operator setup
  described in [`vm-runbook.md`](vm-runbook.md) plus the DNS records in this doc. It has not yet been
  run against a real internet + a real home router end to end (same caveat `vm-runbook.md` states).
- **`<user>@<id>.vm.petabyte.market` specifically:** the API's **canonical** output (`url.ssh` /
  `url.hostname`), because it keeps the SSH username free for `root`/`app`/`ubuntu`/… on the same
  VM. The `vm-<id>@petabyte.market` username form is kept only as a labelled zero-config fallback
  (`url.ssh_username_fallback`) that logs into a single implicit user.
