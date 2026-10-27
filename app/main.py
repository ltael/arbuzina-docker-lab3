from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
import httpx
import psycopg2
import redis

app = FastAPI(title="Personal Assistant")

OWNER = os.getenv("APP_OWNER", "anonymous")
SECRET_KEY = os.getenv("APP_SECRET", "default_secret")

# ЛР3: строка подключения к PostgreSQL.
# Формат: postgresql://пользователь:пароль@хост:порт/имя_бд
DATABASE_URL = os.getenv("DATABASE_URL")

# ЛР4: Redis для кэширования погоды.
# В Docker Compose хост redis — это имя сервиса redis из docker-compose.yml.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "120"))
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


class Note(BaseModel):
    text: str


# Запасное хранилище в памяти: используется, только если DATABASE_URL не задан
# (так приложение по-прежнему запускается без БД, как во второй лабе).
memory_notes: list[str] = []


def get_conn():
    """Открывает новое соединение с PostgreSQL."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


def init_db(cur):
    """Создаёт таблицу заметок, если её ещё нет."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


@app.get("/")
async def root():
    return {
        "message": f"👋 Привет, {OWNER}!",
        "service": "personal-assistant",
        "version": "4.0",
        "storage": "postgresql" if DATABASE_URL else "memory",
        "endpoints": ["/health", "/me", "/notes", "/weather/{city}", "/cache/stats", "/secret/{key}"],
    }


@app.get("/health")
def health():
    result = {"status": "healthy", "owner": OWNER}
    # ЛР4: состояние Redis показываем для информации, на статус не влияет
    try:
        redis_client.ping()
        result["redis"] = "connected"
    except redis.RedisError:
        result["redis"] = "unavailable"
    if not DATABASE_URL:
        result["database"] = "not configured"
        return result
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
        finally:
            conn.close()
        result["database"] = "connected"
        result["db_version"] = version.split(",")[0]
        return result
    except psycopg2.Error as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "owner": OWNER,
                "database": "unavailable",
                "error": str(e).strip(),
            },
        )


@app.get("/me")
async def me():
    return {
        "owner": OWNER,
        "secret_prefix": SECRET_KEY[:6]
        if SECRET_KEY != "default_secret"
        else "NOT_SET",
    }


@app.get("/secret/{key}")
async def secret(key: str):
    """Secret endpoint - checking environment variables"""
    if key == SECRET_KEY:
        return {
            "flag": f"LAB2_SUCCESS_{OWNER.upper()}",
            "message": "The secret key is correct!",
        }
    return {
        "error": "The secret key is incorrect",
        "hint": "Check the APP_SECRET environment variable",
    }


WEATHER_CODES: dict[int, str] = {
    0: "☀️ Ясно", 1: "🌤 Малооблачно", 2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось", 53: "🌦 Морось", 55: "🌧 Сильная морось",
    61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
    71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "❄️ Сильный снег",
    80: "🌦 Ливень", 81: "🌧 Сильный ливень", 82: "⛈ Штормовой ливень",
    95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Сильная гроза с градом",
}


@app.get("/weather/{city}")
async def weather(city: str):
    cache_key = f"weather:{OWNER}:{city.lower()}"

    # ЛР4: сначала проверяем кэш
    try:
        cached = redis_client.get(cache_key)
    except redis.RedisError:
        cached = None  # Redis недоступен: просто идём во внешний API
    if cached:
        data = json.loads(cached)
        data["source"] = "cache"
        return data

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "ru"},
            )
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return {"error": f"City «{city}» not found"}

            location = geo_data["results"][0]
            lat = location["latitude"]
            lon = location["longitude"]
            city_name = location.get("name", city)
            country = location.get("country", "")

            weather_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                },
            )
            weather_data = weather_resp.json()["current"]

            code = weather_data.get("weather_code", -1)

            result = {
                "city": city_name,
                "country": country,
                "coordinates": {"lat": lat, "lon": lon},
                "temperature_c": weather_data["temperature_2m"],
                "humidity_pct": weather_data["relative_humidity_2m"],
                "wind_km_h": weather_data["wind_speed_10m"],
                "condition": WEATHER_CODES.get(code, f"Code {code}"),
                "source": "api",
            }
    except Exception as e:
        # ошибки в кэш не кладём
        return {"error": f"Failed to get weather: {type(e).__name__}: {e}"}

    # ЛР4: сохраняем результат в кэш на CACHE_TTL секунд
    try:
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))
    except redis.RedisError:
        pass
    return result


@app.get("/cache/stats")
async def cache_stats():
    keys = redis_client.keys(f"weather:{OWNER}:*")
    return {
        "owner": OWNER,
        "ttl_seconds": CACHE_TTL,
        "cached_count": len(keys),
        "cached_cities": sorted(k.split(":")[-1] for k in keys),
    }


# Обработчики заметок объявлены через обычный def (не async):
# psycopg2 работает синхронно, и FastAPI сам запустит их в отдельном потоке,
# не блокируя остальные запросы.

@app.post("/notes")
def create_note(note: Note):
    if not DATABASE_URL:
        memory_notes.append(note.text)
        return {
            "status": "saved",
            "note_id": len(memory_notes) - 1,
            "total": len(memory_notes),
            "storage": "memory",
        }

    conn = get_conn()
    try:
        with conn:  # транзакция: COMMIT при успехе, ROLLBACK при ошибке
            with conn.cursor() as cur:
                init_db(cur)
                cur.execute(
                    "INSERT INTO notes (text) VALUES (%s) RETURNING id",
                    (note.text,),
                )
                note_id = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM notes")
                total = cur.fetchone()[0]
    finally:
        conn.close()

    return {"status": "saved", "note_id": note_id, "total": total, "storage": "postgresql"}


@app.get("/notes")
def list_notes():
    if not DATABASE_URL:
        return {"notes": memory_notes, "count": len(memory_notes), "storage": "memory"}

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                init_db(cur)
                cur.execute("SELECT id, text, created_at FROM notes ORDER BY id")
                rows = cur.fetchall()
    finally:
        conn.close()

    notes = [
        {"id": r[0], "text": r[1], "created_at": r[2].strftime("%Y-%m-%d %H:%M:%S")}
        for r in rows
    ]
    return {"notes": notes, "count": len(notes), "storage": "postgresql"}
