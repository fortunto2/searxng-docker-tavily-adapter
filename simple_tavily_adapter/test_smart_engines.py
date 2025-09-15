#!/usr/bin/env python3
"""
Тест умного выбора движков
"""
from main import get_smart_engines

def test_smart_engine_selection():
    """Тест функции умного выбора движков"""
    
    print("🧠 Тестирование умного выбора движков")
    print("=" * 50)
    
    test_cases = [
        # Научные запросы
        ("machine learning research paper", "научные"),
        ("quantum physics study", "научные"),
        ("исследование нейронных сетей", "научные"),
        
        # Программирование
        ("python programming tutorial", "программирование"),
        ("javascript code example", "программирование"),
        ("программирование на go", "программирование"),
        
        # Биографии и история
        ("Napoleon Bonaparte biography", "биография/история"),
        ("history of Roman Empire", "биография/история"),
        ("биография Пушкина", "биография/история"),
        
        # Факты и данные
        ("population of Tokyo statistics", "факты/данные"),
        ("GDP data by country", "факты/данные"),
        ("население России", "факты/данные"),
        
        # Общие запросы
        ("best restaurants in Paris", "общие"),
        ("weather forecast", "общие"),
        ("лучшие фильмы 2024", "общие"),
    ]
    
    for query, category in test_cases:
        engines = get_smart_engines(query)
        print(f"📝 Запрос: '{query}'")
        print(f"🏷️  Категория: {category}")
        print(f"🔍 Движки: {engines}")
        print()
    
    print("✅ Тест завершен!")
    
    # Проверка приоритетов
    print("\n🎯 Проверка приоритетов:")
    
    scientific = get_smart_engines("quantum research paper")
    programming = get_smart_engines("python programming")
    biography = get_smart_engines("Einstein biography")
    facts = get_smart_engines("population statistics")
    general = get_smart_engines("best pizza recipe")
    
    assert "arxiv" in scientific.split(",")[:2], "ArXiv должен быть в приоритете для научных запросов"
    assert "reddit" in programming.split(",")[:2], "Reddit должен быть в приоритете для программирования"
    assert "wikipedia" in biography.split(",")[:2], "Wikipedia должна быть в приоритете для биографий"
    assert "wikidata" in facts.split(",")[:2], "Wikidata должна быть в приоритете для фактов/данных"
    
    print("✅ Все приоритеты работают корректно!")

if __name__ == "__main__":
    test_smart_engine_selection()