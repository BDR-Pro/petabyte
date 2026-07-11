# vm-runbook.md — prove the reachable-VM loop on real machines

This is the physical test the software can't do (see RLtest.md §24-25). Follow it
with **two cheap cloud VMs** and your laptop to prove: a container on a node
**behind NAT** is reachable through a **stable Petabyte address**, and survives
the node dying (**same address, new node**).

The control plane is already built and tested (`VMRoute`, `/launch`,
`/vm/register_tunnel`, `/vm/{id}/route`, `reap_and_failover`). This runbook plugs
**frp** (tunnel) + **sshpiper** (username routing) into those seams.

Do it in two phases. **Phase A proves NAT traversal fast** (port-based). **Phase B
adds the pretty stable address** (`ssh vm-<handle>@petabyte.market`). Don't skip to
B — if A is flaky, everything else is moot.

---

## 0. Hosts

| Role | What | Notes |
|---|---|---|
| **API** | your existing droplet | runs Lumaris API + Postgres. Set `GATEWAY_TOKEN` + `BASE_DOMAIN=petabyte.market`. |
| **Gateway** | a small public VM (`gateway.petabyte.market`) | runs `frps` + (Phase B) `sshpiperd`. Public IP, ports 7000/2222/80/443 open. |
| **Node** | a VM with Docker (simulate NAT: **only allow outbound**, block all inbound except SSH-for-you) | runs the container + `frpc` + the seller agent. This is the "home gaming PC behind a router." |
| **Buyer** | your laptop | runs `ssh` / a browser. |

DNS: `gateway.petabyte.market` → gateway IP. For Phase B web apps, a **wildcard**
`*.petabyte.market` → gateway IP.

---

## 1. Install frp (both gateway and node)

```bash
FRP=0.58.1
curl -fsSL -o frp.tgz https://github.com/fatedier/frp/releases/download/v${FRP}/frp_${FRP}_linux_amd64.tar.gz
tar xzf frp.tgz && sudo mv frp_${FRP}_linux_amd64/frps /usr/local/bin/   # gateway
# on the node instead: sudo mv frp_${FRP}_linux_amd64/frpc /usr/local/bin/
```

Pick a shared secret both sides use: `FRP_TOKEN=$(openssl rand -hex 16)`.

---

## 2. Gateway — frps

`/etc/frp/frps.toml`:
```toml
bindPort = 7000                 # frpc dials in here (outbound from the node)
auth.token = "FRP_TOKEN_HERE"

# Phase B only — HTTP subdomain routing for web templates:
vhostHTTPPort = 8080
subDomainHost = "petabyte.market"

# lock down which remote ports frps will hand out (Phase A)
allowPorts = [ { start = 20000, end = 21000 } ]
```

systemd `/etc/systemd/system/frps.service`:
```ini
[Unit]
Description=frp server
After=network.target
[Service]
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
Restart=always
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now frps`. Open firewall: 7000 (frpc), 20000-21000
(Phase A tunnels), 8080 (Phase B http), 2222 (Phase B ssh router).

---

## 3. Node — container + frpc + register

### 3a. Start the workload container (what `/launch` does today via the agent)
```bash
# buyer's SSH key is injected so they can log in; map container SSH to a host port
docker run -d --name vm-$HANDLE \
  --gpus all --runtime=runsc \                         # gVisor if installed (see isolation-roadmap)
  -p 127.0.0.1:2222:22 \                               # container SSH -> host:2222 (loopback only)
  -p 127.0.0.1:8188:8188 \                             # app port (e.g. ComfyUI)
  -e AUTHORIZED_KEYS="$BUYER_PUBKEY" \
  <template-image>
```

### 3b. frpc dials OUT to the gateway (this is what beats NAT)
`/etc/frp/frpc.toml`:
```toml
serverAddr = "gateway.petabyte.market"
serverPort = 7000
auth.token = "FRP_TOKEN_HERE"

[[proxies]]
name = "HANDLE-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 2222            # the container's SSH on the host
remotePort = 0             # 0 = frps assigns one from allowPorts; read it back

# Phase B — expose the app on https://HANDLE.petabyte.market
[[proxies]]
name = "HANDLE-http"
type = "http"
localPort = 8188
subdomain = "HANDLE"
```
Start it, then **read the assigned SSH port** frps handed out (frpc logs it, e.g.
`start proxy success ... remote_port=20017`).

### 3c. Report the tunnel to the API (the seam we built)
```bash
curl -sX POST https://petabyte.market/vm/register_tunnel \
  -H "X-API-KEY: $PETABYTE_API_KEY" -H "Content-Type: application/json" \
  -d '{"vm_id":"HANDLE","tunnel_port":20017,"ip_address":"GATEWAY_IP"}'
# -> VMRoute.status becomes "running"; buyer's launch panel flips to "Ready"
```

In production the **agent does 3a-3c automatically** on a `/launch` dispatch. For
the runbook you can do it by hand to prove the path.

---

## 4. Phase A test — prove NAT traversal (port-based)

From your **laptop** (buyer):
```bash
ssh -p 20017 root@gateway.petabyte.market       # lands INSIDE the container on the NAT'd node
```
**Pass:** you get a shell in the container, even though the node has **no inbound
ports open**. That's the whole ballgame — traffic went node→gateway (outbound
tunnel), and the buyer→gateway→down-the-tunnel. Try the app too:
`curl http://gateway.petabyte.market:20017` if it were http, or use Phase B.

If this fails: check frpc connected (`journalctl -u frpc`), the token matches, and
`allowPorts` covers the assigned port.

---

## 5. Phase B — the stable address `ssh vm-<handle>@petabyte.market`

Phase A uses a raw port. To get the **username-routed stable address**, add
**sshpiper** on the gateway — it routes SSH by username to an upstream.

Install `sshpiperd` (github.com/tg123/sshpiper). Run it on gateway :2222 with a
small **exec/API plugin** that resolves the upstream from our API:

Resolver (`/etc/sshpiper/resolve.sh`) — given username `vm-HANDLE`, ask the API
where that VM currently lives:
```bash
#!/usr/bin/env bash
handle="${SSHPIPERD_UPSTREAM_USERNAME#vm-}"                     # strip vm- prefix
route=$(curl -s https://petabyte.market/vm/$handle/route \
        -H "X-Gateway-Token: $GATEWAY_TOKEN")
port=$(echo "$route" | jq -r .tunnel_port)
echo "127.0.0.1:$port"                                          # frps exposes the tunnel on loopback
```
So `ssh vm-HANDLE@gateway.petabyte.market` → sshpiper reads `vm-HANDLE` → calls
`GET /vm/HANDLE/route` (the endpoint we built, gateway-token-gated) → gets the
current `tunnel_port` → proxies to that frps-exposed port → into the container.

Point `vm-*.petabyte.market` / `gateway.petabyte.market:22` at sshpiperd. Then:
```bash
ssh vm-uxz8rmwonxv5@petabyte.market      # the exact handle /launch returned
```
**Pass:** same shell as Phase A, but via the **stable, opaque handle** — no port,
no raw node IP.

Web apps (Phase B): the frp `http` proxy + wildcard DNS gives
`https://uxz8rmwonxv5.petabyte.market` → the container's app port. Put
Caddy/nginx in front of frps `vhostHTTPPort` for TLS (wildcard cert via
`certbot -d '*.petabyte.market'`).

---

## 6. Failover test — same address, new node (the payoff)

1. Bring up a **second node** (Node B) the same way, online + attested.
2. Launch a VM (lands on the cheaper node, say Node A); connect via its handle.
3. **Kill Node A** (stop frpc + the box) so its heartbeat goes stale.
4. Within the reaper window, `reap_and_failover` re-points `VMRoute.current_spec_id`
   to Node B (**already tested in software**). Node B's agent restores the latest
   **S3 snapshot** (real once `S3_STUB` is off) and starts the container, then calls
   `/vm/register_tunnel` with its new tunnel port.
5. Re-run `ssh vm-<handle>@petabyte.market`.

**Pass:** the **same handle** now lands you on **Node B**, with state as of the last
snapshot. `VMRoute.migrations` incremented; the address never changed. This is the
`Buyer1/VM1 → new IP, same URL` guarantee, proven physically.

**Honest caveat:** crash-consistent, not zero-loss — the session restarts from the
last checkpoint. Tell users so.

---

## 7. Security hardening (do before real buyers)

- **frp token** secret + rotate; consider mTLS (`transport.tls.enable`).
- The gateway only proxies; it should hold **no buyer data**. Terminate TLS, forward.
- Container hardening from `isolation-roadmap.md` (gVisor `--runtime=runsc`,
  `--cap-drop=ALL`, seccomp, `--pids-limit`, no `--privileged`, no docker socket).
- Inject the buyer's SSH key **per VM**; never a shared key. Tear it down on stop.
- `GATEWAY_TOKEN` is the only thing letting the gateway resolve routes — keep it on
  the gateway host only, rotate on suspicion.
- Rate-limit sshpiper auth; fail2ban on the gateway.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| frpc won't connect | token mismatch, 7000 blocked, wrong `serverAddr`. |
| ssh port refused | assigned `remote_port` outside `allowPorts`, or container SSH not on 127.0.0.1:2222. |
| `vm-<handle>` ssh fails but `-p <port>` works | sshpiper resolver — check `GATEWAY_TOKEN`, `jq`, that `/vm/<handle>/route` returns a `tunnel_port`. |
| route 404 | VM `stopped`/`failed`, or handle typo. |
| https subdomain 404 | wildcard DNS missing, or `subDomainHost`/`subdomain` mismatch, or no TLS in front. |
| after failover, old address dead | Node B never called `/vm/register_tunnel` (status stuck `migrating`). |

---

## 9. How this maps to the code (already in the zip)

| Runbook step | Built endpoint / function |
|---|---|
| node reports its tunnel | `POST /vm/register_tunnel` → `register_vm_tunnel` |
| gateway resolves a handle | `GET /vm/{id}/route` (X-Gateway-Token) |
| buyer sees their VM + URL | `GET /vm`, `GET /vm/{id}`; `/launch` returns `url` |
| stop | `POST /vm/{id}/stop` |
| failover re-point | `reap_and_failover` → `failover_vm` (in the reaper) |
| snapshot up/down | `mint_presigned_put/get` (real once `S3_STUB` off) |

**Once Phase A passes, you have proven the core product.** Everything else —
metering, extend, a nicer UI — is polish on a loop that now physically closes.
