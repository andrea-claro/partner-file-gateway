"""Structured JSON logs: one line per event, correlated by ``transfer_id``.

CloudWatch Logs (or LocalStack's log output) stores each line as-is, so a
query such as ``filter transfer_id = "..."`` returns the full story of a file.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class JsonLogger:
    def __init__(self, component: str, stream: TextIO | None = None, **context: Any) -> None:
        self.component = component
        self.stream = stream or sys.stdout
        self.context = context
        self.threshold = _LEVELS.get(os.environ.get("LOG_LEVEL", "INFO").upper(), 20)

    def bind(self, **context: Any) -> JsonLogger:
        """Return a logger that adds ``context`` to every line."""
        return JsonLogger(self.component, self.stream, **{**self.context, **context})

    def _emit(self, level: str, message: str, fields: dict[str, Any]) -> None:
        if _LEVELS[level] < self.threshold:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": level,
            "component": self.component,
            "message": message,
            **self.context,
            **fields,
        }
        self.stream.write(json.dumps(record, default=str) + "\n")
        self.stream.flush()

    def debug(self, message: str, **fields: Any) -> None:
        self._emit("DEBUG", message, fields)

    def info(self, message: str, **fields: Any) -> None:
        self._emit("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("ERROR", message, fields)
