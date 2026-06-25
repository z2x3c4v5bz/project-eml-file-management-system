import datetime
import pathlib

import pytest

from eml_manager.parser import decode_mime_words, extract_sender_name, parse_eml

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_parse_simple():
    result = parse_eml(FIXTURES / "simple.eml")
    assert result["subject"] == "Hello World"
    assert result["sender"] == "Alice Smith"
    assert result["message_id"] == "<abc123@example.com>"
    assert isinstance(result["sent_dt"], datetime.datetime)
    assert result["sent_dt"].year == 2026
    assert result["sha256"]


def test_parse_no_date_falls_back_to_mtime():
    result = parse_eml(FIXTURES / "no-date.eml")
    assert result["sent_dt"] is not None
    assert isinstance(result["sent_dt"], datetime.datetime)
    assert result["sent_dt"].tzinfo is not None


def test_parse_utf8_encoded_subject():
    result = parse_eml(FIXTURES / "encoded-utf8-subject.eml")
    # Decoded subject should be non-empty Unicode text (not raw encoded bytes)
    assert result["subject"]
    assert "=?" not in result["subject"]


def test_parse_display_name_sender():
    result = parse_eml(FIXTURES / "display-name-only.eml")
    assert result["sender"] == "John Doe"


def test_decode_mime_words_base64():
    encoded = "=?UTF-8?b?SGVsbG8gV29ybGQ=?="
    assert decode_mime_words(encoded) == "Hello World"


def test_decode_mime_words_plain():
    assert decode_mime_words("plain text") == "plain text"


def test_decode_mime_words_none():
    assert decode_mime_words(None) == ""


def test_extract_sender_display_name():
    assert extract_sender_name("Alice Smith <alice@example.com>") == "Alice Smith"


def test_extract_sender_local_part():
    assert extract_sender_name("alice@example.com") == "alice"


def test_extract_sender_bare_string():
    assert extract_sender_name("alice") == "alice"
