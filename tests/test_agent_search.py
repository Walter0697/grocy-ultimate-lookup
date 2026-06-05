from app.agent_search import (
    AgentSearchStore,
    build_agent_lookup_result,
    build_agent_prompt,
    parse_last_json_object,
)
from app.models import LookupResult


def test_agent_search_store_persists_completed_result(tmp_path) -> None:
    store = AgentSearchStore(str(tmp_path / "agent.sqlite3"))
    fallback = LookupResult(
        barcode="810669032478",
        name="Produit original",
        name_language="fr",
        source="open_products_facts",
        confidence=0.95,
    )
    assert store.queue("810669032478", fallback_result=fallback) is True
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
    assert status["fallback"]["name_language"] == "fr"
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
    fallback = LookupResult(
        barcode="810669032478",
        name="Sac à ordures",
        name_language="fr",
        source="open_products_facts",
        confidence=0.95,
    )
    prompt = build_agent_prompt("810669032478", fallback_result=fallback)

    assert "810669032478" in prompt
    assert "Return ONLY one JSON object" in prompt
    assert '"barcode_verified"' in prompt
    assert '"name_origin"' in prompt
    assert "Sac à ordures" in prompt
    assert "Only if exhaustive research" in prompt


def test_translated_agent_result_preserves_original_name() -> None:
    result = build_agent_lookup_result(
        "055966908051",
        {
            "found": True,
            "name": "White Drawstring Kitchen Garbage Bags",
            "name_origin": "translated",
            "original_name": "Sac à ordures blancs à cordons pour la cuisine",
            "original_language": "fr",
            "brand": "Hercules",
            "quantity": "20",
            "barcode_verified": True,
            "confidence": 0.65,
            "sources": ["https://example.test/product"],
        },
    )

    assert result is not None
    assert result.source == "agent_translation"
    assert result.name_origin == "translated"
    assert result.name_language == "en"
    assert result.confidence == 0.55
    assert result.alternate_names == {"fr": "Sac à ordures blancs à cordons pour la cuisine"}
