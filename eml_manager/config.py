import os
import pathlib
from dataclasses import dataclass, field
from typing import List

import yaml


def _config_dir() -> pathlib.Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return pathlib.Path(appdata) / "eml_manager"
    # Fallback for non-Windows dev environments.
    return pathlib.Path.home() / ".config" / "eml_manager"


def _data_dir() -> pathlib.Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return pathlib.Path(appdata) / "eml_manager"
    return pathlib.Path.home() / ".local" / "share" / "eml_manager"


def _log_dir() -> pathlib.Path:
    return _data_dir() / "logs"


def default_config_path() -> pathlib.Path:
    return _config_dir() / "config.yml"


@dataclass
class Config:
    watch_paths: List[str] = field(default_factory=list)
    archive_root: str = str(pathlib.Path.home() / "EmailArchive")
    duplicates_folder: str = "duplicates"
    db_path: str = str(_data_dir() / "eml_manager.db")
    dedupe_policy: str = "message_id,sha256"
    timezone: str = "UTC"
    filename_limit: int = 200
    stable_check_seconds: float = 3.0
    retry_count: int = 3
    log_path: str = str(_log_dir() / "eml-manager.log")
    log_level: str = "INFO"

    def save(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.__dict__, f, default_flow_style=False, allow_unicode=True)

    @classmethod
    def load(cls, path: pathlib.Path) -> "Config":
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)
