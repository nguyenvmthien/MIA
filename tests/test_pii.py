"""Tests for PII masker."""


from meeting_agent.pipeline.pii import mask_pii, mask_turns
from meeting_agent.schemas.transcript import TranscriptTurn


def test_mask_email():
    assert mask_pii("Contact alice@example.com for details") == "Contact [EMAIL] for details"


def test_mask_phone_us():
    assert "[PHONE]" in mask_pii("Call me at 555-867-5309")


def test_mask_phone_international():
    assert "[PHONE]" in mask_pii("Reach me at +1 (800) 555-1234")


def test_mask_ssn():
    assert "[SSN]" in mask_pii("SSN is 123-45-6789")


def test_mask_url():
    assert "[URL]" in mask_pii("See https://internal.corp.com/report")


def test_mask_ip():
    assert "[IP]" in mask_pii("Server at 192.168.1.100")


def test_mask_multiple_in_one_string():
    text = "Email alice@example.com or call 555-867-5309"
    result = mask_pii(text)
    assert "[EMAIL]" in result
    assert "[PHONE]" in result
    assert "alice@example.com" not in result


def test_mask_clean_text_unchanged():
    text = "Alice will send the report by Friday"
    assert mask_pii(text) == text


def test_mask_turns():
    turns = [
        TranscriptTurn(turn_id="t1", speaker_id="S0", start_ms=0, end_ms=1000,
                       text="Email alice@example.com please"),
        TranscriptTurn(turn_id="t2", speaker_id="S1", start_ms=1000, end_ms=2000,
                       text="Call 555-867-5309"),
    ]
    masked = mask_turns(turns)
    assert "[EMAIL]" in masked[0].text
    assert "[PHONE]" in masked[1].text
    # Originals unchanged
    assert turns[0].text == "Email alice@example.com please"
