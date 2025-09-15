"""
Умный выбор поисковых движков в зависимости от запроса
"""


def get_smart_engines(query: str) -> str:
    """Интеллектуальный выбор движков в зависимости от запроса"""
    query_lower = query.lower()

    # Научные запросы - приоритет ArXiv и Wikipedia
    if any(
        word in query_lower
        for word in ["research", "paper", "study", "научн", "исследован", "статья"]
    ):
        return "arxiv,wikipedia,wikidata,google,duckduckgo"

    # Программирование - Reddit + основные
    elif any(
        word in query_lower
        for word in [
            "programming",
            "python",
            "javascript",
            "code",
            "программиров",
            "код",
        ]
    ):
        return "reddit,google,duckduckgo,wikipedia,wikidata"

    # Биографии и история - Wikipedia + Wikidata приоритет
    elif any(
        word in query_lower for word in ["biography", "history", "биография", "история"]
    ):
        return "wikipedia,wikidata,google,duckduckgo,reddit"

    # Факты и данные - Wikidata приоритет
    elif any(
        word in query_lower
        for word in [
            "facts",
            "data",
            "population",
            "statistics",
            "факт",
            "данные",
            "население",
            "статистик",
        ]
    ):
        return "wikidata,wikipedia,google,duckduckgo"

    # Общие запросы - стандартная комбинация
    else:
        return "google,duckduckgo,wikipedia,wikidata,arxiv,reddit"