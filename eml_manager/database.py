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
"""


class Database:
    def __init__(self, db_path: str):
        self._path = db_path
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

    def rewrite_paths(self, old_root: str, new_root: str) -> int:
        """Replace old_root prefix with new_root in all stored_path values. Returns count updated."""
        old = pathlib.PurePath(old_root)
        new = pathlib.PurePath(new_root)
        conn = self._conn()
        rows = conn.execute("SELECT id, stored_path FROM messages").fetchall()
        updated = 0
        for row_id, path in rows:
            if not path:
                continue
            try:
                rel = pathlib.PurePath(path).relative_to(old)
                conn.execute(
                    "UPDATE messages SET stored_path = ? WHERE id = ?",
                    (str(new / rel), row_id),
                )
                updated += 1
            except ValueError:
                pass
        conn.commit()
        return updated

    def replace_file_and_reinit(self, source_path: str) -> None:
        """Replace the database file with source_path and reinitialise the connection."""
        import shutil
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
        shutil.copy2(source_path, self._path)
        self._init()

    def check_integrity(self) -> bool:
        result = self._conn().execute("PRAGMA integrity_check").fetchone()
        return result[0] == "ok"
