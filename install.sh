#!/bin/bash
# Builds MN Route as a real .app bundle (proper name/icon instead of a
# generic Python process), installs it to ~/Applications, and optionally
# sets it up to start automatically at login via a LaunchAgent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="MN Route"
PLIST_LABEL="com.mnroute.app"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
INSTALL_DIR="$HOME/Applications"
APP_PATH="$INSTALL_DIR/${APP_NAME}.app"
PYTHON_BIN="$(command -v python3)"

if [ -z "$PYTHON_BIN" ]; then
    echo "python3 not found. Install Python 3 first (e.g. via Xcode Command Line Tools or Homebrew)." >&2
    exit 1
fi

echo "Installing Python dependencies for $PYTHON_BIN..."
"$PYTHON_BIN" -m pip install --user -r "$SCRIPT_DIR/requirements.txt"

echo
echo "Building ${APP_NAME}.app..."
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"
BUILD_LOG="$(mktemp)"
if ! (cd "$SCRIPT_DIR" && "$PYTHON_BIN" setup.py py2app) > "$BUILD_LOG" 2>&1; then
    echo "Build failed. Full log:" >&2
    cat "$BUILD_LOG" >&2
    rm -f "$BUILD_LOG"
    exit 1
fi
rm -f "$BUILD_LOG"

mkdir -p "$INSTALL_DIR"
rm -rf "$APP_PATH"
cp -R "$SCRIPT_DIR/dist/${APP_NAME}.app" "$APP_PATH"
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"
echo "Installed to $APP_PATH"

echo
read -r -p "Start automatically at login via a LaunchAgent? [Y/n] " REPLY
case "$REPLY" in
    [Nn]*)
        echo "Skipping autostart. Launch it manually any time with:"
        echo "  open \"$APP_PATH\""
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
        <string>${APP_PATH}/Contents/MacOS/${APP_NAME}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/mn-route.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/mn-route.err.log</string>
</dict>
</plist>
PLIST
        launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
        # A freshly-copied .app can briefly fail bootstrap while macOS
        # settles its first-launch checks; retry a few times.
        for attempt in 1 2 3; do
            if launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null; then
                break
            fi
            if [ "$attempt" = 3 ]; then
                echo "launchctl bootstrap failed after 3 attempts — try running this line manually:" >&2
                echo "  launchctl bootstrap gui/\$(id -u) \"$PLIST_PATH\"" >&2
                exit 1
            fi
            sleep 2
        done
        echo "Installed and started — it will now launch automatically at every login."
        echo "Manage it later with:"
        echo "  launchctl bootout gui/\$(id -u)/${PLIST_LABEL}"
        echo "  launchctl bootstrap gui/\$(id -u) ${PLIST_PATH}"
        ;;
esac

echo
echo "Done. The first launch shows a one-time macOS admin-password prompt to allow route switching."
echo "Edit ~/.netbird-route-fix/config.json (created on first run) to add your own subnet(s)."
