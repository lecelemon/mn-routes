#!/bin/bash
# Installs dependencies and (optionally) sets up NetBird Route Fix to
# start automatically at login via a LaunchAgent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_LABEL="com.netbirdroutefix.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
PYTHON_BIN="$(command -v python3)"

if [ -z "$PYTHON_BIN" ]; then
    echo "python3 not found. Install Python 3 first (e.g. via Xcode Command Line Tools or Homebrew)." >&2
    exit 1
fi

echo "Installing Python dependencies for $PYTHON_BIN..."
"$PYTHON_BIN" -m pip install --user -r "$SCRIPT_DIR/requirements.txt"

echo
read -r -p "Start automatically at login via a LaunchAgent? [Y/n] " REPLY
case "$REPLY" in
    [Nn]*)
        echo "Skipping autostart. Run it manually any time with:"
        echo "  $PYTHON_BIN $SCRIPT_DIR/menubar_app.py"
        ;;
    *)
        mkdir -p "$HOME/Library/LaunchAgents"
        cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${SCRIPT_DIR}/menubar_app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/netbird-route-fix.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/netbird-route-fix.err.log</string>
</dict>
</plist>
PLIST
        launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
        echo "Installed and started — it will now launch automatically at every login."
        echo "Manage it later with:"
        echo "  launchctl bootout gui/\$(id -u)/${PLIST_LABEL}"
        echo "  launchctl bootstrap gui/\$(id -u) ${PLIST_PATH}"
        ;;
esac

echo
echo "Done. The first launch shows a one-time macOS admin-password prompt to allow route switching."
echo "Edit ~/.netbird-route-fix/config.json (created on first run) to add your own subnet(s)."
