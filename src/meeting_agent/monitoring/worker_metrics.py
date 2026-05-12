"""Prometheus HTTP endpoint for Celery worker metrics."""

from __future__ import annotations

import logging
import os
import threading
from wsgiref.simple_server import make_server

from prometheus_client import CollectorRegistry, make_wsgi_app, multiprocess

log = logging.getLogger(__name__)

_started = False


def _app():
    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
    return make_wsgi_app(registry)


def start_worker_metrics_server(port: int) -> None:
    """Start a lightweight HTTP server that exposes worker Prometheus metrics."""
    global _started
    if _started or port <= 0:
        return

    def serve() -> None:
        server = make_server("0.0.0.0", port, _app())
        log.info("Worker metrics endpoint listening on :%s", port)
        server.serve_forever()

    thread = threading.Thread(target=serve, name="worker-metrics", daemon=True)
    thread.start()
    _started = True
