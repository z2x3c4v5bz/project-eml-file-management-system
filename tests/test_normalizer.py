import datetime

import pytest

from eml_manager.normalizer import make_filename, make_folder_name, normalize_text, normalize_timestamp, strip_subject_prefixes


def _utc(year, month, day, hour=0, minute=0, second=0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc)


class TestNormalizeTimestamp:
    def test_basic_utc(self):
        dt = _utc(2026, 6, 24, 14, 30, 55)
        assert normalize_timestamp(dt, "UTC") == "20260624143055"

    def test_naive_treated_as_utc(self):
        dt = datetime.datetime(2026, 6, 24, 14, 30, 55)  # no tzinfo
        assert normalize_timestamp(dt, "UTC") == "20260624143055"

    def test_offset_aware_converted(self):
        tz_plus8 = datetime.timezone(datetime.timedelta(hours=8))
        dt = datetime.datetime(2026, 6, 25, 9, 15, 0, tzinfo=tz_plus8)
        # UTC equivalent is 01:15:00 on the same day
        assert normalize_timestamp(dt, "UTC") == "20260625011500"


class TestNormalizeText:
    def test_strips_illegal_chars(self):
        result = normalize_text("hello/world:test<>?")
        for ch in r'/<>:*?"\\|':
            assert ch not in result

    def test_collapses_whitespace(self):
        assert normalize_text("Hello   World") == "Hello_World"

    def test_length_limit(self):
        assert len(normalize_text("a" * 300, limit=200)) <= 200

    def test_empty_becomes_no_subject(self):
        assert normalize_text("") == "no_subject"

    def test_strips_leading_trailing_underscores(self):
        result = normalize_text("  _hello_ ")
        assert not result.startswith("_")
        assert not result.endswith("_")


class TestMakeFilename:
    def test_basic(self):
        name = make_filename("Hello World", "20260624143055", "alice")
        assert name == "Hello_World_20260624143055_alice.eml"

    def test_conflict_appends_counter(self):
        existing = {"Hello_World_20260624143055_alice.eml"}
        name = make_filename("Hello World", "20260624143055", "alice", existing=existing)
        assert name != "Hello_World_20260624143055_alice.eml"
        assert name.endswith(".eml")

    def test_no_existing_set(self):
        name = make_filename("Subject", "20260624143055", "bob", existing=None)
        assert name.endswith(".eml")

    def test_illegal_chars_in_subject(self):
        name = make_filename("Re: Project — Status <Q2>", "20260624143055", "alice")
        for ch in r'/<>:*?"\\|':
            assert ch not in name


class TestMakeFolderName:
    def test_basic(self):
        assert make_folder_name("Project Planning") == "Project_Planning"

    def test_empty(self):
        assert make_folder_name("") == "no_subject"


class TestStripSubjectPrefixes:
    def test_re_prefix(self):
        assert strip_subject_prefixes("Re: Project Planning") == "Project Planning"

    def test_re_uppercase(self):
        assert strip_subject_prefixes("RE: Project Planning") == "Project Planning"

    def test_fw_prefix(self):
        assert strip_subject_prefixes("FW: Project Planning") == "Project Planning"

    def test_fwd_prefix(self):
        assert strip_subject_prefixes("Fwd: Project Planning") == "Project Planning"

    def test_nested_prefixes(self):
        assert strip_subject_prefixes("Re: Re: FW: Project Planning") == "Project Planning"

    def test_chinese_reply(self):
        assert strip_subject_prefixes("答复: Project Planning") == "Project Planning"

    def test_chinese_forward(self):
        assert strip_subject_prefixes("转发: Project Planning") == "Project Planning"

    def test_traditional_chinese_reply(self):
        assert strip_subject_prefixes("回覆: Project Planning") == "Project Planning"

    def test_no_prefix_unchanged(self):
        assert strip_subject_prefixes("Project Planning") == "Project Planning"

    def test_prefix_only_falls_back(self):
        assert strip_subject_prefixes("Re:") == "Re:"
