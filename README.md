# MN-routes

A macOS menu bar app that fixes a common NetBird routing conflict: NetBird
pushes a route for a subnet through its VPN tunnel, even on networks where
that same subnet is already directly reachable (e.g. via inter-VLAN
routing). This app detects which situation you're in and automatically
points the route at whichever path is actually faster — with a menu bar
icon and manual override if you'd rather control it yourself.

Supports any number of subnets, each switched independently.

## Requirements

- macOS with a Mac menu bar (uses `NSStatusItem` via [rumps](https://github.com/jaredks/rumps))
- Python 3
- A VPN client that installs its routes on a `utun` interface (standard
  for WireGuard-based clients)
- **Verified working on:** macOS 26.5.2, Apple M5 (MacBook Air), with
  [NetBird](https://netbird.io). Other Apple Silicon Macs and recent
  macOS versions are likely fine too, but untested. It should also work
  with any other VPN client built on WireGuard/`utun` interfaces (e.g.
  Tailscale, plain WireGuard) since the switching logic only looks at
  the OS routing table and interface names, not anything NetBird-specific
  — but that combination hasn't actually been tested.

## Install

```bash
git clone https://github.com/lecelemon/mn-routes.git
cd mn-routes
chmod +x install.sh
./install.sh
```

`install.sh` builds a real `MN-routes.app`, installs it to `~/Applications`,
and optionally sets up a LaunchAgent so it starts automatically at login.
Building it locally (via [py2app](https://py2app.readthedocs.io/)) is what
gives it a proper name/icon in Activity Monitor, alerts, and the menu bar,
instead of showing up as a generic Python process.

The first time it runs without passwordless `sudo` already configured for
`/sbin/route`, it shows a native macOS admin-password prompt (once) to set
that up — needed so the app can switch routes without asking for your
password every time.

## Configure

Edit `~/.netbird-route-fix/config.json` (created automatically on first
run — see [config.example.json](config.example.json) for the shape):

```json
{
  "poll_interval_seconds": 10,
  "probe_timeout_seconds": 1,
  "routes": [
    {
      "name": "Office VLAN",
      "subnet": "10.0.10.0/24",
      "probe_ip": "10.0.10.254",
      "tcp_probes": []
    }
  ]
}
```

- `name` — label shown in the menu.
- `subnet` — the network to manage, in CIDR form.
- `probe_ip` — a host in that subnet that reliably answers ICMP ping,
  typically the subnet's own router/gateway.
- `tcp_probes` — optional `"host:port"` fallbacks (e.g. `["10.0.10.254:22"]`)
  if ICMP is filtered on your network.

Add as many entries to `routes` as you have subnets to manage.

## Using it

Each configured subnet gets its own line in the menu bar dropdown:

- **Auto (recommended)** — switches automatically based on live reachability.
- **Force Direct** — always route via the local physical interface.
- **Force via NetBird VPN** — always route via the NetBird tunnel.

Menu bar icons: 🟢 direct · 🔒 VPN · 🚫 no route installed · ⚠️ error
(hover the icon for details).

## Uninstall

```bash
./uninstall.sh
```

## License

MIT — see [LICENSE](LICENSE).
