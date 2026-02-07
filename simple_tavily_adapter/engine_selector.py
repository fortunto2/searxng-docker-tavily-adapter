"""
Smart engine selection based on query content.

Analyzes query keywords and routes to the best engine combination.
All engines must be enabled in SearXNG config.yaml to work.

Engine groups:
- GENERAL: broad web search (default fallback)
- ACADEMIC: papers, research, algorithms
- TECH: code, libraries, frameworks
- PRODUCT: apps, competitors, pricing, reviews
- REFERENCE: definitions, facts, history
- NEWS: recent events, launches, trends
"""

# Engine groups — all must be enabled in SearXNG config
ENGINES_GENERAL = "google,duckduckgo,brave,reddit"
ENGINES_ACADEMIC = "google,arxiv,google scholar,wikipedia,wikidata"
ENGINES_TECH = "google,github,stackoverflow,reddit,duckduckgo"
ENGINES_PRODUCT = "google,duckduckgo,brave,reddit,hacker news"
ENGINES_REFERENCE = "google,wikipedia,wikidata,duckduckgo"
ENGINES_NEWS = "google,duckduckgo,brave,reddit,hacker news"

# Keywords for each category (EN + RU)
_ACADEMIC_KW = [
    "research", "paper", "study", "arxiv", "journal", "thesis", "citation",
    "научн", "исследован", "статья", "диссертац",
    "algorithm", "neural network", "transformer", "llm architecture",
    "machine learning theory", "deep learning",
]
_TECH_KW = [
    "github", "stackoverflow", "programming", "code", "library", "framework",
    "npm", "pip", "package", "api", "sdk", "cli", "docker",
    "python", "javascript", "typescript", "swift", "kotlin", "rust", "go",
    "swiftui", "react", "nextjs", "fastapi", "django",
    "программиров", "код", "библиотек", "фреймворк",
]
_PRODUCT_KW = [
    "app", "alternative", "competitor", "pricing", "review", "vs",
    "saas", "startup", "product", "market", "landing",
    "приложени", "аналог", "конкурент", "цена", "отзыв",
    "best", "top", "comparison", "tools for",
]
_REFERENCE_KW = [
    "what is", "definition", "meaning", "wikipedia", "history of",
    "biography", "facts", "population", "statistics",
    "что такое", "определени", "значени", "биография", "история",
    "факт", "данные", "население", "статистик",
]
_NEWS_KW = [
    "news", "latest", "update", "announced", "launched", "released",
    "trend", "2025", "2026",
    "новост", "последн", "обновлен", "запуст", "тренд",
]

_CATEGORIES = {
    "academic": (_ACADEMIC_KW, ENGINES_ACADEMIC),
    "tech": (_TECH_KW, ENGINES_TECH),
    "product": (_PRODUCT_KW, ENGINES_PRODUCT),
    "reference": (_REFERENCE_KW, ENGINES_REFERENCE),
    "news": (_NEWS_KW, ENGINES_NEWS),
}


def get_smart_engines(query: str) -> str:
    """Select engines based on query keywords. Returns comma-separated engine names.

    Scores each category by counting keyword matches.
    Returns ENGINES_GENERAL if no category has any matches.
    """
    q = query.lower()

    best_cat = None
    best_score = 0

    for cat, (keywords, _engines) in _CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > best_score:
            best_score = score
            best_cat = cat

    if best_score == 0 or best_cat is None:
        return ENGINES_GENERAL

    return _CATEGORIES[best_cat][1]
