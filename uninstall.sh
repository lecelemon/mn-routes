#!/bin/bash
# Stops and removes the LaunchAgent installed by install.sh.
# Leaves ~/.netbird-route-fix (config/state) and the sudoers rule in
# place; remove those yourself if you want a fully clean uninstall.

set -euo pipefail

PLIST_LABEL="com.netbirdroutefix.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Stopped and removed the LaunchAgent."
echo
echo "Still on disk (remove manually if you want a full clean uninstall):"
echo "  ~/.netbird-route-fix/          (config + learned state)"
echo "  /etc/sudoers.d/netbird-route-fix  (passwordless sudo rule for /sbin/route)"
