import datetime
import logging
import pathlib
import time

from .bundle import Bundle
from .config import Config
from .database import Database
from .normalizer import make_filename, make_folder_name, normalize_timestamp, strip_subject_prefixes
from .parser import parse_eml

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    pass


class Processor:
    def __init__(self, config: Config, db: Database, bundle: Bundle):
        self.config = config
        self.db = db
        self.bundle = bundle

    def process(self, file_path: pathlib.Path) -> dict:
        """Full pipeline: parse → dedupe → move → persist. Returns a result dict."""
        parsed_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            return self._process_inner(file_path, parsed_at)
        except Exception as exc:
            logger.error("Failed to process %s: %s", file_path, exc, exc_info=True)
            return {"status": "error", "error_message": str(exc), "path": str(file_path)}

    def _process_inner(self, file_path: pathlib.Path, parsed_at: str) -> dict:
        if not file_path.exists():
            raise ProcessingError(f"File not found: {file_path}")

        self._wait_stable(file_path)

        meta = parse_eml(file_path)

        existing = self.db.find_duplicate(meta["message_id"], meta["sha256"])
        if existing:
            logger.info("Duplicate: %s → matches id=%s", file_path.name, existing["id"])
            self._move_to_duplicates(file_path)
            return {"status": "duplicate", "original_id": existing["id"], "path": str(file_path)}

        timestamp = normalize_timestamp(meta["sent_dt"], self.config.timezone)
        pure_subject = strip_subject_prefixes(meta["subject"])
        dest_folder = self.bundle.emails_root / make_folder_name(pure_subject)
        dest_folder.mkdir(parents=True, exist_ok=True)

        existing_names = {p.name for p in dest_folder.glob("*.eml")}
        filename = make_filename(
            pure_subject,
            timestamp,
            meta["sender"],
            self.config.filename_limit,
            existing_names,
        )
        dest_path = dest_folder / filename

        file_path.replace(dest_path)

        row_id = self.db.insert(
            {
                "message_id": meta["message_id"],
                "sha256": meta["sha256"],
                "original_path": str(file_path),
                "stored_path": str(dest_path.relative_to(self.bundle.emails_root)),
                "filename": filename,
                "subject": meta["subject"],
                "pure_subject": pure_subject,
                "sender": meta["sender"],
                "sent_timestamp": timestamp,
                "parsed_at": parsed_at,
                "status": "processed",
                "error_message": None,
            }
        )
        logger.info("Processed %s → %s (id=%d)", file_path.name, dest_path, row_id)
        return {"status": "processed", "id": row_id, "path": str(dest_path), "filename": filename}

    def _wait_stable(self, path: pathlib.Path, poll: float = 0.5):
        """Block until file size is stable for stable_check_seconds, or timeout."""
        target = self.config.stable_check_seconds
        deadline = time.monotonic() + max(target * 4, 30)
        prev_size = -1
        stable_since: float = 0.0

        while time.monotonic() < deadline:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                raise ProcessingError(f"File disappeared: {path}")

            now = time.monotonic()
            if size == prev_size:
                if stable_since == 0.0:
                    stable_since = now
                elif now - stable_since >= target:
                    return
            else:
                stable_since = 0.0
                prev_size = size

            time.sleep(poll)

        logger.warning("Stability timeout for %s — processing anyway", path.name)

    def _move_to_duplicates(self, path: pathlib.Path):
        dup_dir = self.bundle.emails_root / self.config.duplicates_folder
        dup_dir.mkdir(parents=True, exist_ok=True)
        dest = dup_dir / path.name
        if dest.exists():
            import hashlib

            h = hashlib.md5(path.read_bytes()).hexdigest()[:8]
            dest = dup_dir / f"{path.stem}_{h}{path.suffix}"
        path.replace(dest)
