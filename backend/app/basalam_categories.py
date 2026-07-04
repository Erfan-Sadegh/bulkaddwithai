import re
import time
from dataclasses import dataclass
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
    scored.sort(key=lambda category: (category.confidence or 0, len(category.path)), reverse=True)
    return scored[:limit]


def suggest_category(categories: list[BasalamCategory], title: str, description: str = "") -> BasalamCategory | None:
    query = f"{title} {title} {description}".strip()
    matches = search_categories(categories, query, limit=1)
    return matches[0] if matches else None


def category_with_score(category: BasalamCategory, query: str) -> BasalamCategory:
    normalized_query = normalize_text(query)
    title_norm = normalize_text(category.title)
    path_norm = normalize_text(category.path)
    query_tokens = set(_tokenize(normalized_query))
    title_tokens = set(_tokenize(title_norm))
    path_tokens = set(_tokenize(path_norm))
    if not query_tokens:
        score = 0.0
    else:
        title_overlap = len(title_tokens & query_tokens) / max(1, len(title_tokens))
        path_overlap = len(path_tokens & query_tokens) / max(1, min(len(path_tokens), 8))
        score = title_overlap * 0.72 + path_overlap * 0.18
        if title_norm and title_norm in normalized_query:
            score += 0.28
        if normalized_query and normalized_query in path_norm:
            score += 0.12
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
