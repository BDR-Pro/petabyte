# dynamic_dns.md — a stable per-VM address that survives a node dying

**Question this answers:** *"Can I `ssh root@<id>.vm.petabyte.market`, so when a VM's machine goes
down a backup takes over WITHOUT me handling a new IP?"*

**Answer: yes — that's the whole design.** Each VM has a **stable, opaque id** (e.g.
`q7bk2mrelpza`). Every buyer-facing address is derived only from that id, never from the node's IP.
When the hosting machine dies, the platform restores the VM on another node **keeping the same id**,
so the address you were given is byte-identical. You never edit DNS per VM, and you never run a
dynamic-DNS updater. One static wildcard record covers every VM forever; the **control plane**, not
DNS, follows the VM.

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

## 3. SSH — the two routing strategies

SSH has no SNI/Host header, so a shared gateway can't read the target hostname from the SSH protocol
itself. There are two clean ways to tell the gateway which VM you want. Pick one; both survive
failover with **no DNS change**.

### A. Username routing (simplest DNS — the built-in default)

The VM id travels in the SSH **username**, so a single A record is enough and the gateway/sshpiper
reads the id from the login name.

```bash
ssh vm-<id>@petabyte.market      # e.g. ssh vm-q7bk2mrelpza@petabyte.market
```

- **DNS:** one `A` record for `petabyte.market` (or `gw.petabyte.market`) → gateway. No wildcard
  needed.
- **Gateway:** `sshpiperd` selects the upstream from the `vm-<id>` username, then calls
  `/vm/<id>/route` to find the current node. Config in [`vm-runbook.md`](vm-runbook.md).
- This is the string the API returns today as `url.ssh`.

### B. Hostname routing (the `root@<id>.vm.petabyte.market` UX you asked for)

Use the per-VM subdomain and log in as `root` (or any container user). Because raw SSH won't carry
the hostname, the buyer's SSH client passes the id to the gateway via a tiny `ProxyCommand`. Add this
**once** to the buyer's `~/.ssh/config`:

```ssh-config
Host *.vm.petabyte.market
    User root
    # Hand the full VM hostname (%h) to the gateway, which resolves it to the current node.
    ProxyCommand petabyte-connect %h %p
    # (petabyte-connect is a ~15-line helper: open a TCP conn to gw.petabyte.market and send the
    #  handle, exactly like lumaris_gateway/gateway.py:buyer_connect. Or use `ssh -J` / `nc` with a
    #  sshpiper host-routing plugin — see vm-runbook.md.)
```

Then the exact command works:

```bash
ssh root@<id>.vm.petabyte.market
```

- **DNS:** the wildcard `*.vm.petabyte.market` → gateway (from [§2](#2-the-dns-records-you-actually-add)).
- This is the string the API returns as `url.ssh_hostname` (with `VM_DNS_ZONE=vm.petabyte.market`).

> `root@` is about the **login user inside the container**, not routing. The buyer's public key is
> injected into the VM (the launch's `ssh_pubkey`), so `root@` authenticates by key. Routing (which
> machine) is handled by strategy A or B above, independently of the login user.

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
| Address derived only from the id (`vm-<id>@…`, `root@<id>.<zone>`, `https://<id>.<zone>`) | `main._vm_url` | `vm_dns_test.py` |
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
- **`root@<id>.vm.petabyte.market` specifically:** works via the wildcard + strategy B (hostname
  routing). The username form (`vm-<id>@petabyte.market`, strategy A) needs even less DNS and is the
  API's default output.
