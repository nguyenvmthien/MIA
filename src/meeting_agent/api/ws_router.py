"""
WebSocket endpoint for real-time meeting transcription.

Protocol (binary frames from client, JSON frames from server):
  Client → Server: raw PCM bytes (int16 LE, mono, 16 kHz)
  Server → Client: JSON object per transcribed segment:
    {
      "type": "transcript",
      "text": "...",
      "segment_index": 3,
      "duration_ms": 1240
    }
  On stream end, client sends the text "END" as a UTF-8 message.
  Server responds with:
    {"type": "done", "total_segments": N, "full_transcript": "..."}

Mount in main.py:
    from meeting_agent.api.ws_router import router as ws_router
    app.include_router(ws_router)

Endpoint:
    WS /ws/transcribe?language=vi&meeting_id=<optional>
"""

import json
import logging
import time

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from meeting_agent.pipeline.audio_buffer import AudioBuffer
from meeting_agent.pipeline.streaming_stt import transcribe_segment

log = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])

_SAMPLE_RATE = 16000


@router.websocket("/ws/transcribe")
async def ws_transcribe(
    websocket: WebSocket,
    language: str = "vi",
    meeting_id: str | None = None,
):
    """
    Real-time transcription WebSocket.

    The client streams raw PCM audio in binary frames.
    The server detects speech boundaries via Silero VAD, transcribes each
    segment with WhisperX, and returns partial transcript JSON objects.
    Send the string "END" to finalize and receive the full transcript.
    """
    await websocket.accept()
    log.info("WS /ws/transcribe connected: meeting_id=%s language=%s", meeting_id, language)

    buf = AudioBuffer(sample_rate=_SAMPLE_RATE, silence_ms=800)
    all_texts: list[str] = []
    segment_index = 0

    try:
        while True:
            data = await websocket.receive()

            # Handle close / END signal
            if "text" in data:
                text_msg = data["text"]
                if text_msg.strip().upper() == "END":
                    # Flush any remaining buffered audio
                    buf.flush_remaining()
                    for seg_np in buf.drain_segments():
                        text, seg_index, all_texts = await _process_segment(
                            websocket, seg_np, segment_index, all_texts, language
                        )
                        segment_index = seg_index

                    full = " ".join(all_texts).strip()
                    await websocket.send_json({
                        "type": "done",
                        "total_segments": segment_index,
                        "full_transcript": full,
                    })
                    log.info("WS session ended: %d segments, %d chars", segment_index, len(full))
                    break
                continue

            # Binary PCM frame
            if "bytes" in data:
                buf.push(data["bytes"])
                for seg_np in buf.drain_segments():
                    _, segment_index, all_texts = await _process_segment(
                        websocket, seg_np, segment_index, all_texts, language
                    )

    except WebSocketDisconnect:
        log.info("WS client disconnected: meeting_id=%s", meeting_id)
    except Exception as e:
        log.error("WS error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _process_segment(
    websocket: WebSocket,
    seg_np: np.ndarray,
    segment_index: int,
    all_texts: list[str],
    language: str,
) -> tuple[str, int, list[str]]:
    """Transcribe one segment and send result to client. Returns (text, new_index, updated_texts)."""
    import asyncio
    t0 = time.monotonic()
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, transcribe_segment, seg_np, language)
    duration_ms = int((time.monotonic() - t0) * 1000)

    if text:
        all_texts.append(text)
        await websocket.send_json({
            "type": "transcript",
            "text": text,
            "segment_index": segment_index,
            "duration_ms": duration_ms,
        })
        log.debug("Segment %d transcribed in %d ms: %s…", segment_index, duration_ms, text[:60])

    return text, segment_index + 1, all_texts
