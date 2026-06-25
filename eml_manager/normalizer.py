import datetime
import re
from typing import Optional, Set

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE_RUN = re.compile(r"[\s_]+")
# Matches one or more leading reply/forward prefixes in any supported language.
_SUBJECT_PREFIX = re.compile(
    r"^(?:(?:re|fw|fwd)\s*:\s*|(?:回复|回覆|答复|转发|轉發)\s*[：:]\s*)+",
    re.IGNORECASE,
)


def normalize_timestamp(dt: datetime.datetime, tz_name: str = "UTC") -> str:
    """Return YYYYMMDDHHmmss in the configured timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    if tz_name and tz_name.upper() != "UTC":
        try:
            import zoneinfo

            dt = dt.astimezone(zoneinfo.ZoneInfo(tz_name))
        except Exception:
            dt = dt.astimezone(datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)

    return dt.strftime("%Y%m%d%H%M%S")


def normalize_text(text: str, limit: int = 200) -> str:
    """Strip illegal filesystem chars, collapse whitespace, and truncate."""
    text = _ILLEGAL.sub("", text)
    text = _SPACE_RUN.sub("_", text)
    text = text.strip("_. ")
    return text[:limit] if text else "no_subject"


def make_filename(
    timestamp: str,
    sender: str,
    existing: Optional[Set[str]] = None,
) -> str:
    """Produce a unique, filesystem-safe .eml filename."""
    safe_sender = normalize_text(sender, limit=50)
    base = f"{timestamp}_{safe_sender}"
    candidate = f"{base}.eml"

    if existing is None or candidate not in existing:
        return candidate

    for i in range(2, 100_000):
        candidate = f"{base}_{i}.eml"
        if candidate not in existing:
            return candidate

    import hashlib, time

    h = hashlib.md5(f"{base}{time.time()}".encode()).hexdigest()[:8]
    return f"{base}_{h}.eml"


def strip_subject_prefixes(subject: str) -> str:
    """Strip reply/forward prefixes (Re:, Fw:, 答复:, etc.) for folder grouping."""
    stripped = _SUBJECT_PREFIX.sub("", subject).strip()
    return stripped if stripped else subject.strip()


def make_folder_name(subject: str, limit: int = 100) -> str:
    return normalize_text(subject, limit=limit) or "no_subject"
