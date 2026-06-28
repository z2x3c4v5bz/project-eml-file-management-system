import pathlib
import shutil

import pytest

from eml_manager.config import Config
from eml_manager.database import Database
from eml_manager.processor import Processor

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path):
    from eml_manager.bundle import Bundle
    cfg = Config(
        watch_paths=[str(tmp_path / "watch")],
        duplicates_folder="duplicates",
        stable_check_seconds=0.1,  # fast for tests
    )
    (tmp_path / "watch").mkdir()
    bundle = Bundle.create(tmp_path / "archive_bundle")
    db = Database(bundle.db_path, str(bundle.emails_root))
    processor = Processor(cfg, db, bundle)
    return cfg, db, processor, tmp_path, bundle


def _copy(src_name: str, dest: pathlib.Path) -> pathlib.Path:
    dest_file = dest / src_name
    shutil.copy(FIXTURES / src_name, dest_file)
    return dest_file


class TestProcessSimple:
    def test_file_moved_to_archive(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        result = proc.process(src)
        assert result["status"] == "processed"
        assert not src.exists(), "original should be moved"

    def test_db_record_created(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        proc.process(src)
        rows = db.recent(1)
        assert len(rows) == 1
        assert rows[0]["status"] == "processed"
        assert rows[0]["subject"] == "Hello World"
        assert rows[0]["sender"] == "Alice Smith"

    def test_archive_folder_named_after_subject(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        proc.process(src)
        subject_folders = list(bundle.emails_root.iterdir())
        assert any("Hello_World" in f.name for f in subject_folders)

    def test_filename_contains_timestamp_and_sender(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        result = proc.process(src)
        assert "20260624" in result["filename"]
        assert "Alice_Smith" in result["filename"]

    def test_stored_path_is_relative(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        proc.process(src)
        rows = db.recent(1)
        import pathlib
        assert not pathlib.PurePath(rows[0]["stored_path"]).is_absolute()


class TestDuplicateDetection:
    def test_same_file_twice_is_duplicate(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        proc.process(src1)

        src2 = tmp / "watch" / "simple_copy.eml"
        shutil.copy(FIXTURES / "simple.eml", src2)
        result2 = proc.process(src2)
        assert result2["status"] == "duplicate"

    def test_duplicate_goes_to_duplicates_folder(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        proc.process(src1)

        src2 = tmp / "watch" / "simple_copy.eml"
        shutil.copy(FIXTURES / "simple.eml", src2)
        proc.process(src2)

        dup_folder = bundle.emails_root / cfg.duplicates_folder
        assert dup_folder.exists()
        assert any(dup_folder.iterdir())

    def test_duplicate_does_not_create_db_record(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        proc.process(src1)
        assert len(db.recent(10)) == 1

        src2 = tmp / "watch" / "simple_copy.eml"
        shutil.copy(FIXTURES / "simple.eml", src2)
        proc.process(src2)
        assert len(db.recent(10)) == 1  # still only one record


class TestAutoTagBySubject:
    def _write_eml(self, dest: pathlib.Path, subject: str, msg_id: str, body: str) -> pathlib.Path:
        dest.write_text(
            "From: Carol <carol@example.com>\n"
            "To: Dave <dave@example.com>\n"
            f"Subject: {subject}\n"
            "Date: Tue, 25 Jun 2026 09:00:00 +0000\n"
            f"Message-ID: <{msg_id}>\n"
            "MIME-Version: 1.0\n"
            "Content-Type: text/plain; charset=UTF-8\n"
            f"\n{body}\n",
            encoding="utf-8",
        )
        return dest

    def test_new_email_inherits_tags_from_same_subject(self, env):
        cfg, db, proc, tmp, bundle = env
        # First email of the conversation, tagged by the user.
        src1 = _copy("simple.eml", tmp / "watch")
        res1 = proc.process(src1)
        db.update_tags(res1["id"], "finance, urgent")

        # A different email with the same subject is added → inherits the tags.
        src2 = self._write_eml(tmp / "watch" / "reply.eml", "Re: Hello World", "second@x", "Another one")
        res2 = proc.process(src2)
        row = next(r for r in db.recent(10) if r["id"] == res2["id"])
        assert row["tags"] == "finance, urgent"

    def test_no_tags_when_subject_differs(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        res1 = proc.process(src1)
        db.update_tags(res1["id"], "finance")

        src2 = self._write_eml(tmp / "watch" / "other.eml", "Different Topic", "second@x", "Body")
        res2 = proc.process(src2)
        row = next(r for r in db.recent(10) if r["id"] == res2["id"])
        assert not row["tags"]

    def test_no_tags_when_match_is_untagged(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        proc.process(src1)  # not tagged

        src2 = self._write_eml(tmp / "watch" / "reply.eml", "Re: Hello World", "second@x", "Another")
        res2 = proc.process(src2)
        row = next(r for r in db.recent(10) if r["id"] == res2["id"])
        assert not row["tags"]


class TestAttachments:
    def test_attachment_flag_stored(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("with-attachment.eml", tmp / "watch")
        proc.process(src)
        rows = db.recent(1)
        assert rows[0]["has_attachment"] == 1

    def test_no_attachment_flag_zero(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("simple.eml", tmp / "watch")
        proc.process(src)
        rows = db.recent(1)
        assert rows[0]["has_attachment"] == 0

    def test_backfill_recovers_flag_for_legacy_rows(self, env):
        cfg, db, proc, tmp, bundle = env
        # Process a real attachment email, then simulate a legacy row by clearing
        # its flag to 0 as if it were imported before the column existed.
        src = _copy("with-attachment.eml", tmp / "watch")
        res = proc.process(src)
        conn = db._conn()
        conn.execute("UPDATE messages SET has_attachment = 0 WHERE id = ?", (res["id"],))
        conn.commit()
        assert db.recent(1)[0]["has_attachment"] == 0

        changed = db.backfill_attachment_flags()
        assert changed == 1
        assert db.recent(1)[0]["has_attachment"] == 1


class TestEdgeCases:
    def test_missing_date_header(self, env):
        cfg, db, proc, tmp, bundle = env
        src = _copy("no-date.eml", tmp / "watch")
        result = proc.process(src)
        assert result["status"] == "processed"
        rows = db.recent(1)
        assert rows[0]["sent_timestamp"]  # must have a fallback timestamp

    def test_nonexistent_file_returns_error(self, env):
        cfg, db, proc, tmp, bundle = env
        result = proc.process(tmp / "watch" / "ghost.eml")
        assert result["status"] == "error"

    def test_two_different_files_both_processed(self, env):
        cfg, db, proc, tmp, bundle = env
        src1 = _copy("simple.eml", tmp / "watch")
        src2 = _copy("no-date.eml", tmp / "watch")
        proc.process(src1)
        proc.process(src2)
        assert len(db.recent(10)) == 2
