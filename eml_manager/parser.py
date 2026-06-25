import datetime
import email
import email.policy
import hashlib
import pathlib
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional


def decode_mime_words(header: Optional[str]) -> str:
    """RFC2047-decode an email header value to a plain Unicode string."""
    if not header:
        return ""
    parts = decode_header(header)
    chunks = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            chunks.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(raw)
    return "".join(chunks)


def extract_sender_name(from_header: str) -> str:
    """Return display name, or local-part of address, from a From header."""
    display, addr = parseaddr(from_header)
    if display:
        return display.strip()
    if addr and "@" in addr:
        return addr.split("@")[0]
    return addr or "unknown"


def parse_eml(file_path: pathlib.Path) -> dict:
    """
    Parse a .eml file and return a metadata dict with keys:
      subject, message_id, sender, sent_dt (datetime), sha256
    """
    raw = file_path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    msg = email.message_from_bytes(raw, policy=email.policy.compat32)

    subject = decode_mime_words(msg.get("Subject", ""))
    message_id: Optional[str] = (msg.get("Message-ID") or "").strip() or None
    sender = extract_sender_name(decode_mime_words(msg.get("From", "")))

    sent_dt: Optional[datetime.datetime] = None
    date_str = msg.get("Date")
    if date_str:
        try:
            sent_dt = parsedate_to_datetime(date_str)
        except Exception:
            pass

    if sent_dt is None:
        mtime = file_path.stat().st_mtime
        sent_dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)

    return {
        "subject": subject,
        "message_id": message_id,
        "sender": sender,
        "sent_dt": sent_dt,
        "sha256": sha256,
    }
