import re
import time
from dataclasses import dataclass, replace
from functools import lru_cache

from .config import Settings


@dataclass(frozen=True)
class BasalamCategory:
    id: int
    title: str
    path: str
    unit_type_id: int | None = None
    unit_type_title: str | None = None
    max_preparation_days: int | None = None
    confidence: float | None = None


_CATEGORY_CACHE: dict[str, tuple[float, list[BasalamCategory]]] = {}


def clear_basalam_category_cache() -> None:
    _CATEGORY_CACHE.clear()
    _tokenize.cache_clear()


def get_basalam_leaf_categories(settings: Settings, client, refresh: bool = False) -> list[BasalamCategory]:
    cache_key = settings.basalam_api_base_url.rstrip("/")
    cached = _CATEGORY_CACHE.get(cache_key)
    now = time.time()
    if cached and not refresh and now - cached[0] < settings.basalam_category_cache_ttl_seconds:
        return cached[1]
    raw = client.get_categories()
    leaves = flatten_categories(raw)
    _CATEGORY_CACHE[cache_key] = (now, leaves)
    return leaves


def flatten_categories(raw: dict | list) -> list[BasalamCategory]:
    nodes = raw.get("data", raw) if isinstance(raw, dict) else raw
    leaves: list[BasalamCategory] = []

    def walk(items: list[dict], path: list[str]) -> None:
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            current_path = [*path, title]
            children = item.get("children") or []
            if children:
                walk(children, current_path)
                continue
            unit_type = item.get("unit_type") or {}
            leaves.append(
                BasalamCategory(
                    id=int(item["id"]),
                    title=title,
                    path=" > ".join(current_path),
                    unit_type_id=int(unit_type["id"]) if unit_type.get("id") is not None else None,
                    unit_type_title=unit_type.get("title"),
                    max_preparation_days=item.get("max_preparation_days"),
                )
            )

    walk(nodes or [], [])
    return leaves


def category_to_dict(category: BasalamCategory) -> dict:
    return {
        "id": category.id,
        "title": category.title,
        "path": category.path,
        "unit_type_id": category.unit_type_id,
        "unit_type_title": category.unit_type_title,
        "max_preparation_days": category.max_preparation_days,
        "confidence": category.confidence,
    }


def find_category(categories: list[BasalamCategory], category_id: int) -> BasalamCategory | None:
    return next((category for category in categories if category.id == category_id), None)


def search_categories(categories: list[BasalamCategory], query: str, limit: int = 20) -> list[BasalamCategory]:
    query = query.strip()
    if not query:
        return []
    scored = [category_with_score(category, query) for category in categories]
    scored = [category for category in scored if (category.confidence or 0) > 0]
    scored.sort(key=lambda category: (category.confidence or 0, _specificity(category)), reverse=True)
    return scored[:limit]


def suggest_category(categories: list[BasalamCategory], title: str, description: str = "") -> BasalamCategory | None:
    title_query = title.strip()
    full_query = f"{title} {description}".strip()
    title_matches = search_categories(categories, title_query, limit=3) if title_query else []
    full_matches = search_categories(categories, full_query, limit=3) if full_query else []
    if not title_matches and not full_matches:
        return None

    best = full_matches[0] if full_matches else title_matches[0]
    if title_matches and (title_matches[0].confidence or 0) >= (best.confidence or 0) * 0.85:
        best = title_matches[0]

    if not _has_direct_title_signal(best, title_query):
        return replace(best, confidence=round(min(best.confidence or 0, 0.4), 3))
    return best


def category_with_score(category: BasalamCategory, query: str) -> BasalamCategory:
    normalized_query = normalize_text(query)
    title_norm = normalize_text(category.title)
    path_norm = normalize_text(category.path)
    query_tokens = set(_tokenize(normalized_query))
    expanded_query_tokens = _expand_query_tokens(query_tokens)
    title_tokens = set(_tokenize(title_norm))
    path_tokens = set(_tokenize(path_norm))
    if not query_tokens:
        score = 0.0
    else:
        title_match = title_tokens & expanded_query_tokens
        path_match = path_tokens & expanded_query_tokens
        title_coverage = len(title_match) / max(1, len(title_tokens))
        query_title_coverage = len(title_match) / max(1, len(query_tokens))
        path_coverage = len(path_match) / max(1, min(len(query_tokens), 8))
        score = title_coverage * 0.46 + query_title_coverage * 0.25 + path_coverage * 0.18
        if title_norm and title_norm in normalized_query:
            score += 0.28
        if normalized_query and normalized_query in path_norm:
            score += 0.12
        boost = _domain_boost(path_tokens, expanded_query_tokens)
        score += boost
        if not (title_tokens & query_tokens) and boost <= 0:
            score = min(score, 0.42)
    score = max(0.0, min(1.0, score))
    return BasalamCategory(
        id=category.id,
        title=category.title,
        path=category.path,
        unit_type_id=category.unit_type_id,
        unit_type_title=category.unit_type_title,
        max_preparation_days=category.max_preparation_days,
        confidence=round(score, 3),
    )


def normalize_text(value: str) -> str:
    value = value.lower()
    replacements = {
        "ي": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "‌": " ",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = re.sub(r"[\u064b-\u065f]", "", value)
    value = re.sub(r"[^\w\u0600-\u06ff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_direct_title_signal(category: BasalamCategory, query: str) -> bool:
    normalized_query = normalize_text(query)
    title_norm = normalize_text(category.title)
    if title_norm and title_norm in normalized_query:
        return True
    query_tokens = set(_tokenize(normalized_query))
    expanded_query_tokens = _expand_query_tokens(query_tokens)
    title_tokens = set(_tokenize(title_norm))
    return bool(query_tokens and title_tokens and expanded_query_tokens & title_tokens)


def _specificity(category: BasalamCategory) -> int:
    return len(_tokenize(normalize_text(category.title)))


def _expand_query_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    synonym_groups = [
        {"ایرپاد", "ایرپادز", "ایرباد", "هندزفری", "هدفون", "airpod", "airpods", "apods", "earbud", "earbuds"},
        {"اسپیکر", "بلندگو", "speaker"},
        {"ساعت", "واچ", "مچ", "بند", "هوشمند", "watch"},
        {"شارژر", "کابل", "اداپتور", "آداپتور", "charger", "cable"},
        {"قاب", "کاور", "گارد", "case", "cover"},
    ]
    for group in synonym_groups:
        if tokens & group:
            expanded |= group
    return expanded


def _domain_boost(path_tokens: set[str], query_tokens: set[str]) -> float:
    boost = 0.0
    digital_path = {"دیجیتال", "موبایل", "کامپیوتر", "صوتی", "تصویری", "لوازم", "جانبی"} & path_tokens
    unrelated_path = {"خانه", "اشپزخانه", "آشپزخانه", "سرگرمی"} & path_tokens

    if query_tokens & {"ایرپاد", "ایرپادز", "ایرباد", "هندزفری", "هدفون", "airpod", "airpods", "apods", "earbud", "earbuds"}:
        if path_tokens & {"ایرپاد", "هندزفری", "هدفون", "ایرباد"}:
            boost += 0.35
        elif digital_path:
            boost += 0.08
        if unrelated_path:
            boost -= 0.28

    if query_tokens & {"اسپیکر", "بلندگو", "speaker"}:
        if path_tokens & {"اسپیکر", "بلندگو", "صوتی"}:
            boost += 0.32
        elif digital_path:
            boost += 0.08
        if unrelated_path:
            boost -= 0.25

    smart_watch_query = bool(query_tokens & {"ساعت", "واچ", "watch", "مچ"}) and bool(query_tokens & {"هوشمند", "بند", "مچ"})
    if smart_watch_query:
        if path_tokens & {"ساعت", "مچ", "هوشمند", "واچ"}:
            boost += 0.34
        elif digital_path:
            boost += 0.08
        if unrelated_path:
            boost -= 0.25

    if query_tokens & {"شارژر", "کابل", "اداپتور", "آداپتور", "charger", "cable"}:
        if path_tokens & {"شارژر", "کابل", "اداپتور", "آداپتور"}:
            boost += 0.33
        elif digital_path:
            boost += 0.08
        if unrelated_path:
            boost -= 0.22

    if query_tokens & {"قاب", "کاور", "گارد", "case", "cover"}:
        if path_tokens & {"قاب", "کاور", "گارد"}:
            boost += 0.33
        elif digital_path:
            boost += 0.08

    return boost


@lru_cache(maxsize=4096)
def _tokenize(value: str) -> tuple[str, ...]:
    stop_words = {
        "و",
        "یا",
        "از",
        "برای",
        "با",
        "به",
        "در",
        "این",
        "ان",
        "مدل",
        "محصول",
        "تستی",
        "شماره",
    }
    return tuple(token for token in value.split() if len(token) > 1 and token not in stop_words)
