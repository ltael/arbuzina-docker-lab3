# 1. Базовый образ: облегчённый Python 3.11 на Debian
FROM python:3.11-slim

# 2. Метаданные образа
LABEL maintainer="arbuzina@lab.local"
LABEL version="3.0"

# 3. Рабочая директория внутри контейнера
WORKDIR /app

# 4. Сначала копируем только список зависимостей (для кеширования слоя)
COPY requirements.txt .

# 5. Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# 6. Копируем код приложения
COPY app/ ./app/

# 7. Документируем порт ассистента (ЛР3: 8000 + 38 = 8038)
EXPOSE 8038

# 8. Запуск приложения на персональном порту ассистента
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8038"]
