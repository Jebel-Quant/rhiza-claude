#!/usr/bin/env python3
"""The reporting sink every `validate.py` check writes to.

Its own module because all three halves of the validator need it — the structure checks,
the field checks, and the orchestration — and a shim they all import cannot live in the
module that imports them.

Two audiences from one call: a human reading symbol-prefixed lines on stderr, and
``--json``, which needs the ERROR and WARNING messages as data. That is the whole reason
this is a class and not `print`.
"""

from __future__ import annotations

import sys


class Log:
    """Tiny stand-in for the CLI's loguru sink.

    Prints human-readable, symbol-prefixed lines to stderr and, so `--json`
    can report a structured verdict, accumulates the ERROR/WARNING messages.
    """

    _SYMBOLS = {"error": "✗", "warning": "!", "success": "✓", "info": " ", "debug": " "}

    def __init__(self, *, verbose: bool = False) -> None:
        """Start the sink with empty error/warning buffers."""
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._verbose = verbose

    def _emit(self, level: str, message: str) -> None:
        """Print a symbol-prefixed line (debug only when verbose)."""
        if level == "debug" and not self._verbose:
            return
        print(f"{self._SYMBOLS[level]} {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        """Record and print an error."""
        self.errors.append(message)
        self._emit("error", message)

    def warning(self, message: str) -> None:
        """Record and print a warning."""
        self.warnings.append(message)
        self._emit("warning", message)

    def success(self, message: str) -> None:
        """Print a success line."""
        self._emit("success", message)

    def info(self, message: str) -> None:
        """Print an info line."""
        self._emit("info", message)

    def debug(self, message: str) -> None:
        """Print a debug line (verbose only)."""
        self._emit("debug", message)
