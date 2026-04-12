"""
FAISS speaker RAG — builds a speaker profile index from transcript turns
and retrieves relevant context when assembling prompts.

Used to give the LLM richer context about each speaker (role, past statements)
without bloating every prompt with the full transcript history.
"""

import logging

import numpy as np

from meeting_agent.config import settings
from meeting_agent.schemas.transcript import TranscriptTurn

log = logging.getLogger(__name__)

try:
    import faiss  # type: ignore
    _faiss_available = True
except ImportError:
    _faiss_available = False


def _embed(texts: list[str]) -> np.ndarray:
    """Get embeddings from Ollama (nomic-embed-text)."""
    import ollama as ollama_client
    embeddings = []
    for text in texts:
        resp = ollama_client.embeddings(model=settings.ollama_embed_model, prompt=text)
        embeddings.append(resp["embedding"])
    return np.array(embeddings, dtype=np.float32)


class SpeakerIndex:
    """
    In-memory FAISS index of speaker turn embeddings.

    Build once per meeting from the full transcript, then query
    with a chunk of text to retrieve the most relevant past context
    for each speaker.
    """

    def __init__(self):
        self._index = None
        self._texts: list[str] = []
        self._speakers: list[str] = []
        self._dim: int = 0

    def build(self, turns: list[TranscriptTurn]) -> None:
        """Embed all turns and build the FAISS index."""
        if not _faiss_available:
            log.warning("faiss not installed — speaker RAG disabled")
            return
        if not turns:
            return

        texts = [f"[{t.display_name}]: {t.text}" for t in turns]
        speakers = [t.display_name for t in turns]

        try:
            vecs = _embed(texts)
        except Exception as exc:
            log.warning("Embedding failed — speaker RAG disabled: %s", exc)
            return

        self._dim = vecs.shape[1]
        self._index = faiss.IndexFlatIP(self._dim)  # inner product (cosine after normalize)
        faiss.normalize_L2(vecs)
        self._index.add(vecs)
        self._texts = texts
        self._speakers = speakers
        log.info("SpeakerIndex built: %d turns, dim=%d", len(turns), self._dim)

    def query(self, text: str, top_k: int = 3) -> list[str]:
        """Return top_k most relevant speaker turns for a given query text."""
        if self._index is None or not self._texts:
            return []
        try:
            q = _embed([text])
            faiss.normalize_L2(q)
            _, indices = self._index.search(q, min(top_k, len(self._texts)))
            return [self._texts[i] for i in indices[0] if i >= 0]
        except Exception as exc:
            log.warning("RAG query failed: %s", exc)
            return []

    @property
    def is_ready(self) -> bool:
        return self._index is not None and len(self._texts) > 0
