import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings
from app.models import LookupResult
from app.normalization import normalize_product_name


class AgentSearchStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_search_jobs (
                    barcode TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result_payload TEXT,
                    fallback_payload TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(agent_search_jobs)")}
            if "fallback_payload" not in columns:
                db.execute("ALTER TABLE agent_search_jobs ADD COLUMN fallback_payload TEXT")
            db.execute(
                """
                UPDATE agent_search_jobs
                SET status = 'queued', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                """
            )

    def get_status(self, barcode: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM agent_search_jobs WHERE barcode = ?", (barcode,)).fetchone()
        if row is None:
            return None
        return {
            "barcode": row["barcode"],
            "status": row["status"],
            "result": json.loads(row["result_payload"]) if row["result_payload"] else None,
            "fallback": json.loads(row["fallback_payload"]) if row["fallback_payload"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_result(self, barcode: str) -> LookupResult | None:
        status = self.get_status(barcode)
        if status is None or status["status"] != "completed" or status["result"] is None:
            return None
        return LookupResult.model_validate(status["result"])

    def queue(self, barcode: str, fallback_result: LookupResult | None = None) -> bool:
        fallback_payload = (
            json.dumps(fallback_result.model_dump(mode="json")) if fallback_result is not None else None
        )
        with self._connect() as db:
            existing = db.execute(
                "SELECT status FROM agent_search_jobs WHERE barcode = ?",
                (barcode,),
            ).fetchone()
            if existing is not None and existing["status"] in {"queued", "running", "completed"}:
                if fallback_payload is not None:
                    db.execute(
                        """
                        UPDATE agent_search_jobs
                        SET fallback_payload = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE barcode = ?
                        """,
                        (fallback_payload, barcode),
                    )
                return False
            db.execute(
                """
                INSERT INTO agent_search_jobs (barcode, status, result_payload, fallback_payload, error)
                VALUES (?, 'queued', NULL, ?, NULL)
                ON CONFLICT(barcode) DO UPDATE SET
                    status = 'queued',
                    result_payload = NULL,
                    fallback_payload = excluded.fallback_payload,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (barcode, fallback_payload),
            )
        return True

    def mark_running(self, barcode: str) -> None:
        self._update(barcode, "running")

    def mark_completed(self, barcode: str, result: LookupResult) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE agent_search_jobs
                SET status = 'completed', result_payload = ?, error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE barcode = ?
                """,
                (json.dumps(result.model_dump(mode="json")), barcode),
            )

    def mark_not_found(self, barcode: str) -> None:
        self._update(barcode, "not_found")

    def mark_failed(self, barcode: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE agent_search_jobs
                SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE barcode = ?
                """,
                (error[:2000], barcode),
            )

    def delete(self, barcode: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM agent_search_jobs WHERE barcode = ?", (barcode,))
            return cursor.rowcount > 0

    def _update(self, barcode: str, status: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE agent_search_jobs
                SET status = ?, error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE barcode = ?
                """,
                (status, barcode),
            )


class AgentSearchManager:
    def __init__(self, store: AgentSearchStore | None = None) -> None:
        self.store = store or AgentSearchStore(settings.agent_search_path)
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, barcode: str, fallback_result: LookupResult | None = None) -> bool:
        if not settings.enable_agent_search:
            return False
        auth_path = Path(settings.agent_search_auth_path)
        if not auth_path.exists() or shutil.which("codex") is None:
            return False
        existing = self.store.get_status(barcode)
        queued = self.store.queue(barcode, fallback_result=fallback_result)
        recovering_queued_job = existing is not None and existing["status"] == "queued"
        if queued or (recovering_queued_job and barcode not in self._tasks):
            self._tasks[barcode] = asyncio.create_task(self._run(barcode))
        return queued

    async def _run(self, barcode: str) -> None:
        self.store.mark_running(barcode)
        try:
            status = self.store.get_status(barcode)
            fallback = LookupResult.model_validate(status["fallback"]) if status and status["fallback"] else None
            result = await run_codex_product_search(barcode, fallback_result=fallback)
            if result is None:
                self.store.mark_not_found(barcode)
            else:
                self.store.mark_completed(barcode, result)
        except Exception as exc:
            self.store.mark_failed(barcode, str(exc))
        finally:
            self._tasks.pop(barcode, None)


async def run_codex_product_search(
    barcode: str,
    fallback_result: LookupResult | None = None,
) -> LookupResult | None:
    auth_path = Path(settings.agent_search_auth_path)
    with tempfile.TemporaryDirectory(prefix="grocy-agent-", dir="/data") as temp_dir:
        home = Path(temp_dir)
        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        shutil.copyfile(auth_path, codex_dir / "auth.json")
        prompt = build_agent_prompt(barcode, fallback_result=fallback_result)
        process_env = os.environ.copy()
        process_env.update(
            {
                "HOME": str(home),
                "CODEX_HOME": str(codex_dir),
            }
        )
        process = await asyncio.create_subprocess_exec(
            "codex",
            "--model",
            settings.agent_search_model,
            "exec",
            "--ephemeral",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--cd",
            "/data",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.agent_search_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Agent search timed out")
        if process.returncode != 0:
            raise RuntimeError(f"Codex search failed: {stderr.decode(errors='replace')[-1000:]}")

    payload = parse_last_json_object(stdout.decode(errors="replace"))
    return build_agent_lookup_result(barcode, payload)


def build_agent_lookup_result(barcode: str, payload: dict[str, Any] | None) -> LookupResult | None:
    if payload is None or not payload.get("found") or not payload.get("name"):
        return None
    normalized = normalize_product_name(
        payload["name"],
        brand=payload.get("brand"),
        quantity=payload.get("quantity"),
    )
    confidence = min(float(payload.get("confidence") or 0.5), 0.65)
    name_origin = payload.get("name_origin")
    if name_origin not in {"sourced_english", "translated"}:
        return None
    if name_origin == "translated":
        confidence = min(confidence, 0.55)
    sources = [
        source
        for source in payload.get("sources", [])
        if isinstance(source, str) and source.startswith(("http://", "https://"))
    ]
    image_url = payload.get("image_url")
    if not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
        image_url = None
    original_name = payload.get("original_name")
    original_language = payload.get("original_language")
    alternate_names = {}
    if name_origin == "translated" and isinstance(original_name, str) and isinstance(original_language, str):
        alternate_names[original_language] = original_name
    return LookupResult(
        barcode=barcode,
        name=normalized.normalized_name,
        name_language="en",
        name_origin="translated" if name_origin == "translated" else "sourced",
        alternate_names=alternate_names,
        raw_name=payload["name"],
        normalized_name=normalized.normalized_name,
        brand=normalized.brand,
        quantity=payload.get("quantity"),
        size=payload.get("size") or normalized.size,
        count=payload.get("count") or normalized.count,
        variant=payload.get("variant") or normalized.variant,
        image_url=image_url,
        source="agent_translation" if name_origin == "translated" else "agent_search",
        confidence=confidence,
        match_reason="coding_agent_research",
        match_warnings=[] if payload.get("barcode_verified") else ["agent_did_not_verify_exact_barcode"],
        raw_url=sources[0] if sources else None,
        raw_payload={
            "sources": sources,
            "barcode_verified": bool(payload.get("barcode_verified")),
            "reasoning_summary": payload.get("reasoning_summary"),
            "agent_model": settings.agent_search_model,
            "name_origin": name_origin,
            "original_name": original_name,
            "original_language": original_language,
        },
    )


def build_agent_prompt(barcode: str, fallback_result: LookupResult | None = None) -> str:
    fallback_context = "No trusted non-English fallback name was provided."
    if fallback_result is not None:
        fallback_context = (
            "Trusted non-English fallback product JSON:\n"
            + json.dumps(
                {
                    "name": fallback_result.raw_name or fallback_result.name,
                    "language": fallback_result.name_language,
                    "brand": fallback_result.brand,
                    "quantity": fallback_result.quantity,
                    "source": fallback_result.source,
                    "source_url": str(fallback_result.raw_url) if fallback_result.raw_url else None,
                },
                ensure_ascii=False,
            )
        )
    return f"""
Research the consumer product with barcode {barcode}.

Use web search and inspect multiple sources when possible. This is not a coding task.
Prefer exact barcode evidence from retailer pages, manufacturer pages, product databases,
search snippets, JSON-LD, or embedded product data. Compare conflicting results.
First try to find an English product name supported by a source. Only if exhaustive research
finds no sourced English name, translate the trusted non-English fallback name below into
natural English. Never translate an unverified name or invent missing product details.

{fallback_context}

Return ONLY one JSON object with exactly these fields:
{{
  "found": true or false,
  "name": string or null,
  "name_origin": "sourced_english", "translated", or null,
  "original_name": string or null,
  "original_language": string or null,
  "brand": string or null,
  "quantity": string or null,
  "size": string or null,
  "count": integer or null,
  "variant": string or null,
  "image_url": string or null,
  "barcode_verified": true or false,
  "confidence": number between 0 and 0.65,
  "sources": ["https://..."],
  "reasoning_summary": "short evidence summary"
}}

Set found=false when you cannot identify a plausible product. Do not invent product details.
For translated results, preserve the exact original name and language in original_name and
original_language. For sourced English results, set those fields to null.
Do not include markdown fences or any text outside the JSON object.
""".strip()


def parse_last_json_object(output: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    parsed_objects: list[dict[str, Any]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed_objects.append(parsed)
    return parsed_objects[-1] if parsed_objects else None
