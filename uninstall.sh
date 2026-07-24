#!/bin/bash
# Stops and removes the LaunchAgent and installed app created by install.sh.
# Leaves ~/.netbird-route-fix (config/state) and the sudoers rule in
# place; remove those yourself if you want a fully clean uninstall.

set -euo pipefail

APP_NAME="MN-routes"
PLIST_LABEL="com.mnroutes.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
APP_PATH="$HOME/Applications/${APP_NAME}.app"

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
rm -f "$PLIST_PATH"
rm -rf "$APP_PATH"

echo "Stopped and removed the LaunchAgent and ${APP_NAME}.app."
echo
echo "Still on disk (remove manually if you want a full clean uninstall):"
echo "  ~/.netbird-route-fix/          (config + learned state)"
echo "  /etc/sudoers.d/netbird-route-fix  (passwordless sudo rule for /sbin/route)"
