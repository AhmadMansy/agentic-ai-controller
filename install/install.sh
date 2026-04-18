#!/usr/bin/env bash
# agentic-ai-controller installer
#
# Does three things, safely and idempotently:
#   1. Installs Python dependencies from bridge/requirements.txt
#   2. Merges LED hooks into ~/.claude/settings.json (backs up first)
#   3. Optionally installs a launchd (macOS) or systemd-user (Linux) service
#      so the bridge auto-starts at login.
#
# Usage:
#     ./install.sh                  # interactive
#     ./install.sh --no-service     # skip auto-start service
#     ./install.sh --port 8787      # override bridge HTTP port
#     ./install.sh --help

set -euo pipefail

# -- locate repo regardless of where the script is called from -----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_DIR="$REPO_DIR/bridge"
INSTALL_DIR="$REPO_DIR/install"

# -- defaults ------------------------------------------------------------------
HTTP_PORT=8787
INSTALL_SERVICE=ask     # ask | yes | no
TARGET_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

# -- colour helpers ------------------------------------------------------------
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi
say()  { printf "%s==>%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s!!%s %s\n"  "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf "%sxx%s %s\n"  "$RED"    "$RESET" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
${BOLD}agentic-ai-controller installer${RESET}

Usage: $(basename "$0") [options]

Options:
  --port PORT        HTTP port the bridge will listen on (default: 8787)
  --no-service       Don't install the auto-start service
  --service          Install the auto-start service without prompting
  --target PATH      Path to Claude Code settings.json
                     (default: \$CLAUDE_SETTINGS or ~/.claude/settings.json)
  --help             Show this message

Files touched:
  * $TARGET_SETTINGS  (hooks merged in; backed up before write)
  * ~/Library/LaunchAgents/com.agenticai.controller.plist      (macOS, if --service)
  * ~/.config/systemd/user/agentic-ai-controller.service       (Linux,  if --service)
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --port)       HTTP_PORT="$2"; shift 2 ;;
        --no-service) INSTALL_SERVICE=no; shift ;;
        --service)    INSTALL_SERVICE=yes; shift ;;
        --target)     TARGET_SETTINGS="$2"; shift 2 ;;
        -h|--help)    usage; exit 0 ;;
        *) die "unknown option: $1  (try --help)" ;;
    esac
done

OS="$(uname -s)"
case "$OS" in
    Darwin) PLATFORM=macos ;;
    Linux)  PLATFORM=linux ;;
    *)      PLATFORM=unknown ;;
esac

# -- step 1: python deps -------------------------------------------------------
say "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
    die "python3 is not on PATH. Install Python 3.9+ and re-run."
fi
PY_VER="$(python3 -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))')"
say "Python $PY_VER detected"

say "Installing Python dependencies"
if ! python3 -m pip install --quiet -r "$BRIDGE_DIR/requirements.txt"; then
    die "pip install failed. Try: python3 -m pip install -r $BRIDGE_DIR/requirements.txt"
fi

# -- step 2: merge hooks -------------------------------------------------------
say "Merging LED hooks into $TARGET_SETTINGS"
python3 "$INSTALL_DIR/hooks_merge.py" --target "$TARGET_SETTINGS" --port "$HTTP_PORT"

# -- step 3: auto-start service (optional) -------------------------------------
if [ "$INSTALL_SERVICE" = "ask" ]; then
    printf "\n%sInstall auto-start service?%s [Y/n] " "$BOLD" "$RESET"
    read -r reply || reply=""
    case "${reply:-Y}" in
        N|n|no|No) INSTALL_SERVICE=no ;;
        *)         INSTALL_SERVICE=yes ;;
    esac
fi

if [ "$INSTALL_SERVICE" = "yes" ]; then
    PYTHON_BIN="$(command -v python3)"
    BRIDGE_SCRIPT="$BRIDGE_DIR/agentic_ai_bridge.py"

    if [ "$PLATFORM" = "macos" ]; then
        PLIST_SRC="$INSTALL_DIR/com.agenticai.controller.plist.template"
        PLIST_DST="$HOME/Library/LaunchAgents/com.agenticai.controller.plist"
        mkdir -p "$(dirname "$PLIST_DST")"
        sed \
            -e "s|{{PYTHON_BIN}}|$PYTHON_BIN|g" \
            -e "s|{{BRIDGE_SCRIPT}}|$BRIDGE_SCRIPT|g" \
            -e "s|{{HTTP_PORT}}|$HTTP_PORT|g" \
            -e "s|{{LOG_DIR}}|$HOME/Library/Logs/agentic-ai-controller|g" \
            "$PLIST_SRC" > "$PLIST_DST"
        mkdir -p "$HOME/Library/Logs/agentic-ai-controller"
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        launchctl load -w "$PLIST_DST"
        say "launchd service installed at $PLIST_DST"
        say "logs: ~/Library/Logs/agentic-ai-controller/"
    elif [ "$PLATFORM" = "linux" ]; then
        UNIT_SRC="$INSTALL_DIR/agentic-ai-controller.service.template"
        UNIT_DST="$HOME/.config/systemd/user/agentic-ai-controller.service"
        mkdir -p "$(dirname "$UNIT_DST")"
        sed \
            -e "s|{{PYTHON_BIN}}|$PYTHON_BIN|g" \
            -e "s|{{BRIDGE_SCRIPT}}|$BRIDGE_SCRIPT|g" \
            -e "s|{{HTTP_PORT}}|$HTTP_PORT|g" \
            "$UNIT_SRC" > "$UNIT_DST"
        systemctl --user daemon-reload
        systemctl --user enable --now agentic-ai-controller.service
        say "systemd user service installed: agentic-ai-controller.service"
        say "check with: systemctl --user status agentic-ai-controller"
    else
        warn "unknown platform $OS — skipping service install"
    fi
fi

# -- post-install summary ------------------------------------------------------
cat <<EOF

${GREEN}${BOLD}Done.${RESET}

Next steps:
  ${BOLD}1.${RESET} Upload the sketch to the Arduino Uno:
        Open Arduino IDE, File -> Open ->
          $REPO_DIR/arduino/agentic_ai_controller/agentic_ai_controller.ino
        Tools -> Board: Arduino Uno
        Tools -> Port:  pick the /dev/cu.usbmodem* (macOS), /dev/ttyACM* (Linux), or COM* (Windows)
        Click Upload. The three LEDs flash once and the green one stays on.

  ${BOLD}2.${RESET} $([ "$INSTALL_SERVICE" = "yes" ] && echo "The bridge is already running in the background." || echo "Start the bridge manually:   python3 $BRIDGE_DIR/agentic_ai_bridge.py")

  ${BOLD}3.${RESET} ${YELLOW}macOS only:${RESET} when you press the button the first time, macOS will
     prompt for Accessibility access. Grant it to the terminal (or launchd
     process) running the bridge, then restart the bridge.

  ${BOLD}4.${RESET} In Claude Code, run  /hooks  once to force a settings reload, or
     simply restart claude.

To uninstall later:  ${DIM}$INSTALL_DIR/uninstall.sh${RESET}
EOF
