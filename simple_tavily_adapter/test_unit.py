#!/usr/bin/env python3
"""
Unit тесты для адаптера
"""
import pytest
from main import SearchRequest

def test_search_request_defaults():
    """Тест дефолтных значений SearchRequest"""
    # Минимальный запрос
    req = SearchRequest(query="test")
    assert req.query == "test"
    assert req.max_results == 10
    assert req.include_raw_content == False
    assert req.content_format == "markdown"  # По умолчанию теперь markdown
    
def test_search_request_custom():
    """Тест кастомных значений SearchRequest"""
    req = SearchRequest(
        query="custom search",
        max_results=5,
        include_raw_content=True,
        content_format="text"
    )
    assert req.query == "custom search"
    assert req.max_results == 5
    assert req.include_raw_content == True
    assert req.content_format == "text"

def test_content_format_validation():
    """Тест валидации content_format"""
    # Валидные значения
    req1 = SearchRequest(query="test", content_format="text")
    assert req1.content_format == "text"
    
    req2 = SearchRequest(query="test", content_format="markdown")
    assert req2.content_format == "markdown"
    
    # Невалидное значение должно вызвать ошибку
    try:
        SearchRequest(query="test", content_format="invalid")
        assert False, "Должна быть ошибка валидации"
    except ValueError:
        pass  # Ожидаемое поведение

def test_markdown_default():
    """Тест что markdown теперь по умолчанию"""
    req = SearchRequest(query="test")
    assert req.content_format == "markdown"
    
    print("✅ Все unit тесты прошли!")

if __name__ == "__main__":
    test_search_request_defaults()
    test_search_request_custom() 
    test_content_format_validation()
    test_markdown_default()
    print("🎉 Все тесты успешно завершены!")