import pytest

from eml_manager.database import Database
from eml_manager.normalizer import strip_subject_prefixes


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def _record(**overrides) -> dict:
    base = {
        "message_id": "<test@example.com>",
        "sha256": "deadbeef" * 8,
        "original_path": "/tmp/original.eml",
        "stored_path": "Hello_World/test.eml",
        "filename": "Test_Subject_20260624143055_alice.eml",
        "subject": "Test Subject",
        "sender": "alice",
        "sent_timestamp": "20260624143055",
        "parsed_at": "2026-06-24T14:30:55Z",
        "status": "processed",
        "error_message": None,
    }
    base.update(overrides)
    if "pure_subject" not in overrides:
        base["pure_subject"] = strip_subject_prefixes(base.get("subject") or "")
    return base


class TestInsertAndRecent:
    def test_insert_returns_id(self, db):
        row_id = db.insert(_record())
        assert isinstance(row_id, int) and row_id > 0

    def test_recent_returns_row(self, db):
        db.insert(_record())
        rows = db.recent(10)
        assert len(rows) == 1
        assert rows[0]["subject"] == "Test Subject"

    def test_recent_limit(self, db):
        for i in range(5):
            db.insert(_record(message_id=f"<msg{i}@x.com>", sha256=f"{'x' * 56}{i:08d}"))
        assert len(db.recent(3)) == 3


class TestDuplicateDetection:
    def test_find_by_message_id(self, db):
        db.insert(_record())
        dup = db.find_duplicate("<test@example.com>", "other-hash")
        assert dup is not None
        assert dup["subject"] == "Test Subject"

    def test_find_by_sha256(self, db):
        db.insert(_record(message_id=None))
        dup = db.find_duplicate(None, "deadbeef" * 8)
        assert dup is not None

    def test_no_match(self, db):
        db.insert(_record())
        assert db.find_duplicate("<other@x.com>", "totally-different") is None

    def test_message_id_none_skips_msg_lookup(self, db):
        db.insert(_record())
        # Passing None for message_id should not raise; falls through to sha256 check
        result = db.find_duplicate(None, "no-match-sha256")
        assert result is None


class TestSearch:
    def test_keyword_subject(self, db):
        db.insert(_record())
        assert len(db.search(keyword="Test Subject")) == 1
        assert len(db.search(keyword="nonexistent")) == 0

    def test_keyword_sender(self, db):
        db.insert(_record())
        assert len(db.search(keyword="alice")) == 1

    def test_keyword_searches_tags(self, db):
        row_id = db.insert(_record())
        db.update_tags(row_id, "invoice, urgent")
        assert len(db.search(keyword="invoice")) == 1
        assert len(db.search(keyword="urgent")) == 1
        assert len(db.search(keyword="nope")) == 0

    def test_mail_type_re(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Re: Hello"))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, subject="Hello"))
        assert len(db.search(mail_type="Re")) == 1

    def test_mail_type_fw(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="FW: Meeting"))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, subject="Meeting"))
        assert len(db.search(mail_type="Fw")) == 1

    def test_subject_filter(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Alpha"))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, subject="Beta"))
        assert len(db.search(subject="alp")) == 1

    def test_sender_filter(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, sender="bob"))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, sender="carol"))
        assert len(db.search(sender="bob")) == 1

    def test_tags_filter(self, db):
        row_id = db.insert(_record())
        db.update_tags(row_id, "invoice")
        assert len(db.search(tags="invoice")) == 1
        assert len(db.search(tags="other")) == 0

    def test_has_attachment_filter(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, has_attachment=1))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, has_attachment=0))
        assert len(db.search(has_attachment="yes")) == 1
        assert len(db.search(has_attachment="no")) == 1
        assert len(db.search(has_attachment="")) == 2  # no filter → all rows

    def test_has_attachment_defaults_to_zero(self, db):
        # A record inserted without the column reads back as 0 (no attachment).
        db.insert(_record())
        assert db.recent(1)[0]["has_attachment"] == 0

    def test_date_range(self, db):
        db.insert(_record())
        assert len(db.search(start_date="20260624000000", end_date="20260624235959")) == 1
        assert len(db.search(start_date="20260625000000")) == 0

    def test_date_range_yyyymmdd_input(self, db):
        # User enters 8-char YYYYMMDD; end_date must be padded to include the full day.
        db.insert(_record())
        assert len(db.search(start_date="20260624", end_date="20260624")) == 1
        assert len(db.search(start_date="20260624", end_date="20260623")) == 0
        assert len(db.search(start_date="20260625", end_date="20260625")) == 0

    def test_added_date_range(self, db):
        # parsed_at default is 2026-06-24T14:30:55Z
        db.insert(_record())
        assert len(db.search(added_start="2026-06-24T00:00:00Z", added_end="2026-06-24T23:59:59Z")) == 1
        assert len(db.search(added_start="2026-06-25T00:00:00Z")) == 0
        assert len(db.search(added_end="2026-06-23T23:59:59Z")) == 0

    def test_added_date_range_independent_of_sent(self, db):
        # Sent in January but added in June: only the Added filter should match June.
        db.insert(_record(sent_timestamp="20260101000000", parsed_at="2026-06-24T14:30:55Z"))
        assert len(db.search(added_start="2026-06-24T00:00:00Z", added_end="2026-06-24T23:59:59Z")) == 1
        assert len(db.search(start_date="20260624000000")) == 0  # nothing sent on the 24th

    def test_empty_filter_returns_all(self, db):
        for i in range(3):
            db.insert(_record(message_id=f"<m{i}@x.com>", sha256=f"{'a' * 56}{i:08d}"))
        assert len(db.search()) == 3

    def test_sort_order(self, db):
        # "Re: Zebra" and "Re: Apple" strip to "Zebra" and "Apple" for sorting
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Re: Zebra", sent_timestamp="20260101000000"))
        db.insert(_record(message_id="<b@x>", sha256="b" * 64, subject="Apple", sent_timestamp="20260201000000"))
        db.insert(_record(message_id="<c@x>", sha256="c" * 64, subject="Re: Apple", sent_timestamp="20260101000000"))
        rows = db.recent(10)
        # Both "Apple" rows come first (pure_subject="Apple"), then "Zebra"
        assert rows[0]["pure_subject"] == "Apple"
        assert rows[1]["pure_subject"] == "Apple"
        # Newest date sorts first within the same pure_subject (DESC)
        assert rows[0]["sent_timestamp"] > rows[1]["sent_timestamp"]
        assert rows[2]["pure_subject"] == "Zebra"


class TestFindTagsForSubject:
    def test_returns_tags_of_matching_pure_subject(self, db):
        row_id = db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Invoice"))
        db.update_tags(row_id, "finance, urgent")
        assert db.find_tags_for_subject("Invoice") == "finance, urgent"

    def test_matches_across_reply_prefix(self, db):
        # "Re: Invoice" strips to pure_subject "Invoice", so it matches a plain "Invoice".
        row_id = db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Re: Invoice"))
        db.update_tags(row_id, "finance")
        assert db.find_tags_for_subject("Invoice") == "finance"

    def test_returns_none_when_no_tags(self, db):
        db.insert(_record(message_id="<a@x>", sha256="a" * 64, subject="Invoice"))
        assert db.find_tags_for_subject("Invoice") is None

    def test_returns_none_for_unknown_subject(self, db):
        assert db.find_tags_for_subject("Nonexistent") is None

    def test_empty_subject_returns_none(self, db):
        assert db.find_tags_for_subject("") is None


class TestAttachmentMigration:
    def _make_legacy_db(self, path):
        """Create a messages table that predates the has_attachment column."""
        import sqlite3
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " message_id TEXT, sha256 TEXT NOT NULL, original_path TEXT,"
            " stored_path TEXT NOT NULL, filename TEXT NOT NULL, subject TEXT,"
            " pure_subject TEXT, sender TEXT, sent_timestamp TEXT,"
            " parsed_at TEXT NOT NULL, status TEXT NOT NULL, error_message TEXT, tags TEXT)"
        )
        conn.execute(
            "INSERT INTO messages (sha256, stored_path, filename, subject, parsed_at, status)"
            " VALUES ('deadbeef', 'Old/old.eml', 'old.eml', 'Old Mail', '2026-06-24T00:00:00Z', 'processed')"
        )
        conn.commit()
        conn.close()

    def test_legacy_db_gains_column_with_zero_default(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        self._make_legacy_db(db_path)
        db = Database(str(db_path))  # opening runs the migration
        rows = db.recent(10)
        assert len(rows) == 1
        assert rows[0]["has_attachment"] == 0
        # The new filter is usable on the upgraded database.
        assert len(db.search(has_attachment="no")) == 1
        assert len(db.search(has_attachment="yes")) == 0


class TestIntegrity:
    def test_integrity_check_passes(self, db):
        db.insert(_record())
        assert db.check_integrity() is True
