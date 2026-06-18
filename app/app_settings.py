import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.config import settings


class CommunityCatalogSettings(BaseModel):
    enabled: bool = False
    path: str = "/data/community-catalog"
    export_images: bool = False
    auto_commit: bool = False
    auto_push: bool = False
    git_remote: str = "origin"
    git_branch: str = "main"
    author_name: str | None = None
    author_email: str | None = None


class CommunityCatalogStatus(BaseModel):
    path: str
    path_exists: bool
    is_git_repo: bool


def default_community_catalog_settings() -> CommunityCatalogSettings:
    return CommunityCatalogSettings(
        enabled=settings.community_catalog_enabled,
        path=settings.community_catalog_path,
        export_images=settings.community_catalog_export_images,
        auto_commit=settings.community_catalog_auto_commit,
        auto_push=settings.community_catalog_auto_push,
        git_remote=settings.community_catalog_git_remote,
        git_branch=settings.community_catalog_git_branch,
        author_name=settings.community_catalog_author_name,
        author_email=settings.community_catalog_author_email,
    )


class AppSettingsStore:
    def __init__(
        self,
        path: str,
        *,
        community_catalog_defaults: CommunityCatalogSettings | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.community_catalog_defaults = community_catalog_defaults or default_community_catalog_settings()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_community_catalog(self) -> CommunityCatalogSettings:
        payload = self._get_json("community_catalog")
        if payload is None:
            return self.community_catalog_defaults
        merged = self.community_catalog_defaults.model_dump()
        merged.update(payload)
        return CommunityCatalogSettings.model_validate(merged)

    def set_community_catalog(self, value: CommunityCatalogSettings) -> CommunityCatalogSettings:
        self._set_json("community_catalog", value.model_dump(mode="json"))
        return self.get_community_catalog()

    def community_catalog_status(self) -> CommunityCatalogStatus:
        current = self.get_community_catalog()
        path = Path(current.path)
        return CommunityCatalogStatus(
            path=current.path,
            path_exists=path.exists(),
            is_git_repo=(path / ".git").exists(),
        )

    def _get_json(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def _set_json(self, key: str, value: dict) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value, sort_keys=True)),
            )
