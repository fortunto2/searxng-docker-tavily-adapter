#!/usr/bin/env python3
"""
Тест для проверки Docker готовности
"""
import sys
import subprocess

def check_python_version():
    """Проверяем версию Python"""
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major == 3 and version.minor >= 12:
        print("✅ Python 3.12+ поддерживается")
        return True
    else:
        print("❌ Требуется Python 3.12+")
        return False

def check_imports():
    """Проверяем все импорты"""
    try:
        import fastapi
        import uvicorn
        import aiohttp
        import pydantic
        import bs4
        import yaml
        import markdownify
        import nh3
        import dotenv
        
        print("✅ Все зависимости доступны")
        return True
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False

def check_uv_available():
    """Проверяем доступность uv"""
    try:
        result = subprocess.run(['uv', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✅ uv доступен: {result.stdout.strip()}")
            return True
        else:
            print("❌ uv не найден")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ uv не установлен")
        return False

def check_app_startup():
    """Проверяем, что приложение может запуститься"""
    try:
        from main import app
        print("✅ FastAPI приложение загружается корректно")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки приложения: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Тест Docker готовности")
    print("=" * 40)
    
    checks = [
        ("Python version", check_python_version),
        ("Dependencies", check_imports),
        ("uv availability", check_uv_available),
        ("App startup", check_app_startup),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n🔍 {name}:")
        success = check_func()
        results.append(success)
    
    print("\n" + "=" * 40)
    if all(results):
        print("🎉 Все проверки прошли! Docker готов к сборке")
        sys.exit(0)
    else:
        print("❌ Некоторые проверки провалились")
        sys.exit(1)