"""Bundle — a self-contained EML archive: a folder with archive.db and emails/."""
import datetime
import json
import pathlib

MARKER_FILENAME = ".emlarchive"
DB_FILENAME = "archive.db"
EMAILS_DIRNAME = "emails"


class Bundle:
    def __init__(self, path: pathlib.Path):
        self.path = path.resolve()
        self.emails_root = self.path / EMAILS_DIRNAME
        self.db_path = str(self.path / DB_FILENAME)
        self._marker = self.path / MARKER_FILENAME

    @property
    def name(self) -> str:
        return self.path.name

    def is_valid(self) -> bool:
        return self._marker.exists()

    def resolve(self, relative_path: str) -> pathlib.Path:
        return self.emails_root / relative_path

    @classmethod
    def create(cls, path: pathlib.Path) -> "Bundle":
        path.mkdir(parents=True, exist_ok=True)
        bundle = cls(path)
        bundle.emails_root.mkdir(exist_ok=True)
        bundle._marker.write_text(
            json.dumps({"version": 1, "created_at": datetime.datetime.utcnow().isoformat()}, indent=2),
            encoding="utf-8",
        )
        return bundle
