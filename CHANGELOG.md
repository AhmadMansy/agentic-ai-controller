# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-04-17

### Added
- Initial public release.
- Arduino sketch: 3-colour LED state output, approve button + joystick input, newline-delimited serial protocol at 9600 baud.
- Python bridge with:
  - Cross-platform serial-port auto-detection (macOS / Linux / Windows)
  - Loopback HTTP API for Claude Code hooks
  - Auto-reconnect on Arduino disconnect/replug
  - Configurable keybindings via `config.json`
  - `--list-ports`, `--dry-run`-style CLI ergonomics
- Idempotent installer that merges LED hooks into `~/.claude/settings.json` without overwriting existing user hooks.
- Uninstaller that removes only hooks it owns (identified by the bridge URL marker).
- launchd plist template (macOS) and systemd user-unit template (Linux) for auto-start at login.
- Hardware setup HTML guide with wiring diagram.
