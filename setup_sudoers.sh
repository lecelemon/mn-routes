#!/bin/bash
# Manual/terminal fallback for the one-time sudo setup — the app now does
# this itself automatically via a native macOS password prompt the first
# time it launches without it configured. Use this script instead only if
# that GUI prompt can't run (e.g. no window server / SSH session).
#
# Installs one NOPASSWD rule covering every `/sbin/route` invocation, so
# the app can add/delete routes without prompting for a password each
# time it auto-switches. You'll be asked for your password once, here.

set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/netbird-route-fix"
CURRENT_USER="$(whoami)"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<EOF
# Managed by netbird-route-fix — do not edit by hand.
# Regenerate via the app's automatic setup, or this script.
${CURRENT_USER} ALL=(root) NOPASSWD: /sbin/route
EOF

echo "This will install the following sudoers rule (you'll be asked for your password once):"
echo "---"
cat "$TMP_FILE"
echo "---"

if ! sudo visudo -cf "$TMP_FILE"; then
    echo "Generated sudoers file failed validation — aborting, nothing installed." >&2
    exit 1
fi

sudo install -m 0440 -o root -g wheel "$TMP_FILE" "$SUDOERS_FILE"

echo "Installed $SUDOERS_FILE"
if sudo -n /sbin/route -n get default >/dev/null 2>&1; then
    echo "Passwordless sudo is working. You're done — start (or refresh) the app."
else
    echo "Something's off — passwordless sudo still isn't working. Check $SUDOERS_FILE." >&2
    exit 1
fi
