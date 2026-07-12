# vm-runbook.md — make a NAT'd GPU reachable at a stable address

## Status: the loop is PROVEN in software, not yet on real machines

`lumaris_gateway/tunnel_test.py` runs the whole thing end to end and passes **12/12**,
stable across repeated runs:

```
PASS both nodes established OUTBOUND control channels (NAT traversed)
PASS VM landed on the cheaper node (A)
PASS node registered its tunnel with the API
PASS buyer reached the workload through the tunnel using only the handle
PASS workload is bound to loopback only (no public listener on the node)
PASS reaper migrated the VM off the dead node
PASS VM now points at node B
PASS node B registered the tunnel for the same VM
PASS SAME handle now reaches node B (address never changed)
PASS the buyer's connection string is unchanged after failover
PASS event timeline shows created -> migrated (failover is visible)
```

A buyer knowing **only** the handle `d4fb48y4fazw` reached a workload bound to `127.0.0.1`
on a node with **no inbound ports**, then the node was killed and **the same handle**
reached a different machine. Run it yourself:

```bash
cd lumaris_gateway && python tunnel_test.py
```

**Still unproven:** the same thing across a real internet, a real home router, and real
SSH. That is what this runbook is for. The control plane is done — you are plugging
production plumbing into seams that already work.

---

## The idea in one paragraph

A seller's GPU sits behind a home router: no public IP, no open ports, and you cannot ask
a gamer to set up port forwarding. So the node **dials out** to your gateway and holds the
connection open — outbound connections cross NAT freely. When a buyer arrives, the gateway
sends "open a channel" **down that existing connection**; the node dials out again; the
gateway splices the two. Bytes flow. No inbound port is ever opened on the node. On
failover the gateway resolves the same handle to a different node — the buyer's address
never changes.

In production **frp** does the tunnelling and **sshpiper** does the username routing.
`lumaris_gateway/gateway.py` is that same design in ~200 readable lines: use it to
understand the shape and to keep the control plane honest in CI, not to serve traffic.

---

## 0. Hosts

| Role | What | Notes |
|---|---|---|
| **API** | your existing droplet | set `GATEWAY_TOKEN`, `BASE_DOMAIN=petabyte.market` |
| **Gateway** | a small public VM | runs `frps` + `sshpiperd`; open 7000 / 22 / 80 / 443 |
| **Node** | box with Docker + GPU | **simulate NAT: block ALL inbound except your admin SSH.** If it works with inbound blocked, it works behind a router |
| **Buyer** | your laptop | runs `ssh` |

DNS: `gateway.petabyte.market` -> gateway IP. For web templates, wildcard
`*.petabyte.market` -> gateway IP.

---

## 1. Install frp (gateway + node)

```bash
FRP=0.58.1
curl -fsSL -o frp.tgz https://github.com/fatedier/frp/releases/download/v${FRP}/frp_${FRP}_linux_amd64.tar.gz
tar xzf frp.tgz
sudo mv frp_${FRP}_linux_amd64/frps /usr/local/bin/     # gateway
sudo mv frp_${FRP}_linux_amd64/frpc /usr/local/bin/     # node
FRP_TOKEN=$(openssl rand -hex 16)     # same secret both sides
```

## 2. Gateway - frps

`/etc/frp/frps.toml`:
```toml
bindPort = 7000                    # nodes dial IN here (outbound from their side)
auth.token = "FRP_TOKEN_HERE"

vhostHTTPPort = 8080               # web templates -> https://<handle>.petabyte.market
subDomainHost = "petabyte.market"

allowPorts = [{ start = 20000, end = 21000 }]

transport.tls.force = true         # nodes must speak TLS to the gateway
```

`/etc/systemd/system/frps.service`:
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
```bash
sudo systemctl enable --now frps
```

## 3. Node - container + frpc + tell the API

### 3a. Start the workload (what the agent already does)
```bash
docker run -d --name vm-$HANDLE \
  --gpus all --runtime=runsc \                  # gVisor if installed
  --security-opt no-new-privileges --pids-limit 1024 \
  -p 127.0.0.1:2222:22 \                        # container SSH -> HOST LOOPBACK ONLY
  -p 127.0.0.1:8188:8188 \                      # app port, loopback only
  -e AUTHORIZED_KEYS="$BUYER_PUBKEY" \
  <template-image>
```
Binding to `127.0.0.1` is the point: nothing on the node is publicly reachable, and the
tunnel is the only way in. (`tunnel_test.py` asserts exactly this.)

### 3b. frpc dials OUT - this is what beats NAT
`/etc/frp/frpc.toml`:
```toml
serverAddr = "gateway.petabyte.market"
serverPort = 7000
auth.token = "FRP_TOKEN_HERE"
transport.tls.enable = true

[[proxies]]
name = "HANDLE-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 2222
remotePort = 0            # frps assigns from allowPorts; read it back from the log

[[proxies]]
name = "HANDLE-http"      # only for templates with a web UI
type = "http"
localPort = 8188
subdomain = "HANDLE"
```

### 3c. Report the tunnel to the control plane (seam already built + tested)
```bash
curl -sX POST https://petabyte.market/vm/register_tunnel \
  -H "X-API-KEY: $PETABYTE_API_KEY" -H "Content-Type: application/json" \
  -d '{"vm_id":"HANDLE","tunnel_port":20017,"ip_address":"GATEWAY_IP"}'
```
`VMRoute.status` -> `running`; the buyer's panel flips to Ready. In production the **agent
does 3a-3c automatically** on a `/launch` dispatch — do it by hand once to prove it.

---

## 4. Phase A - prove NAT traversal (the whole ballgame)

From your **laptop**:
```bash
ssh -p 20017 root@gateway.petabyte.market
```

**Pass:** a shell **inside the container**, on a node with **no inbound ports open**. If
this works, the product works. Everything else is presentation.

Fails? `journalctl -u frpc` on the node (token mismatch, 7000 blocked outbound), and check
the assigned port falls inside `allowPorts`.

---

## 5. Phase B - the stable address `ssh vm-<handle>@petabyte.market`

Phase A leaves a raw port. Now route by **username** so the address is stable and opaque.
Install **sshpiperd** (github.com/tg123/sshpiper) on the gateway, listening on :22.

Resolver `/etc/sshpiper/resolve.sh` — the gateway asks the API where the VM lives *right
now*. This is the failover hinge, and it is `GET /vm/{id}/route`, already built and gated
by `X-Gateway-Token`:
```bash
#!/usr/bin/env bash
handle="${SSHPIPERD_UPSTREAM_USERNAME#vm-}"     # ssh vm-d4fb48y4fazw@... -> d4fb48y4fazw
route=$(curl -fsS "https://petabyte.market/vm/${handle}/route" \
        -H "X-Gateway-Token: ${GATEWAY_TOKEN}") || exit 1
port=$(echo "$route" | jq -r .tunnel_port)
[ "$port" = "null" ] && exit 1
echo "127.0.0.1:${port}"     # frps exposes the node's tunnel on gateway loopback
```

Then:
```bash
ssh vm-d4fb48y4fazw@petabyte.market
```
**Pass:** the same shell as Phase A, via the stable opaque handle `/launch` gave the buyer
— no port, no node IP, nothing leaked.

Web templates: the frp `http` proxy + wildcard DNS gives `https://<handle>.petabyte.market`.
Terminate TLS with Caddy/nginx in front of frps' `vhostHTTPPort`; wildcard cert via
`certbot -d '*.petabyte.market'`.

---

## 6. Failover - the payoff (proven in software; now prove it physically)

1. Bring up **Node B**, attested and heartbeating.
2. Launch a VM (lands on cheaper Node A). Connect. Write a file.
3. **Kill Node A**: `systemctl stop frpc && poweroff`. Heartbeat goes stale.
4. Within the reaper window `reap_and_failover` re-points `VMRoute.current_spec_id` to
   Node B, **moves the booking with it**, and releases A's unit. Node B's agent restores
   the latest **S3 snapshot** and calls `/vm/register_tunnel` with its new port.
5. `ssh vm-<same-handle>@petabyte.market`

**Pass:** the **same address** lands you on **Node B**, with state as of the last snapshot.
`migrations` incremented; the buyer's connection string never changed.

**Say this honestly:** recovery is **crash-consistent from the last checkpoint**, not a
live mirror — a failover restarts the session from a snapshot. `/security` already says so.

---

## 7. Before real buyers

- Rotate `FRP_TOKEN`; keep `transport.tls.force = true`.
- `GATEWAY_TOKEN` lives **only** on the gateway — it is the key to route resolution.
- The gateway proxies and holds **no buyer data**: terminate TLS, forward, forget.
- Inject the buyer's SSH key **per VM**; never a shared key. Revoke on stop.
- `fail2ban` + auth rate limiting on the gateway's :22.
- Container hardening: `--runtime=runsc`, `--cap-drop=ALL`, `--pids-limit`, never
  `--privileged`, never mount the docker socket. See `docs/isolation-roadmap.md`.

---

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| frpc won't connect | token mismatch · 7000 blocked outbound · wrong `serverAddr` |
| ssh port refused | `remotePort` outside `allowPorts` · container not bound to `127.0.0.1:2222` |
| `-p <port>` works, `vm-<handle>` doesn't | sshpiper resolver: check `GATEWAY_TOKEN`, `jq`, and that `/vm/<handle>/route` returns a `tunnel_port` |
| route 404 | VM `stopped`/`failed`, or wrong handle |
| https subdomain 404 | wildcard DNS missing · `subDomainHost`/`subdomain` mismatch · no TLS terminator |
| after failover old address dead | Node B never called `/vm/register_tunnel` (stuck at `migrating`) |

---

## 9. What maps to what (all built and tested)

| Runbook step | Code |
|---|---|
| node reports its tunnel | `POST /vm/register_tunnel` -> `register_vm_tunnel` |
| gateway resolves a handle | `GET /vm/{id}/route` (X-Gateway-Token) |
| buyer sees VM + address | `GET /vm`, `GET /vm/{id}`; `/launch` returns `url` |
| stop (metered) | `POST /vm/{id}/stop` -> `stop_vm_metered` |
| failover re-point | `reap_and_failover` -> `failover_vm` |
| snapshot up/down | `mint_presigned_put/get` (real once `S3_STUB` is off) |
| the whole loop, in CI | `lumaris_gateway/tunnel_test.py` |
