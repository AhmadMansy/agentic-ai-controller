#!/usr/bin/env python3
"""
Idempotent installer for agentic-ai-controller LED hooks.

Adds five hook entries to ~/.claude/settings.json (or --target) that each
ping the bridge's HTTP API. Preserves every hook the user already has; on
re-run, updates only the entries we own and leaves foreign hooks untouched.

Identity: "our" hooks are command hooks whose `command` string contains
the distinctive substring stored in MARKER_URL below. Uninstall reverses
the install by deleting any hook matching that marker.

Usage:
    python3 hooks_merge.py                          # install, uses ~/.claude/settings.json
    python3 hooks_merge.py --uninstall
    python3 hooks_merge.py --port 8787              # override bridge HTTP port
    python3 hooks_merge.py --target /path/to/settings.json
    python3 hooks_merge.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

MARKER_URL_FMT = "127.0.0.1:{port}/led/"   # identifies our hooks on uninstall

# (event_name, led_color)
EVENT_TO_COLOR = [
    ("UserPromptSubmit",  "red"),
    ("PreToolUse",        "red"),
    ("PostToolUse",       "red"),
    ("PermissionRequest", "yellow"),
    ("Stop",              "green"),
]


def our_curl(port: int, color: str) -> str:
    return (
        f"curl -s --max-time 1 http://127.0.0.1:{port}/led/{color} "
        f"> /dev/null 2>&1 || true"
    )


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: {path} is not valid JSON: {e}")


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup_path)
    return backup_path


def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def is_ours(cmd: dict, marker: str) -> bool:
    return (
        isinstance(cmd, dict)
        and cmd.get("type") == "command"
        and marker in str(cmd.get("command", ""))
    )


def strip_our_hooks(settings: dict, marker: str) -> dict:
    """Remove only hooks whose command contains `marker`; keep everything else."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings

    new_hooks: dict = {}
    for event, matcher_blocks in hooks.items():
        if not isinstance(matcher_blocks, list):
            new_hooks[event] = matcher_blocks
            continue
        kept_blocks = []
        for block in matcher_blocks:
            if not isinstance(block, dict):
                kept_blocks.append(block)
                continue
            inner = block.get("hooks", [])
            if not isinstance(inner, list):
                kept_blocks.append(block)
                continue
            kept = [h for h in inner if not is_ours(h, marker)]
            if kept:
                new_block = dict(block)
                new_block["hooks"] = kept
                kept_blocks.append(new_block)
            # else: block becomes empty -> drop it entirely
        if kept_blocks:
            new_hooks[event] = kept_blocks
        # else: entire event had no other hooks -> drop the event

    out = dict(settings)
    if new_hooks:
        out["hooks"] = new_hooks
    else:
        out.pop("hooks", None)
    return out


def add_our_hooks(settings: dict, port: int) -> dict:
    """Append our LED hook to each configured event, leaving foreign hooks intact."""
    out = dict(settings)
    hooks = dict(out.get("hooks") or {})

    for event, color in EVENT_TO_COLOR:
        blocks = list(hooks.get(event) or [])
        target_block = None
        # Prefer a matcher-less block if one exists (matches every tool).
        for b in blocks:
            if isinstance(b, dict) and not b.get("matcher") and isinstance(b.get("hooks"), list):
                target_block = b
                break
        if target_block is None:
            target_block = {"hooks": []}
            blocks.append(target_block)

        target_block["hooks"].append({
            "type": "command",
            "command": our_curl(port, color),
            "async": True,
        })
        hooks[event] = blocks

    out["hooks"] = hooks
    return out


def install(settings: dict, port: int) -> dict:
    # Always strip first so re-running install is a no-op (idempotent).
    marker = MARKER_URL_FMT.format(port=port)
    settings = strip_our_hooks(settings, marker)
    return add_our_hooks(settings, port)


def uninstall(settings: dict, port: int) -> dict:
    marker = MARKER_URL_FMT.format(port=port)
    return strip_our_hooks(settings, marker)


def default_target() -> Path:
    return Path.home() / ".claude" / "settings.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--target", type=Path, default=default_target(),
                   help="Path to the Claude Code settings.json (default: ~/.claude/settings.json)")
    p.add_argument("--port", type=int, default=8787,
                   help="HTTP port the bridge listens on (default: 8787)")
    p.add_argument("--uninstall", action="store_true",
                   help="Remove our hooks instead of adding them")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resulting JSON; do not write")
    args = p.parse_args(argv)

    target: Path = args.target
    settings = load_settings(target)

    if args.uninstall:
        new_settings = uninstall(settings, args.port)
        action = "uninstall"
    else:
        new_settings = install(settings, args.port)
        action = "install"

    output = json.dumps(new_settings, indent=2) + "\n"

    if args.dry_run:
        print(output)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    bak = backup(target) if target.exists() else None
    atomic_write(target, output)

    if bak:
        print(f"[hooks_merge] {action}: wrote {target} (backup {bak.name})")
    else:
        print(f"[hooks_merge] {action}: created {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
