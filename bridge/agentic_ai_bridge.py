#!/usr/bin/env python3
"""
agentic-ai-bridge — physical controller for AI coding agents.

Owns the Arduino serial port and exposes a loopback HTTP API so Claude Code
hooks can set the LED state with a single curl. In the reverse direction,
button and joystick events from the Arduino are turned into keystrokes
(Enter / ↑ / ↓) and injected into the frontmost window.

Run:
    python3 agentic_ai_bridge.py                 # auto-detect everything
    python3 agentic_ai_bridge.py --port /dev/cu.usbmodem1101
    python3 agentic_ai_bridge.py --config ./config.json
    python3 agentic_ai_bridge.py --help

HTTP (loopback only):
    GET /led/red      red on   (agent is busy)
    GET /led/yellow   yellow on (agent wants permission)
    GET /led/green    green on (agent is idle/ready)
    GET /led/off      all off
    GET /led/test     cycle all 3 LEDs once
    GET /healthz      bridge liveness check

Serial protocol (see arduino/agentic_ai_controller/agentic_ai_controller.ino):
    Host -> Arduino:  R | Y | G | O | T
    Arduino -> Host:  BTN\\n | UP\\n | DN\\n

Supported on macOS, Linux, and Windows.
macOS: first synthetic keystroke triggers an Accessibility prompt.
Grant access to the *terminal* running this bridge, then restart it.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import platform
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    print("error: pyserial is not installed. Run: pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(2)

try:
    from pynput.keyboard import Controller, Key
except ImportError:  # pragma: no cover
    print("error: pynput is not installed. Run: pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(2)

__version__ = "1.0.0"

log = logging.getLogger("agentic-ai-bridge")

DEFAULT_CONFIG = {
    "port": None,               # None → auto-detect
    "baud": 9600,
    "http_host": "127.0.0.1",
    "http_port": 8787,
    "reconnect_delay_s": 2.0,
    "boot_test": True,
    "keys": {
        "approve": "enter",     # button press
        "up": "up",             # joystick up
        "down": "down",         # joystick down
    },
}

# Human-readable key name -> pynput Key enum. Anything not in this map is
# treated as a literal character (e.g. "y" to answer yes in a y/n prompt).
SPECIAL_KEYS = {
    "enter": Key.enter,
    "return": Key.enter,
    "space": Key.space,
    "tab": Key.tab,
    "esc": Key.esc,
    "escape": Key.esc,
    "backspace": Key.backspace,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
}


# --------------------------------------------------------------------------- #
# Serial port discovery
# --------------------------------------------------------------------------- #

def detect_ports() -> list[str]:
    """Return a list of candidate serial ports, most-likely-Arduino first."""
    system = platform.system()
    if system == "Darwin":
        patterns = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"]
        found: list[str] = []
        for p in patterns:
            found.extend(sorted(glob.glob(p)))
        return found
    if system == "Linux":
        patterns = ["/dev/ttyACM*", "/dev/ttyUSB*"]
        found = []
        for p in patterns:
            found.extend(sorted(glob.glob(p)))
        return found
    if system == "Windows":
        likely = []
        others = []
        for info in list_ports.comports():
            desc = (info.description or "") + " " + (info.manufacturer or "")
            entry = info.device
            if any(key in desc.lower() for key in ("arduino", "usb serial", "ch340", "wch", "ftdi")):
                likely.append(entry)
            else:
                others.append(entry)
        return likely + others
    return []


def resolve_port(preferred: Optional[str]) -> str:
    if preferred:
        if not Path(preferred).exists() and platform.system() != "Windows":
            log.warning("configured port %s does not exist; trying anyway", preferred)
        return preferred
    candidates = detect_ports()
    if not candidates:
        raise SystemExit(
            "error: no Arduino-like serial port found. Plug the Arduino in, "
            "or pass --port /path/to/device. Detected none on this system."
        )
    return candidates[0]


# --------------------------------------------------------------------------- #
# Keystroke dispatch
# --------------------------------------------------------------------------- #

class KeyDispatcher:
    def __init__(self, key_config: dict[str, str]):
        self.keyboard = Controller()
        self.bindings = {
            "BTN": self._resolve(key_config.get("approve", "enter")),
            "UP":  self._resolve(key_config.get("up", "up")),
            "DN":  self._resolve(key_config.get("down", "down")),
        }

    @staticmethod
    def _resolve(name: str):
        name = (name or "").strip().lower()
        if name in SPECIAL_KEYS:
            return SPECIAL_KEYS[name]
        if len(name) == 1:
            return name  # literal character
        raise SystemExit(f"error: unknown key name {name!r}. "
                         f"Valid specials: {', '.join(sorted(SPECIAL_KEYS))}")

    def dispatch(self, event: str) -> bool:
        key = self.bindings.get(event)
        if key is None:
            return False
        try:
            self.keyboard.press(key)
            self.keyboard.release(key)
            return True
        except Exception as e:
            log.warning("keystroke dispatch failed: %s", e)
            return False


# --------------------------------------------------------------------------- #
# Serial link with auto-reconnect
# --------------------------------------------------------------------------- #

class SerialLink:
    """Thin wrapper around pyserial with reconnect-on-failure semantics."""

    def __init__(self, port: str, baud: int, reconnect_delay: float):
        self.port_name = port
        self.baud = baud
        self.reconnect_delay = reconnect_delay
        self.ser: Optional[serial.Serial] = None
        self.write_lock = threading.Lock()
        self._stop = threading.Event()
        self._connect()

    def _connect(self) -> None:
        self.ser = serial.Serial(self.port_name, self.baud, timeout=0.2)
        # Arduino Uno auto-resets on port open; give its bootloader time.
        time.sleep(2.0)
        log.info("connected: %s @ %d", self.port_name, self.baud)

    def stop(self) -> None:
        self._stop.set()
        with self.write_lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass

    def send(self, cmd: str) -> bool:
        """Send a command char. Returns True on success, False on disconnect."""
        with self.write_lock:
            if not self.ser or not self.ser.is_open:
                return False
            try:
                self.ser.write(cmd.encode("ascii"))
                self.ser.flush()
                return True
            except (serial.SerialException, OSError) as e:
                log.warning("send failed (%s); will reconnect", e)
                return False

    def readline(self) -> str:
        """Blocking-ish read of one line. Raises on disconnect."""
        if not self.ser:
            raise serial.SerialException("not connected")
        line = self.ser.readline()
        return line.decode("ascii", errors="ignore").strip()

    def reconnect_forever(self) -> None:
        """Reconnect loop — call after a read/write failure."""
        with self.write_lock:
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
        while not self._stop.is_set():
            try:
                # Re-detect: user may have plugged into a different USB port.
                candidates = detect_ports()
                if candidates:
                    self.port_name = candidates[0]
                self._connect()
                return
            except Exception as e:
                log.warning("reconnect failed (%s); retry in %.1fs",
                            e, self.reconnect_delay)
                if self._stop.wait(self.reconnect_delay):
                    return


# --------------------------------------------------------------------------- #
# Reader thread
# --------------------------------------------------------------------------- #

def reader_loop(link: SerialLink, keys: KeyDispatcher,
                stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            line = link.readline()
        except (serial.SerialException, OSError) as e:
            log.warning("serial read lost: %s", e)
            link.reconnect_forever()
            continue
        except Exception:
            log.exception("unexpected reader error")
            time.sleep(1.0)
            continue

        if not line:
            continue
        if line in ("BTN", "UP", "DN"):
            ok = keys.dispatch(line)
            log.info("%s -> %s", line, "ok" if ok else "FAILED")
        else:
            log.debug("ignored: %r", line)


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

ROUTES = {
    "/led/red":    "R",
    "/led/yellow": "Y",
    "/led/green":  "G",
    "/led/off":    "O",
    "/led/test":   "T",
}


def make_handler(link: SerialLink):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path in ("/healthz", "/health"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "ok": link.ser is not None and link.ser.is_open,
                    "version": __version__,
                    "port": link.port_name,
                }).encode())
                return

            cmd = ROUTES.get(self.path)
            if cmd is None:
                self.send_response(404)
                self.end_headers()
                return

            ok = link.send(cmd)
            if not ok:
                # Serial is down but HTTP must still return fast so hooks
                # don't stall. The reader thread will reconnect.
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"serial unavailable\n")
                # Kick a reconnect in the background.
                threading.Thread(target=link.reconnect_forever, daemon=True).start()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"ok {cmd}\n".encode())

        def log_message(self, fmt, *args):  # silence default stderr access log
            return

    return Handler


# --------------------------------------------------------------------------- #
# Config & CLI
# --------------------------------------------------------------------------- #

def load_config(path: Optional[Path]) -> dict:
    cfg = {**DEFAULT_CONFIG, "keys": dict(DEFAULT_CONFIG["keys"])}
    if path is None:
        return cfg
    if not path.exists():
        log.warning("config file %s not found; using defaults", path)
        return cfg
    try:
        user = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: config {path} is not valid JSON: {e}")
    for k, v in user.items():
        if k == "keys" and isinstance(v, dict):
            cfg["keys"].update(v)
        else:
            cfg[k] = v
    return cfg


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agentic-ai-bridge",
        description="Physical controller bridge for AI coding agents.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", type=Path, default=None,
                   help="Path to JSON config file")
    p.add_argument("--port", default=None,
                   help="Serial device path (e.g. /dev/cu.usbmodem1101, COM3)")
    p.add_argument("--baud", type=int, default=None,
                   help="Serial baud rate")
    p.add_argument("--http-host", default=None, help="HTTP bind host")
    p.add_argument("--http-port", type=int, default=None, help="HTTP bind port")
    p.add_argument("--list-ports", action="store_true",
                   help="List detected serial ports and exit")
    p.add_argument("--no-boot-test", action="store_true",
                   help="Skip the startup LED cycle")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def apply_cli_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    if args.port is not None:      cfg["port"] = args.port
    if args.baud is not None:      cfg["baud"] = args.baud
    if args.http_host is not None: cfg["http_host"] = args.http_host
    if args.http_port is not None: cfg["http_port"] = args.http_port
    if args.no_boot_test:          cfg["boot_test"] = False
    return cfg


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_ports:
        ports = detect_ports()
        if not ports:
            print("(no candidate serial ports found)")
            return 1
        for p in ports:
            print(p)
        return 0

    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    port = resolve_port(cfg["port"])
    link = SerialLink(port, cfg["baud"], cfg["reconnect_delay_s"])

    if cfg["boot_test"]:
        link.send("T")

    keys = KeyDispatcher(cfg["keys"])
    stop = threading.Event()

    reader = threading.Thread(
        target=reader_loop, args=(link, keys, stop),
        name="serial-reader", daemon=True,
    )
    reader.start()

    server = ThreadingHTTPServer((cfg["http_host"], cfg["http_port"]), make_handler(link))
    log.info("listening http://%s:%d/led/{red,yellow,green,off,test}  healthz=/healthz",
             cfg["http_host"], cfg["http_port"])
    log.info("keys: approve=%s  up=%s  down=%s",
             cfg["keys"]["approve"], cfg["keys"]["up"], cfg["keys"]["down"])

    def _shutdown(signum, frame):
        log.info("signal %s received; shutting down", signum)
        stop.set()
        try:
            link.send("O")   # LEDs off
        except Exception:
            pass
        link.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
