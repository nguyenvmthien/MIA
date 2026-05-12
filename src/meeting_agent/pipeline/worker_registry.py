"""Persistent worker registry.

Workers added via the UI or API are persisted here and pre-populate the
participant picker on the meeting submission form.
"""

import json
import logging
import uuid
from pathlib import Path
from threading import Lock

from meeting_agent.config import settings
from meeting_agent.db.engine import get_session
from meeting_agent.db.models import WorkerRecord
from meeting_agent.schemas.worker import Worker, WorkerRoster

log = logging.getLogger(__name__)
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


def _to_schema(row: WorkerRecord) -> Worker:
    return Worker(
        worker_id=row.worker_id,
        name=row.name,
        aliases=list(row.aliases or []),
        role=row.role,
        email=row.email,
        skills=list(row.skills or []),
    )


def _db_unavailable(exc: Exception) -> bool:
    log.debug("Worker DB unavailable, falling back to file registry: %s", exc)
    return True


def list_workers(owner_user_id: str | None = None) -> list[Worker]:
    """Return all registered workers sorted by name."""
    try:
        with get_session() as session:
            query = session.query(WorkerRecord)
            if owner_user_id is not None:
                query = query.filter(WorkerRecord.owner_user_id == owner_user_id)
            else:
                query = query.filter(WorkerRecord.owner_user_id.is_(None))
            rows = query.order_by(WorkerRecord.name.asc()).all()
            return [_to_schema(row) for row in rows]
    except Exception as exc:
        _db_unavailable(exc)
        return sorted(_load_all(), key=lambda w: w.name.lower())


def get_worker(worker_id: str, owner_user_id: str | None = None) -> Worker | None:
    try:
        with get_session() as session:
            query = session.query(WorkerRecord).filter(WorkerRecord.worker_id == worker_id)
            if owner_user_id is not None:
                query = query.filter(WorkerRecord.owner_user_id == owner_user_id)
            else:
                query = query.filter(WorkerRecord.owner_user_id.is_(None))
            row = query.first()
            return _to_schema(row) if row else None
    except Exception as exc:
        _db_unavailable(exc)
        for w in _load_all():
            if w.worker_id == worker_id:
                return w
    return None


def add_worker(worker: Worker, owner_user_id: str | None = None) -> Worker:
    """Persist a new worker. Raises ValueError if a worker with same name already exists."""
    if not worker.worker_id:
        worker = worker.model_copy(update={"worker_id": str(uuid.uuid4())[:8]})
    try:
        with get_session() as session:
            existing = (
                session.query(WorkerRecord)
                .filter(
                    WorkerRecord.owner_user_id == owner_user_id,
                    WorkerRecord.name.ilike(worker.name),
                )
                .first()
            )
            if existing is not None:
                raise ValueError(f"Worker '{worker.name}' already exists.")
            session.add(WorkerRecord(
                worker_id=worker.worker_id,
                owner_user_id=owner_user_id,
                name=worker.name,
                email=worker.email,
                role=worker.role,
                aliases=worker.aliases,
                skills=worker.skills,
            ))
        return worker
    except ValueError:
        raise
    except Exception as exc:
        _db_unavailable(exc)

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


def update_worker(
    worker_id: str,
    updated: Worker,
    owner_user_id: str | None = None,
) -> Worker | None:
    """Replace a worker record. Returns the updated worker, or None if not found."""
    try:
        with get_session() as session:
            query = session.query(WorkerRecord).filter(WorkerRecord.worker_id == worker_id)
            if owner_user_id is not None:
                query = query.filter(WorkerRecord.owner_user_id == owner_user_id)
            else:
                query = query.filter(WorkerRecord.owner_user_id.is_(None))
            row = query.first()
            if row is None:
                return None
            row.name = updated.name
            row.email = updated.email
            row.role = updated.role
            row.aliases = updated.aliases
            row.skills = updated.skills
            return updated.model_copy(update={"worker_id": worker_id})
    except Exception as exc:
        _db_unavailable(exc)

    with _lock:
        workers = _load_all()
        for i, w in enumerate(workers):
            if w.worker_id == worker_id:
                workers[i] = updated.model_copy(update={"worker_id": worker_id})
                _save_all(workers)
                return workers[i]
    return None


def delete_worker(worker_id: str, owner_user_id: str | None = None) -> bool:
    """Delete a worker by ID. Returns True if found and deleted."""
    try:
        with get_session() as session:
            query = session.query(WorkerRecord).filter(WorkerRecord.worker_id == worker_id)
            if owner_user_id is not None:
                query = query.filter(WorkerRecord.owner_user_id == owner_user_id)
            else:
                query = query.filter(WorkerRecord.owner_user_id.is_(None))
            row = query.first()
            if row is None:
                return False
            session.delete(row)
            return True
    except Exception as exc:
        _db_unavailable(exc)

    with _lock:
        workers = _load_all()
        new = [w for w in workers if w.worker_id != worker_id]
        if len(new) == len(workers):
            return False
        _save_all(new)
    return True


def build_roster(worker_ids: list[str], owner_user_id: str | None = None) -> WorkerRoster:
    """Build a WorkerRoster from a subset of registered worker IDs."""
    all_workers = {w.worker_id: w for w in list_workers(owner_user_id=owner_user_id)}
    selected = [all_workers[wid] for wid in worker_ids if wid in all_workers]
    return WorkerRoster(workers=selected)
