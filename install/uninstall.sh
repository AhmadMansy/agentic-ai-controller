#!/usr/bin/env bash
# claude-controller uninstaller — reverses install.sh without touching
# any other hook or setting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="$REPO_DIR/install"

HTTP_PORT=8787
TARGET_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

usage() {
    cat <<EOF
claude-controller uninstaller

Usage: $(basename "$0") [options]

Options:
  --port PORT     HTTP port used at install time (default: 8787)
  --target PATH   Path to Claude Code settings.json
                  (default: \$CLAUDE_SETTINGS or ~/.claude/settings.json)
  --help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --port)   HTTP_PORT="$2"; shift 2 ;;
        --target) TARGET_SETTINGS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

OS="$(uname -s)"

echo "==> Removing LED hooks from $TARGET_SETTINGS"
if [ -f "$TARGET_SETTINGS" ]; then
    python3 "$INSTALL_DIR/hooks_merge.py" \
        --target "$TARGET_SETTINGS" --port "$HTTP_PORT" --uninstall
else
    echo "    (no settings file — nothing to do)"
fi

if [ "$OS" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.claudecontroller.bridge.plist"
    if [ -f "$PLIST" ]; then
        echo "==> Unloading launchd service"
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
    fi
elif [ "$OS" = "Linux" ]; then
    UNIT="$HOME/.config/systemd/user/claude-controller.service"
    if [ -f "$UNIT" ]; then
        echo "==> Stopping systemd user service"
        systemctl --user disable --now claude-controller.service 2>/dev/null || true
        rm -f "$UNIT"
        systemctl --user daemon-reload
    fi
fi

cat <<EOF

Done. What this uninstall did NOT do (on purpose):
  * Python packages (pyserial, pynput) — still installed in your environment
  * Your sound hooks and other settings — untouched
  * The Arduino sketch — still on the board

If you want to fully unwind, run:
  python3 -m pip uninstall pyserial pynput
EOF
