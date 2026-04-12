"""Persistent worker registry — stores workers in a JSON file on disk.

Workers added via the UI or API are persisted here and pre-populate the
participant picker on the meeting submission form.
"""

import json
import uuid
from pathlib import Path
from threading import Lock

from meeting_agent.config import settings
from meeting_agent.schemas.worker import Worker, WorkerRoster

_lock = Lock()


def _path() -> Path:
    return Path(settings.workers_storage_path)


def _load_all() -> list[Worker]:
    p = _path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
        return [Worker.model_validate(w) for w in raw]
    except Exception:
        return []


def _save_all(workers: list[Worker]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([w.model_dump() for w in workers], indent=2))


def list_workers() -> list[Worker]:
    """Return all registered workers sorted by name."""
    return sorted(_load_all(), key=lambda w: w.name.lower())


def get_worker(worker_id: str) -> Worker | None:
    for w in _load_all():
        if w.worker_id == worker_id:
            return w
    return None


def add_worker(worker: Worker) -> Worker:
    """Persist a new worker. Raises ValueError if a worker with same name already exists."""
    with _lock:
        workers = _load_all()
        existing_names = {w.name.lower() for w in workers}
        if worker.name.lower() in existing_names:
            raise ValueError(f"Worker '{worker.name}' already exists.")
        if not worker.worker_id:
            worker = worker.model_copy(update={"worker_id": str(uuid.uuid4())[:8]})
        workers.append(worker)
        _save_all(workers)
    return worker


def delete_worker(worker_id: str) -> bool:
    """Delete a worker by ID. Returns True if found and deleted."""
    with _lock:
        workers = _load_all()
        new = [w for w in workers if w.worker_id != worker_id]
        if len(new) == len(workers):
            return False
        _save_all(new)
    return True


def build_roster(worker_ids: list[str]) -> WorkerRoster:
    """Build a WorkerRoster from a subset of registered worker IDs."""
    all_workers = {w.worker_id: w for w in _load_all()}
    selected = [all_workers[wid] for wid in worker_ids if wid in all_workers]
    return WorkerRoster(workers=selected)
