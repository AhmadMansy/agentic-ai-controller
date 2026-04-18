# Contributing to claude-controller

Thanks for wanting to help. This is a small, hardware-adjacent project — contributions are welcome in all of these areas:

- **Bug reports** — especially serial-port quirks on Linux/Windows distros you use
- **New hardware targets** — pin maps for ESP32, Pro Micro, Raspberry Pi Pico, etc.
- **New LED states or gestures** — e.g. a blue "thinking" state, or a scroll-wheel for prompt history
- **Docs** — better wiring diagrams, localized translations
- **Cross-platform keystroke paths** — alternatives to pynput on Wayland, headless Linux

## Ground rules

1. **Keep the bridge dependency-light.** Every new pip package is a step toward "this won't install for someone". Prefer stdlib. `pyserial` and `pynput` are the ceiling.
2. **Never hardcode user paths.** Anything that references `~/.claude/settings.json` or `/dev/cu.usbmodem*` must be overridable with a flag or env var.
3. **Idempotency is not optional.** `install.sh` run twice must equal `install.sh` run once. Same for `hooks_merge.py`.
4. **Never destroy user hooks.** The installer identifies its own hooks by the `127.0.0.1:PORT/led/` marker. Any new hook you add must use the same marker scheme so the uninstaller can reverse it cleanly.

## Dev setup

```bash
git clone https://github.com/YOUR-FORK/claude-controller
cd claude-controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r bridge/requirements.txt

# Run the bridge without installing hooks
python3 bridge/claude_bridge.py --log-level DEBUG
```

Dry-run the hook merger against a throwaway file to test changes:

```bash
echo '{}' > /tmp/settings.json
python3 install/hooks_merge.py --target /tmp/settings.json --dry-run
```

## Pull requests

- Small, focused PRs beat large ones.
- Update `CHANGELOG.md` under "Unreleased".
- For hardware changes, include a photo of your prototype in the PR description.
- For new flags or config keys, update `bridge/config.example.json` and `docs/hardware_setup.html` (or the README) in the same PR.

## Reporting bugs

Please include:

- OS + version, Python version, Arduino board model
- Output of `python3 bridge/claude_bridge.py --log-level DEBUG --list-ports`
- Contents of `~/.claude/settings.json` with any secrets redacted
- Whether the LEDs light on boot (confirms the Arduino sketch is running)
- Whether `curl http://127.0.0.1:8787/led/test` cycles the LEDs (confirms HTTP path)
