"""PII Masker — regex-based scrubber applied before any text is logged or stored."""

import re

# Patterns ordered from most specific to least
_PATTERNS: list[tuple[str, str]] = [
    # Email
    (r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[EMAIL]"),
    # Phone (various formats)
    (r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b", "[PHONE]"),
    # Credit card (16-digit groups)
    (r"\b(?:\d[ -]?){13,16}\b", "[CARD]"),
    # SSN
    (r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", "[SSN]"),
    # IPv4
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]"),
    # URLs (http/https)
    (r"https?://[^\s\"'>]+", "[URL]"),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), replacement)
             for pattern, replacement in _PATTERNS]


def mask_pii(text: str) -> str:
    """
    Replace common PII patterns (email, phone, SSN, card, IP, URL) with placeholders.
    Applied to text before it is written to logs or LangSmith traces.
    """
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text


def mask_turns(turns: list) -> list:
    """Return a copy of TranscriptTurn list with PII masked in .text fields (for logging)."""
    masked = []
    for turn in turns:
        masked.append(turn.model_copy(update={"text": mask_pii(turn.text)}))
    return masked
