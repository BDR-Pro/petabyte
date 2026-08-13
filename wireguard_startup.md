# WireGuard startup — turn a VM into the Petabyte VPN server

Petabyte can put a buyer's traffic to their rented compute on a private, encrypted
**WireGuard** tunnel instead of the public gateway. This is opt-in: a buyer chooses "Private
network (VPN)" in the web app (or `--vpn` on the CLI), and the API hands them a **client**
config whose `[Peer]` is a WireGuard **server** you run. This doc sets up that server.

Nothing here touches money or the marketplace — it only stands up the VPN endpoint the API
points clients at.

## Who holds which key

* The **server** (this VM) keeps its **private** key at `/etc/wireguard/server_private.key`
  (root-only, never leaves the box).
* The API only ever needs the server's **public** key + endpoint (`WG_PUBLIC_KEY`,
  `WG_ENDPOINT`) — both safe to share — plus `WG_APPLY=true` so it can push buyer peers.
* Each **buyer** gets a freshly generated client keypair per download; the private half lives
  only in the config the buyer downloads, and the API discards it immediately.

## 1. Run the bootstrap on a fresh VM

Any small Linux VM with a public IP (or a forwarded UDP port) works — 1 vCPU / 512 MB is plenty.

```bash
# copy the script onto the VM, then:
sudo WG_ENDPOINT_HINT=vpn.yourdomain.com ./lumaris_api/deploy/wireguard-server.sh
```

The script is **idempotent** and does the whole server setup:

1. installs `wireguard-tools` + `iptables`,
2. generates the server keypair (once; `0600` root-only),
3. writes `/etc/wireguard/wg0.conf` with NAT + forwarding `PostUp/PostDown` rules,
4. enables `net.ipv4.ip_forward`,
5. opens UDP `51820`,
6. enables and starts `wg-quick@wg0` (survives reboot),
7. prints the exact env vars to give the API.

Tunables (env): `WG_INTERFACE` (default `wg0`), `WG_PORT` (`51820`), `WG_SUBNET`
(`10.0.0.0/24`), `WG_SERVER_ADDR` (`10.0.0.1/24`), `WAN_IF` (auto-detected).

## 2. Wire the API to this server

Paste the values the script printed into the API environment (GitHub env / `.env` / compose):

```dotenv
WG_PUBLIC_KEY=<server_public.key from the script>
WG_ENDPOINT=<this VM's public IP or hostname>
WG_INTERFACE=wg0
WG_APPLY=true
```

`WG_APPLY=true` lets the API register each buyer's public key on the live interface with
`wg set wg0 peer <pubkey> allowed-ips <ip>/32` when they download a config. With
`WG_APPLY=false` (the default) the API still issues valid client configs but does not modify
the interface — useful for staging, or when a separate privileged helper applies peers.

> Run the API on this same VM, or give the API host permission to run `wg set` against the
> interface (e.g. a small root helper). The API never needs the server private key.

## 3. What a buyer gets

When a buyer opts into VPN, the API returns a ready-to-use client config:

```ini
[Interface]
PrivateKey = <buyer's per-session private key>
Address = 10.0.0.7/32
DNS = 1.1.1.1

[Peer]
PublicKey = <WG_PUBLIC_KEY>
Endpoint = <WG_ENDPOINT>:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

The buyer saves it and runs `wg-quick up ./petabyte.conf` (or imports it into the WireGuard
app). Their machine now reaches the rented GPU / cluster over the private `10.0.0.0/24`
network. Endpoints:

* VM / hourly rental: `GET /vpn_config/{booking_id}` (set `vpn:true` on `/request_vm`).
* Distributed cluster: `GET /jobs/{job_id}/vpn_config` (set `vpn:true` on `/distributed`).

## 4. On the seller node (the agent)

Cluster ranks talk to each other over WireGuard too. The agent brings up its own interface
for a VPN-enabled job (`lumaris_agent/wireguard.py`), gated on `AGENT_VPN_ENABLED=true` and
`wg` being present — it no-ops safely otherwise. See that module and the CLI's `--vpn` flag.

## 5. Verify

```bash
sudo wg show                     # server: interface up, peers appear as buyers connect
ping 10.0.0.1                    # from a connected buyer: reach the server
```

## Security notes

* The server private key is `0600` root-only and never printed or sent to the API.
* Buyer peers are `/32` — each buyer can only use its own allocated address.
* Rotate by deleting `/etc/wireguard/server_*.key` and re-running the script (issues a new
  `WG_PUBLIC_KEY`; update the API env and existing clients re-download).
