import pathlib
import sqlite3
import threading
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id       TEXT,
    sha256           TEXT NOT NULL,
    original_path    TEXT,
    stored_path      TEXT NOT NULL,
    filename         TEXT NOT NULL,
    subject          TEXT,
    pure_subject     TEXT,
    sender           TEXT,
    sent_timestamp   TEXT,
    parsed_at        TEXT NOT NULL,
    status           TEXT NOT NULL,
    error_message    TEXT,
    tags             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_msgid   ON messages(message_id) WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_sha256  ON messages(sha256);
CREATE        INDEX IF NOT EXISTS idx_msg_subject ON messages(subject);
CREATE        INDEX IF NOT EXISTS idx_msg_sender  ON messages(sender);
CREATE        INDEX IF NOT EXISTS idx_msg_ts      ON messages(sent_timestamp);
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, db_path: str, emails_root: Optional[str] = None, tz_name: str = "UTC"):
        self._path = db_path
        self._emails_root = emails_root
        self._tz_name = tz_name
        self._local = threading.local()
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init(self):
        conn = self._conn()
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        conn.commit()
        self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        from .normalizer import strip_subject_prefixes
        existing = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        if "tags" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN tags TEXT")
        if "pure_subject" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN pure_subject TEXT")
            rows = conn.execute(
                "SELECT id, subject FROM messages WHERE subject IS NOT NULL"
            ).fetchall()
            for row_id, subj in rows:
                conn.execute(
                    "UPDATE messages SET pure_subject = ? WHERE id = ?",
                    (strip_subject_prefixes(subj), row_id),
                )
        # Index is created here (not in _SCHEMA) so it is always applied after the
        # column exists, whether this is a fresh DB or an upgraded one.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_msg_pure_subject ON messages(pure_subject)"
        )
        conn.commit()
        self._migrate_timestamps_to_utc(conn)
        # Convert absolute stored_path values (from pre-refactor databases) to paths
        # relative to the bundle's emails/ root. Only runs when an emails_root is set
        # and at least one stored_path is still absolute.
        if self._emails_root:
            emails_root = pathlib.PurePath(self._emails_root)
            rows = conn.execute(
                "SELECT id, stored_path FROM messages WHERE stored_path IS NOT NULL"
            ).fetchall()
            needs_migration = any(
                pathlib.PurePath(r[1]).is_absolute() for r in rows if r[1]
            )
            if needs_migration:
                for row_id, path in rows:
                    if not path:
                        continue
                    p = pathlib.PurePath(path)
                    if not p.is_absolute():
                        continue
                    try:
                        rel = p.relative_to(emails_root)
                    except ValueError:
                        continue
                    conn.execute(
                        "UPDATE messages SET stored_path = ? WHERE id = ?",
                        (str(rel), row_id),
                    )
                conn.commit()

    def _migrate_timestamps_to_utc(self, conn: sqlite3.Connection):
        """One-time migration: convert stored sent_timestamp values from the previously
        configured timezone to UTC. Skipped on subsequent runs via a metadata flag."""
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'timestamp_utc_migrated'"
        ).fetchone()
        if row:
            return

        if self._tz_name and self._tz_name.upper() != "UTC":
            import datetime
            import zoneinfo
            try:
                tz = zoneinfo.ZoneInfo(self._tz_name)
            except Exception:
                tz = datetime.timezone.utc

            rows = conn.execute(
                "SELECT id, sent_timestamp FROM messages WHERE sent_timestamp IS NOT NULL"
            ).fetchall()
            for row_id, ts in rows:
                if not (ts and len(ts) == 14 and ts.isdigit()):
                    continue
                try:
                    dt = datetime.datetime(
                        int(ts[:4]), int(ts[4:6]), int(ts[6:8]),
                        int(ts[8:10]), int(ts[10:12]), int(ts[12:14]),
                        tzinfo=tz,
                    )
                    utc_ts = dt.astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
                    conn.execute(
                        "UPDATE messages SET sent_timestamp = ? WHERE id = ?",
                        (utc_ts, row_id),
                    )
                except (ValueError, Exception):
                    pass
            conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('timestamp_utc_migrated', '1')"
        )
        conn.commit()

    # --- duplicate detection ---

    def find_duplicate(self, message_id: Optional[str], sha256: str) -> Optional[Dict]:
        conn = self._conn()
        if message_id:
            row = conn.execute(
                "SELECT * FROM messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            if row:
                return dict(row)
        row = conn.execute(
            "SELECT * FROM messages WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return dict(row) if row else None

    # --- writes ---

    def insert(self, record: Dict[str, Any]) -> int:
        conn = self._conn()
        cols = list(record.keys())
        sql = f"INSERT INTO messages ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        cur = conn.execute(sql, [record[c] for c in cols])
        conn.commit()
        return cur.lastrowid

    def update_status(self, row_id: int, status: str, error_message: Optional[str] = None):
        conn = self._conn()
        conn.execute(
            "UPDATE messages SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, row_id),
        )
        conn.commit()

    def update_tags(self, row_id: int, tags: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE messages SET tags = ? WHERE id = ?",
            (tags.strip() or None, row_id),
        )
        conn.commit()

    def delete(self, row_ids: list[int]) -> None:
        conn = self._conn()
        placeholders = ",".join("?" * len(row_ids))
        conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", row_ids)
        conn.commit()

    def get_all_tags(self) -> list[str]:
        """Return a sorted deduplicated list of every individual tag in the database."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT tags FROM messages WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()
        tag_set: set[str] = set()
        for row in rows:
            for t in row[0].split(","):
                t = t.strip()
                if t:
                    tag_set.add(t)
        return sorted(tag_set, key=str.lower)

    # --- reads ---

    def recent(self, limit: int = 100) -> List[Dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM messages"
            " ORDER BY pure_subject COLLATE NOCASE ASC, sent_timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search(
        self,
        keyword: str = "",
        mail_type: str = "",
        subject: str = "",
        sender: str = "",
        tags: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict]:
        conditions: List[str] = []
        params: List[Any] = []
        if keyword:
            conditions.append("(subject LIKE ? OR sender LIKE ? OR tags LIKE ?)")
            params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
        if mail_type == "Re":
            re_pats = ["Re:%", "RE:%", "re:%", "回复:%", "回覆:%", "答复:%"]
            conditions.append("(" + " OR ".join("subject LIKE ?" for _ in re_pats) + ")")
            params += re_pats
        elif mail_type == "Fw":
            fw_pats = ["Fw:%", "FW:%", "fw:%", "Fwd:%", "FWD:%", "转发:%", "轉發:%"]
            conditions.append("(" + " OR ".join("subject LIKE ?" for _ in fw_pats) + ")")
            params += fw_pats
        if subject:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject}%")
        if sender:
            conditions.append("sender LIKE ?")
            params.append(f"%{sender}%")
        if tags:
            conditions.append("tags LIKE ?")
            params.append(f"%{tags}%")
        if start_date:
            conditions.append("sent_timestamp >= ?")
            params.append(start_date)
        if end_date:
            # Pad a bare YYYYMMDD to YYYYMMDD235959 so the full end day is included.
            if len(end_date) == 8 and end_date.isdigit():
                end_date = end_date + "235959"
            conditions.append("sent_timestamp <= ?")
            params.append(end_date)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            f"SELECT * FROM messages {where} "
            f"ORDER BY pure_subject COLLATE NOCASE ASC, sent_timestamp DESC LIMIT ? OFFSET ?"
        )
        params += [limit, offset]
        conn = self._conn()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def check_integrity(self) -> bool:
        result = self._conn().execute("PRAGMA integrity_check").fetchone()
        return result[0] == "ok"
