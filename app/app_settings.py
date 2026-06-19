import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.config import settings

DEFAULT_CATALOG_AUTHOR_NAME = "Grocy Ultimate Lookup Bot"
DEFAULT_CATALOG_AUTHOR_EMAIL = "grocy-ultimate-lookup-bot@example.local"


class CommunityCatalogSettings(BaseModel):
    enabled: bool = False
    repository_url: str | None = None
    github_pat: str | None = None
    branch: str = "main"
    workdir: str = "/data/community-catalog-workdir"
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
    repository_url: str | None = None
    branch: str
    path_exists: bool
    is_git_repo: bool
    pending_changes: bool = False
    configured: bool = False


class CommunityCatalogSettingsResponse(BaseModel):
    enabled: bool
    repository_url: str | None
    branch: str
    export_images: bool
    auto_push: bool
    author_name: str | None
    author_email: str | None
    github_pat_set: bool


class CommunityCatalogSettingsUpdate(BaseModel):
    enabled: bool = False
    repository_url: str | None = None
    github_pat: str | None = None
    branch: str = "main"
    export_images: bool = False
    auto_push: bool = False
    author_name: str | None = None
    author_email: str | None = None


class CommunityCatalogDiff(BaseModel):
    configured: bool
    pending_changes: bool
    status: str
    files: list[str] = []


def default_community_catalog_settings() -> CommunityCatalogSettings:
    return CommunityCatalogSettings(
        enabled=settings.community_catalog_enabled,
        repository_url=settings.community_catalog_repository_url,
        github_pat=settings.community_catalog_github_pat,
        branch=settings.community_catalog_git_branch,
        workdir=settings.community_catalog_workdir,
        path=settings.community_catalog_path,
        export_images=settings.community_catalog_export_images,
        auto_commit=settings.community_catalog_auto_commit,
        auto_push=settings.community_catalog_auto_push,
        git_remote=settings.community_catalog_git_remote,
        git_branch=settings.community_catalog_git_branch,
        author_name=settings.community_catalog_author_name or DEFAULT_CATALOG_AUTHOR_NAME,
        author_email=settings.community_catalog_author_email or DEFAULT_CATALOG_AUTHOR_EMAIL,
    )


def public_community_catalog_settings(settings_value: CommunityCatalogSettings) -> CommunityCatalogSettingsResponse:
    return CommunityCatalogSettingsResponse(
        enabled=settings_value.enabled,
        repository_url=settings_value.repository_url,
        branch=settings_value.branch or settings_value.git_branch,
        export_images=settings_value.export_images,
        auto_push=settings_value.auto_push,
        author_name=settings_value.author_name,
        author_email=settings_value.author_email,
        github_pat_set=bool(settings_value.github_pat),
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

    def update_community_catalog(self, value: CommunityCatalogSettingsUpdate) -> CommunityCatalogSettings:
        current = self.get_community_catalog()
        github_pat = value.github_pat.strip() if value.github_pat else current.github_pat
        updated = current.model_copy(
            update={
                "enabled": value.enabled,
                "repository_url": value.repository_url.strip() if value.repository_url else None,
                "github_pat": github_pat,
                "branch": value.branch.strip() or "main",
                "git_branch": value.branch.strip() or "main",
                "export_images": value.export_images,
                "auto_commit": value.auto_push,
                "auto_push": value.auto_push,
                "author_name": value.author_name.strip() if value.author_name else DEFAULT_CATALOG_AUTHOR_NAME,
                "author_email": value.author_email.strip() if value.author_email else DEFAULT_CATALOG_AUTHOR_EMAIL,
                "path": current.workdir,
            }
        )
        return self.set_community_catalog(updated)

    def community_catalog_status(self) -> CommunityCatalogStatus:
        current = self.get_community_catalog()
        path = Path(current.workdir if current.repository_url else current.path)
        return CommunityCatalogStatus(
            path=str(path),
            repository_url=current.repository_url,
            branch=current.branch or current.git_branch,
            path_exists=path.exists(),
            is_git_repo=(path / ".git").exists(),
            pending_changes=self._community_catalog_has_pending_changes(path),
            configured=bool(current.repository_url),
        )

    @staticmethod
    def _community_catalog_has_pending_changes(path: Path) -> bool:
        if not (path / ".git").exists():
            return False
        import subprocess

        try:
            result = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return False
        return bool(result.stdout.strip())

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
