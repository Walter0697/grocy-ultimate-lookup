import re


TITLE_STOP_WORDS = {
    "and",
    "for",
    "from",
    "online",
    "product",
    "shop",
    "store",
    "the",
    "with",
}


def title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in TITLE_STOP_WORDS and not token.isdigit()
    }


def titles_conflict(search_title: str, product_name: str) -> bool:
    search_tokens = title_tokens(search_title)
    product_tokens = title_tokens(product_name)
    return bool(search_tokens and product_tokens and search_tokens.isdisjoint(product_tokens))


def web_confidence(match_reason: str, match_warnings: list[str]) -> float:
    confidence_by_reason = {
        "barcode_in_structured_data": 0.65,
        "barcode_in_page_content": 0.55,
        "search_result_only": 0.45,
    }
    confidence = confidence_by_reason.get(match_reason, 0.4)
    if "search_title_product_name_mismatch" in match_warnings:
        confidence = min(confidence, 0.4)
    return confidence


def llm_confidence(barcode_seen: bool, match_warnings: list[str]) -> float:
    confidence = 0.35 if barcode_seen else 0.25
    if "search_title_product_name_mismatch" in match_warnings:
        confidence = min(confidence, 0.2)
    return confidence
