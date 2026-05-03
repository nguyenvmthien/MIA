"""Shared pytest fixtures."""

import pytest

from meeting_agent.schemas.transcript import TranscriptTurn
from meeting_agent.schemas.worker import Worker, WorkerRoster


@pytest.fixture
def roster():
    return WorkerRoster(workers=[
        Worker(worker_id="w1", name="Alice Chen", aliases=["Alice"]),
        Worker(worker_id="w2", name="Bob Kim", aliases=["Bob"]),
    ])


@pytest.fixture
def turns():
    return [
        TranscriptTurn(
            turn_id="t1",
            speaker_id="S1",
            speaker_name="Alice Chen",
            start_ms=0,
            end_ms=5000,
            text="Alice can you write the API docs by Friday?",
        ),
    ]
