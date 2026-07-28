"""Validated runtime configuration for the LLM Assistant RAG service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from dotenv import load_dotenv

_ENV_FILE = os.getenv("LLMASSISTANT_ENV_FILE", "").strip()
if _ENV_FILE:
    load_dotenv(_ENV_FILE, override=False)
else:
    load_dotenv(Path(__file__).with_name(".env"), override=False)


def _text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _integer(name: str, default: int) -> int:
    try:
        return int(_text(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _boolean(name: str, default: bool = False) -> bool:
    value = _text(name, "1" if default else "0").lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _prefix() -> str:
    value = _text("MOODLE_DB_PREFIX", "mdl_")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise RuntimeError("MOODLE_DB_PREFIX contains invalid characters")
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    dbtype: str
    host: str
    port: int
    name: str
    user: str
    password: str
    prefix: str

    @classmethod
    def from_environment(cls, require_password: bool = True) -> "DatabaseSettings":
        dbtype = _text("MOODLE_DB_TYPE", "pgsql").lower()
        aliases = {"postgres": "pgsql", "postgresql": "pgsql", "mysql": "mariadb"}
        dbtype = aliases.get(dbtype, dbtype)
        if dbtype not in {"pgsql", "mariadb"}:
            raise RuntimeError("MOODLE_DB_TYPE must be pgsql or mariadb")
        default_port = 5432 if dbtype == "pgsql" else 3306
        password = _text("MOODLE_DB_PASSWORD")
        if require_password and not password:
            raise RuntimeError("MOODLE_DB_PASSWORD is required")
        return cls(
            dbtype=dbtype,
            host=_text("MOODLE_DB_HOST", "db"),
            port=_integer("MOODLE_DB_PORT", default_port),
            name=_text("MOODLE_DB_NAME", "moodle"),
            user=_text("MOODLE_DB_USER", "moodle"),
            password=password,
            prefix=_prefix(),
        )

MOODLEDATA_PATH = _text("MOODLEDATA_PATH", "/var/www/moodledata/filedir")
CHROMA_DB_PATH = _text("CHROMA_DB_PATH", "/var/www/moodledata/chroma_db")
TARGET_COURSE_ID = _integer("TARGET_COURSE_ID", 0)
RESET_COLLECTION = _boolean("RESET_COLLECTION", False)
