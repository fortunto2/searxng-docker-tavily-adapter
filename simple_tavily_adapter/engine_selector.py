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
# Independent indexes (mojeek, stract, marginalia) added for diversity.
ENGINES_GENERAL = "google,duckduckgo,brave,mojeek"
ENGINES_ACADEMIC = "google,arxiv,google scholar,wikipedia,wikidata"
ENGINES_TECH = "google,github,stackoverflow,duckduckgo,lobste.rs,mdn"
ENGINES_PRODUCT = "google,duckduckgo,brave,mojeek,crowdview,google play apps,apple app store"
ENGINES_REFERENCE = "google,wikipedia,wikidata,duckduckgo"
ENGINES_NEWS = "google,google news,duckduckgo,brave,hackernews,lobste.rs"
ENGINES_AI = "google,github,huggingface,arxiv,duckduckgo"

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
    "app store", "play store", "ios", "android",
    "solopreneur", "indiehacker", "bootstrapped", "mvp",
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
_AI_KW = [
    "huggingface", "model", "llm", "gpt", "claude", "gemini", "ollama",
    "fine-tune", "finetune", "embedding", "rag", "vector",
    "ai agent", "ai tool", "langchain", "llamaindex",
    "нейросет", "модел", "ии агент",
]

_CATEGORIES = {
    "academic": (_ACADEMIC_KW, ENGINES_ACADEMIC),
    "tech": (_TECH_KW, ENGINES_TECH),
    "product": (_PRODUCT_KW, ENGINES_PRODUCT),
    "reference": (_REFERENCE_KW, ENGINES_REFERENCE),
    "news": (_NEWS_KW, ENGINES_NEWS),
    "ai": (_AI_KW, ENGINES_AI),
}


# Engine → SearXNG categories mapping
# SearXNG requires matching categories for engines to return results
ENGINE_CATEGORIES: dict[str, str] = {
    "google": "general",
    "duckduckgo": "general",
    "brave": "general",
    "mojeek": "general",
    "stract": "general",
    "marginalia": "general",
    "crowdview": "general",
    "wikipedia": "general",
    "wikidata": "general",
    "google news": "news",
    "reddit": "social media",
    "reddit api": "social media",
    "hackernews": "social media",
    "lobste.rs": "it",
    "github": "it",
    "stackoverflow": "it",
    "huggingface": "it",
    "huggingface datasets": "it",
    "mdn": "it",
    "arxiv": "science",
    "google scholar": "science",
    "youtube": "videos",
    "google play apps": "general",
    "apple app store": "general",
    "npm": "it",
    "pypi": "it",
    "crates.io": "it",
    "bitbucket": "it",
    "codeberg": "it",
    "gitlab": "it",
}


def get_categories_for_engines(engines: str) -> str:
    """Return comma-separated SearXNG categories needed for the given engines.

    SearXNG requires matching categories — e.g. reddit needs 'social media',
    github needs 'it'. Without the right category, the engine returns 0 results.
    """
    cats: set[str] = set()
    for engine in engines.split(","):
        engine = engine.strip()
        cat = ENGINE_CATEGORIES.get(engine)
        if cat:
            cats.add(cat)
    return ",".join(sorted(cats)) if cats else "general"


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
