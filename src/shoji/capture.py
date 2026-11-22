"""Per-request capture: one record per proxied request, sent to pluggable sinks.

A record holds metadata only (ids, model, status, timings) and never prompt or response
content. Stage 1 ships a JSON-log sink; later stages add sinks (e.g. the SQLite audit log)
without touching the proxy code.
"""

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("shoji.requests")

# Client-supplied request ids are reused (handy for tracing) only if they look safe to log.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def request_id_from(header_value: str | None) -> str:
    if header_value and _SAFE_REQUEST_ID.match(header_value):
        return header_value
    return uuid.uuid4().hex


@dataclass
class RequestRecord:
    request_id: str
    provider: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    model: str | None = None
    stream: bool = False
    status: int | None = None
    # Time until the upstream response arrived (headers, for streams), including retries.
    upstream_latency_ms: float | None = None
    # Time until the proxy finished responding (end of stream, for streams).
    total_latency_ms: float | None = None
    error_type: str | None = None
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def mark_upstream(self) -> None:
        self.upstream_latency_ms = _ms_since(self._t0)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


Sink = Callable[[RequestRecord], None]


def log_sink(record: RequestRecord) -> None:
    logger.info(json.dumps(record.to_dict()))


class Capture:
    """Finalises records and fans them out to sinks. A failing sink never fails a request."""

    def __init__(self, sinks: Iterable[Sink] = (log_sink,)) -> None:
        self.sinks = list(sinks)

    def finish(self, record: RequestRecord, status: int) -> None:
        record.status = status
        record.total_latency_ms = _ms_since(record._t0)
        for sink in self.sinks:
            try:
                sink(record)
            except Exception:
                logging.getLogger(__name__).exception("Capture sink %r failed", sink)


def configure_logging() -> None:
    """Send request records to stdout as one JSON object per line."""
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)
