"""
NetBird Route Fix — a macOS menu bar app that keeps traffic to one or
more configured subnets on the fastest available path.

Problem it solves: NetBird pushes a route for a subnet through its
tunnel even when you're on a network that already has direct
(inter-VLAN) routing to that same subnet. This app detects which
situation you're actually in, independently for each subnet listed in
~/.netbird-route-fix/config.json, and repoints the macOS routing table
to match — automatically, or on manual command from the menu bar.
"""

import rumps
import route_manager as rm

ICONS = {
    "direct": "🟢",
    "vpn": "🔒",
    "absent": "🚫",
    "unknown": "❓",
    "error": "⚠️",
}

STATUS_LABELS = {
    "direct": "direct",
    "vpn": "vpn",
    "absent": "no route installed",
    "unknown": "checking",
}

TITLE_LABELS = {
    "direct": "DIRECT",
    "vpn": "VPN",
    "absent": "NO ROUTE",
    "unknown": "…",
}

MODE_LABELS = {"auto": "Auto", "direct": "Manual: Direct", "vpn": "Manual: VPN"}


class RouteEntry:
    """Runtime state + menu items for one configured route."""

    def __init__(self, route_cfg, mode, app):
        self.cfg = route_cfg
        self.subnet = route_cfg["subnet"]
        self.mode = mode  # auto | direct | vpn
        self.current_path = "unknown"  # direct | vpn | absent | unknown
        self.last_error = None

        subnet = self.subnet
        self.status_item = rumps.MenuItem(f"{route_cfg['name']}: checking…")
        self.auto_item = rumps.MenuItem(
            "Auto (recommended)", callback=lambda s: app.set_mode(subnet, "auto"))
        self.direct_item = rumps.MenuItem(
            "Force Direct (bypass VPN)", callback=lambda s: app.set_mode(subnet, "direct"))
        self.vpn_item = rumps.MenuItem(
            "Force via NetBird VPN", callback=lambda s: app.set_mode(subnet, "vpn"))

    def sync_checkmarks(self):
        self.auto_item.state = self.mode == "auto"
        self.direct_item.state = self.mode == "direct"
        self.vpn_item.state = self.mode == "vpn"

    def menu_block(self):
        return [self.status_item, self.auto_item, self.direct_item, self.vpn_item]


class NetBirdRouteFixApp(rumps.App):
    def __init__(self):
        super().__init__("MN Route", title="❓ …")
        self.cfg = rm.load_config()
        self.state = rm.load_state()

        self.routes = {}
        for route_cfg in self.cfg["routes"]:
            subnet = route_cfg["subnet"]
            rstate = rm.get_route_state(self.state, subnet)
            self.routes[subnet] = RouteEntry(route_cfg, rstate.get("mode", "auto"), self)
        rm.save_state(self.state)  # persist any legacy-state migration immediately

        # Only prompts (native macOS password dialog) if not already configured.
        self.sudo_ok, self.sudo_message = rm.ensure_sudo_configured()

        self.refresh_item = rumps.MenuItem("Refresh Now", callback=self.refresh_now)
        self.setup_item = rumps.MenuItem("Check sudo Setup…", callback=self.check_setup)

        menu = []
        for entry in self.routes.values():
            menu.extend(entry.menu_block())
            menu.append(None)
        menu.append(self.refresh_item)
        menu.append(self.setup_item)
        self.menu = menu

        for entry in self.routes.values():
            entry.sync_checkmarks()

        self.timer = rumps.Timer(self.tick, self.cfg["poll_interval_seconds"])
        self.timer.start()
        self.tick(None)

    def _persist_modes(self):
        for subnet, entry in self.routes.items():
            rm.get_route_state(self.state, subnet)["mode"] = entry.mode
        rm.save_state(self.state)

    def set_mode(self, subnet, mode):
        entry = self.routes[subnet]
        entry.mode = mode
        entry.sync_checkmarks()
        self._persist_modes()
        self.tick(None)

    def refresh_now(self, _sender):
        self.tick(None)

    def check_setup(self, _sender):
        self.sudo_ok, self.sudo_message = rm.ensure_sudo_configured()
        if self.sudo_ok:
            rumps.alert("Setup OK", "Passwordless sudo for /sbin/route is working.")
        else:
            rumps.alert("Setup needed", f"Sudo still isn't configured: {self.sudo_message}")
        self._update_tooltip()

    def _set_icon_tooltip(self, text):
        try:
            self._nsapp.nsstatusitem.button().setToolTip_(text)
        except AttributeError:
            pass  # status item not created yet (very first tick, before run() finishes init)

    def _update_tooltip(self):
        if self.sudo_ok:
            self._set_icon_tooltip("")
        else:
            self._set_icon_tooltip(
                f"⚠️ Sudo not set up: {self.sudo_message}\nClick 'Check sudo Setup…' in the menu to retry."
            )

    def tick(self, _sender):
        for entry in self.routes.values():
            self._tick_route(entry)
        rm.save_state(self.state)

        # Cheap, non-prompting recheck so the tooltip stays accurate even if
        # the sudoers rule is removed/broken after the initial launch prompt.
        self.sudo_ok = rm.sudo_is_configured()
        if self.sudo_ok:
            self.sudo_message = ""
        elif not self.sudo_message:
            self.sudo_message = "passwordless sudo for /sbin/route isn't configured"

        self._render_title()
        self._update_tooltip()

    def _tick_route(self, entry):
        route_cfg = entry.cfg
        subnet = entry.subnet
        rstate = rm.get_route_state(self.state, subnet)
        reachable = None
        try:
            reachable, phys_iface = rm.is_directly_reachable(
                route_cfg["probe_ip"],
                self.cfg["probe_timeout_seconds"],
                route_cfg.get("tcp_probes", []),
            )
            route = rm.get_current_route(subnet)

            if route and route["netif"].startswith(("utun", "wt")):
                if not rstate.get("netbird_iface"):
                    rstate["netbird_iface"] = route["netif"]

            vpn_iface = rstate.get("netbird_iface")
            if route is None:
                entry.current_path = "absent"
            elif route["netif"].startswith(("utun", "wt")):
                entry.current_path = "vpn"
            else:
                entry.current_path = "direct"

            if entry.mode == "auto":
                desired = "direct" if reachable else "vpn"
                if desired != entry.current_path:
                    self._apply(entry, desired, phys_iface, vpn_iface)
            elif entry.mode == "direct" and entry.current_path != "direct":
                self._apply(entry, "direct", phys_iface, vpn_iface)
            elif entry.mode == "vpn" and entry.current_path != "vpn":
                self._apply(entry, "vpn", phys_iface, vpn_iface)

            entry.last_error = None
        except Exception as e:
            entry.last_error = str(e)

        self._render_route(entry, reachable=reachable)

    def _apply(self, entry, desired, phys_iface, vpn_iface):
        subnet = entry.subnet
        if desired == "direct":
            if not phys_iface:
                raise RuntimeError("no reachable physical interface to route through")
            rm.apply_direct_route(subnet, phys_iface)
            entry.current_path = "direct"
        else:
            if not vpn_iface:
                raise RuntimeError(
                    "NetBird tunnel interface unknown — connect while off-site once so it can be learned"
                )
            rm.apply_vpn_route(subnet, vpn_iface)
            entry.current_path = "vpn"

    def _render_route(self, entry, reachable=None):
        mode_label = MODE_LABELS[entry.mode]
        route_label = STATUS_LABELS.get(entry.current_path, entry.current_path)
        name = entry.cfg["name"]

        if entry.last_error:
            entry.status_item.title = (
                f"{ICONS['error']} {name}: error ({route_label}, {mode_label}) — {entry.last_error}"
            )
            return

        icon = ICONS.get(entry.current_path, ICONS["unknown"])
        reach_note = "" if reachable is None else f", probe {'ok' if reachable else 'no answer'}"
        entry.status_item.title = f"{icon} {name}: {route_label} ({mode_label}{reach_note})"

    def _render_title(self):
        icons = []
        any_error = False
        for entry in self.routes.values():
            icons.append(ICONS.get(entry.current_path, ICONS["unknown"]))
            any_error = any_error or bool(entry.last_error)
        any_error = any_error or not self.sudo_ok
        prefix = f"{ICONS['error']} " if any_error else ""
        self.title = prefix + " ".join(icons)


if __name__ == "__main__":
    NetBirdRouteFixApp().run()
