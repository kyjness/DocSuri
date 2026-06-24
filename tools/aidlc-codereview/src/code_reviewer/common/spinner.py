"""Terminal spinner for long-running operations."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import itertools
import sys
import threading
import time


class Spinner:
    """A simple terminal spinner that runs in a background thread.

    Usage:
        with Spinner("Analyzing code"):
            do_long_running_work()
    """

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Working", interval: float = 0.08):
        self.message = message
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        frames = itertools.cycle(self._FRAMES)
        while not self._stop_event.is_set():
            frame = next(frames)
            sys.stdout.write(f"\r  {frame} {self.message}...")
            sys.stdout.flush()
            time.sleep(self.interval)
        # Clear the spinner line when done
        sys.stdout.write(f"\r  ✔ {self.message}... done\n")
        sys.stdout.flush()

    def start(self) -> "Spinner":
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()
