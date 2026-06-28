import datetime
import email
import email.policy
import hashlib
import pathlib
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

# Non-standard charset aliases emitted by some East Asian email clients that
# Python's codec system doesn't recognise under those exact names.
_CHARSET_ALIASES: dict = {
    # Simplified Chinese
    "gb_2312": "gb2312",
    "gb_2312-80": "gb2312",
    "chinese": "gb2312",
    "x-gb2312": "gb2312",
    "x-gbk": "gbk",
    "windows-936": "gbk",
    # Japanese
    "x-euc-jp": "euc_jp",
    "x-euc": "euc_jp",
    "x-sjis": "shift_jis",
    "shift-jis": "shift_jis",
    "windows-31j": "cp932",
    # Korean
    "x-euc-kr": "euc_kr",
    "ks_c_5601-1987": "euc_kr",
    "ks_c_5601_1987": "euc_kr",
    # Traditional Chinese
    "x-big5": "big5",
}


def decode_mime_words(header: Optional[str]) -> str:
    """RFC2047-decode an email header value to a plain Unicode string."""
    if not header:
        return ""
    parts = decode_header(header)
    chunks = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            cs = (charset or "utf-8").lower().strip()
            cs = _CHARSET_ALIASES.get(cs, cs)
            try:
                chunks.append(raw.decode(cs, errors="replace"))
            except (LookupError, TypeError):
                # Unknown charset — fall back to UTF-8 with replacement chars.
                chunks.append(raw.decode("utf-8", errors="replace"))
        else:
            chunks.append(raw)
    return "".join(chunks)


def has_attachments(msg) -> bool:
    """Return True if the parsed message carries at least one attachment.

    A part counts as an attachment when its Content-Disposition is "attachment",
    or when it advertises a filename (covers clients that omit the disposition
    header but still name the file). Inline-only parts without a filename — the
    plain-text/HTML alternatives of an ordinary email — are ignored.
    """
    if not msg.is_multipart():
        return False
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            return True
        if part.get_filename():
            return True
    return False


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
        "has_attachment": has_attachments(msg),
    }
