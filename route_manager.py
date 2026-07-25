"""
Core logic for detecting whether a given subnet is directly reachable
(inter-VLAN, on-site) versus only reachable through a VPN tunnel, and
for switching the macOS routing table between the two. Supports any
number of independently-configured subnets ("routes").

Nothing here needs elevated privileges except the `route add`/`route
delete` calls in apply_direct_route()/apply_vpn_route(), which run
through `sudo -n` (non-interactive). A single blanket NOPASSWD rule for
`/sbin/route` covers all of them; ensure_sudo_configured() installs it
automatically (via a native macOS admin-password prompt) the first
time it's missing.
"""

import getpass
import ipaddress
import json
import re
import shlex
import socket
import subprocess
import tempfile
from pathlib import Path

APP_DIR = Path.home() / ".mn-routes"
_LEGACY_APP_DIR = Path.home() / ".netbird-route-fix"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
SUDOERS_FILE = Path("/etc/sudoers.d/mn-routes")
_LEGACY_SUDOERS_FILE = Path("/etc/sudoers.d/netbird-route-fix")

DEFAULT_CONFIG = {
    "poll_interval_seconds": 10,
    "probe_timeout_seconds": 1,
    "routes": [
        {
            "name": "Office VLAN",
            "subnet": "10.0.10.0/24",
            "probe_ip": "10.0.10.254",
            "tcp_probes": [],  # e.g. ["10.0.10.254:22"] as an ICMP fallback
        },
    ],
}

# Interfaces that are never "physical LAN" interfaces we should probe from.
IFACE_EXCLUDE_PREFIXES = (
    "lo", "utun", "wt", "awdl", "llw", "bridge", "ap",
    "gif", "stf", "p2p", "anpi",
)


def _migrate_legacy_app_dir():
    """Config/state used to live under ~/.netbird-route-fix; move it to
    the current location in place, once, if found."""
    if APP_DIR.exists() or not _LEGACY_APP_DIR.exists():
        return
    _LEGACY_APP_DIR.rename(APP_DIR)


def _migrate_legacy_config(on_disk):
    """Older configs had one top-level subnet/probe_ip instead of a
    routes list; fold them into a single-entry routes list in place."""
    if "routes" in on_disk:
        return on_disk
    if "subnet" in on_disk:
        on_disk["routes"] = [{
            "name": on_disk.get("subnet", "route"),
            "subnet": on_disk.pop("subnet"),
            "probe_ip": on_disk.pop("probe_ip", "10.0.10.254"),
            "tcp_probes": on_disk.pop("tcp_probes", []),
        }]
    return on_disk


def load_config():
    _migrate_legacy_app_dir()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return json.loads(json.dumps(DEFAULT_CONFIG))

    raw = json.loads(CONFIG_PATH.read_text())
    was_legacy = "routes" not in raw
    on_disk = _migrate_legacy_config(raw)
    if was_legacy:
        CONFIG_PATH.write_text(json.dumps(on_disk, indent=2))

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg.update(on_disk)
    return cfg


def load_state():
    _migrate_legacy_app_dir()
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


VALID_MODES = ("auto", "direct", "vpn")


def get_route_state(state, subnet):
    """Per-subnet state (mode, learned VPN tunnel interface), migrating
    older on-disk shapes in place if found. state.json is user-editable,
    so a missing/invalid mode (typo, hand edit, old format) is reset to
    "auto" rather than left to crash callers that trust it's always one
    of VALID_MODES."""
    routes = state.setdefault("routes", {})
    if subnet not in routes and ("mode" in state or "netbird_iface" in state or "vpn_iface" in state):
        routes[subnet] = {
            "mode": state.pop("mode", "auto"),
            "vpn_iface": state.pop("vpn_iface", None) or state.pop("netbird_iface", None),
        }
    route = routes.setdefault(subnet, {"mode": "auto", "vpn_iface": None})
    if "vpn_iface" not in route:
        route["vpn_iface"] = route.pop("netbird_iface", None)
    if route.get("mode") not in VALID_MODES:
        route["mode"] = "auto"
    return route


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class _Fail:
            returncode = -1
            stdout = ""
            stderr = str(e)
        return _Fail()


def list_physical_interfaces():
    """Return interface names that are up, have an IPv4 address, and
    aren't loopback/tunnel/virtual interfaces."""
    result = _run(["/sbin/ifconfig"])
    if result.returncode != 0:
        return []

    ifaces = []
    current = None
    has_inet = False
    is_active = False
    for line in result.stdout.splitlines():
        if line and not line[0].isspace():
            if current and has_inet and is_active:
                ifaces.append(current)
            current = line.split(":")[0]
            has_inet = False
            is_active = "UP" in line and "RUNNING" in line
        elif "inet " in line:
            has_inet = True
    if current and has_inet and is_active:
        ifaces.append(current)

    return [i for i in ifaces if not i.startswith(IFACE_EXCLUDE_PREFIXES)]


def _ping_bound(iface, target, timeout):
    result = _run(["/sbin/ping", "-c", "1", "-t", str(timeout), "-b", iface, target],
                  timeout=timeout + 2)
    if "invalid option" in (result.stderr or "").lower():
        return None  # -b unsupported on this ping build; caller should fall back
    return result.returncode == 0


def _tcp_bound_probe(iface, host, port, timeout):
    IP_BOUND_IF = 25  # macOS-specific IPPROTO_IP sockopt: force egress interface
    try:
        idx = socket.if_nametoindex(iface)
    except OSError:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, idx)
        sock.settimeout(timeout)
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def is_directly_reachable(probe_ip, timeout, tcp_probes=()):
    """Probe every physical interface for direct (non-VPN) reachability of
    a route's probe_ip, bypassing the current routing table by binding the
    probe to each interface. Returns (reachable: bool, iface: str|None)."""
    tcp_probes = [p.rsplit(":", 1) for p in tcp_probes]

    for iface in list_physical_interfaces():
        ok = _ping_bound(iface, probe_ip, timeout)
        if ok:
            return True, iface
        for host, port in tcp_probes:
            if _tcp_bound_probe(iface, host, int(port), timeout):
                return True, iface
    return False, None


_ROUTE_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")


def get_current_route(subnet):
    """Parse `netstat -rn` for the route currently active for `subnet`.
    Returns dict(destination, gateway, flags, netif) or None."""
    net = ipaddress.ip_network(subnet, strict=False)
    base = str(net.network_address)
    short = base.rsplit(".0", 1)[0] if base.endswith(".0") else base  # netstat abbreviates trailing .0

    result = _run(["/usr/sbin/netstat", "-rn", "-f", "inet"])
    for line in result.stdout.splitlines():
        m = _ROUTE_LINE_RE.match(line)
        if not m:
            continue
        dest = m.group(1)
        if dest in (base, short) or dest.startswith(base + "/") or dest.startswith(short + "/"):
            return {"destination": dest, "gateway": m.group(2), "flags": m.group(3), "netif": m.group(4)}
    return None


def get_gateway_for_iface(iface):
    result = _run(["/usr/sbin/ipconfig", "getoption", iface, "router"])
    gw = result.stdout.strip()
    return gw or None


def apply_direct_route(subnet, iface):
    """Point `subnet` at the given physical interface's own gateway,
    overriding whatever the VPN currently has installed."""
    gw = get_gateway_for_iface(iface)
    if not gw:
        raise RuntimeError(f"No DHCP-provided gateway found for {iface}")
    _run(["sudo", "-n", "/sbin/route", "-n", "delete", "-net", subnet])
    result = _run(["sudo", "-n", "/sbin/route", "-n", "add", "-net", subnet, gw])
    if result.returncode != 0:
        raise RuntimeError(f"route add failed: {result.stderr.strip()}")
    return gw


def apply_vpn_route(subnet, vpn_iface):
    """Restore `subnet` to route through the VPN's tunnel interface."""
    _run(["sudo", "-n", "/sbin/route", "-n", "delete", "-net", subnet])
    result = _run(["sudo", "-n", "/sbin/route", "-n", "add", "-net", subnet, "-interface", vpn_iface])
    if result.returncode != 0:
        raise RuntimeError(f"route add failed: {result.stderr.strip()}")


def sudo_is_configured():
    """Sanity-check that passwordless sudo works for /sbin/route at all,
    using a harmless read-only invocation."""
    result = _run(["sudo", "-n", "/sbin/route", "-n", "get", "default"])
    return result.returncode == 0


def install_blanket_sudoers_rule():
    """Install one NOPASSWD rule covering every `/sbin/route` invocation,
    via a native macOS admin-password prompt (Touch ID/password, not a
    terminal prompt). Returns (ok: bool, message: str)."""
    user = getpass.getuser()
    content = (
        "# Managed by mn-routes — do not edit by hand.\n"
        "# Regenerate via the app's automatic setup, or setup_sudoers.sh.\n"
        f"{user} ALL=(root) NOPASSWD: /sbin/route\n"
    )

    fd, tmp_path = tempfile.mkstemp(prefix="mn-routes-")
    try:
        with open(fd, "w") as f:
            f.write(content)

        shell_cmd = (
            f"/usr/sbin/visudo -cf {shlex.quote(tmp_path)} && "
            f"/usr/bin/install -m 0440 -o root -g wheel {shlex.quote(tmp_path)} {shlex.quote(str(SUDOERS_FILE))} && "
            f"rm -f {shlex.quote(str(_LEGACY_SUDOERS_FILE))}"
        )
        as_escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
        prompt = (
            "MN-routes needs one-time permission to switch macOS "
            "routes automatically, without asking for your password every time."
        )
        script = f'do shell script "{as_escaped}" with prompt "{prompt}" with administrator privileges'

        result = _run(["osascript", "-e", script], timeout=180)
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or "cancelled").strip()
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass


def ensure_sudo_configured():
    """Check passwordless sudo for /sbin/route; if missing, prompt once
    (GUI) to install it. Returns (ok: bool, message: str) — message is
    empty when ok."""
    if sudo_is_configured():
        return True, ""

    ok, err = install_blanket_sudoers_rule()
    if not ok:
        return False, f"sudo setup was cancelled or failed: {err}"
    if sudo_is_configured():
        return True, ""
    return False, "sudo still isn't working after the install attempt"
