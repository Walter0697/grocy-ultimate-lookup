from app.agent_search import AgentSearchStore, build_agent_prompt, parse_last_json_object
from app.models import LookupResult


def test_agent_search_store_persists_completed_result(tmp_path) -> None:
    store = AgentSearchStore(str(tmp_path / "agent.sqlite3"))
    assert store.queue("810669032478") is True
    assert store.queue("810669032478") is False
    store.mark_running("810669032478")
    store.mark_completed(
        "810669032478",
        LookupResult(
            barcode="810669032478",
            name="Agent Product",
            normalized_name="Agent Product",
            source="agent_search",
            confidence=0.6,
        ),
    )

    status = store.get_status("810669032478")
    result = store.get_result("810669032478")

    assert status is not None
    assert status["status"] == "completed"
    assert result is not None
    assert result.name == "Agent Product"


def test_agent_search_store_allows_retry_after_failure(tmp_path) -> None:
    store = AgentSearchStore(str(tmp_path / "agent.sqlite3"))
    store.queue("810669032478")
    store.mark_failed("810669032478", "failed")

    assert store.queue("810669032478") is True
    assert store.get_status("810669032478")["status"] == "queued"


def test_parse_last_json_object_uses_final_agent_result() -> None:
    output = 'progress {"step": 1}\n{"found": true, "name": "Final Product"}'

    result = parse_last_json_object(output)

    assert result == {"found": True, "name": "Final Product"}


def test_agent_prompt_requires_strict_product_research_json() -> None:
    prompt = build_agent_prompt("810669032478")

    assert "810669032478" in prompt
    assert "Return ONLY one JSON object" in prompt
    assert '"barcode_verified"' in prompt
