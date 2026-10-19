# Практическая работа №3. Персистентность и изоляция: добавляем БД и настраиваем сети

**Студент:** Арбузина Елена Романовна, ИСУ 465038
**Дисциплина:** Контейнеризация и оркестрация приложений
**Основа:** репозиторий ЛР2 [ltael/arbuzina-docker-lab2](https://github.com/ltael/arbuzina-docker-lab2) — FastAPI-сервис «Personal Assistant»

## Персональные параметры

| Параметр                      | Значение                    |
| ----------------------------- | --------------------------- |
| Номер ИСУ                     | 465038                      |
| Персональный порт (PostgreSQL)| 5468 (5430 + 38)            |
| Персональный порт (Assistant) | 8038 (8000 + 38)            |
| Персональный префикс          | arbuzina                    |
| Секретный ключ                | secret38arbuzina            |
| Пользователь / пароль БД      | user_38 / pgpass_38         |
| Имя базы данных               | assistant_38                |

## Что изменено относительно ЛР2

- `app/main.py` — заметки хранятся в PostgreSQL (таблица `notes` создаётся автоматически), строка подключения берётся из переменной `DATABASE_URL`. Без неё приложение работает как раньше, с хранением в памяти. `/health` проверяет подключение к БД.
- `requirements.txt` — добавлен драйвер `psycopg2-binary`.
- `Dockerfile` — порт приложения изменён с 5468 на 8038 (5468 теперь занимает PostgreSQL).
- `config/app.conf` — файл конфигурации для bind mount.

## Структура репозитория

```
.
├── app/
│   └── main.py              # код приложения (FastAPI + PostgreSQL)
├── config/
│   └── app.conf             # конфигурация, монтируется в контейнер (этап 3)
├── requirements.txt         # зависимости Python
├── Dockerfile               # образ ассистента (порт 8038)
├── Dockerfile.optimized     # multi-stage образ из ЛР2
├── .dockerignore
└── README.md
```

## Требования

- Linux (проверено на Ubuntu 24.04)
- Docker Engine 28+
- git, curl, python3

## Воспроизведение

### 0. Клонирование и сборка образа

```bash
git clone https://github.com/ltael/arbuzina-docker-lab3.git
cd arbuzina-docker-lab3
docker build -t arbuzina-assistant:v3 .
```

### 1. Volume, PostgreSQL и подключение ассистента

```bash
docker volume create arbuzina-pgdata
docker volume inspect arbuzina-pgdata

docker run -d \
  --name arbuzina-postgres \
  -e POSTGRES_USER=user_38 \
  -e POSTGRES_PASSWORD=pgpass_38 \
  -e POSTGRES_DB=assistant_38 \
  -v arbuzina-pgdata:/var/lib/postgresql/data \
  -p 5468:5432 \
  postgres:15

sleep 5

docker run -d \
  --name arbuzina-assistant \
  --add-host=host.docker.internal:host-gateway \
  -p 8038:8038 \
  -e APP_OWNER=arbuzina \
  -e APP_SECRET=secret38arbuzina \
  -e DATABASE_URL="postgresql://user_38:pgpass_38@host.docker.internal:5468/assistant_38" \
  arbuzina-assistant:v3
```

Проверка:

```bash
curl http://localhost:8038/ ; echo
curl http://localhost:8038/health ; echo
curl -X POST http://localhost:8038/notes \
  -H "Content-Type: application/json" \
  -d '{"text": "ЛР3: данные в БД"}' ; echo
curl http://localhost:8038/notes ; echo
```

Ожидаемо: `/health` возвращает `"database":"connected"`, в `/notes` присутствует созданная заметка.

### 2. Тест персистентности

```bash
docker stop arbuzina-assistant && docker rm arbuzina-assistant

docker run -d \
  --name arbuzina-assistant \
  --add-host=host.docker.internal:host-gateway \
  -p 8038:8038 \
  -e APP_OWNER=arbuzina \
  -e APP_SECRET=secret38arbuzina \
  -e DATABASE_URL="postgresql://user_38:pgpass_38@host.docker.internal:5468/assistant_38" \
  arbuzina-assistant:v3

echo "========================================" && \
echo "Тест персистентности: $(date '+%H:%M:%S')" && \
echo "$(whoami)@$(hostname)" && \
echo "========================================" && \
curl -s http://localhost:8038/notes | python3 -m json.tool --no-ensure-ascii
```

Ожидаемо: заметка из этапа 1 на месте после пересоздания контейнера.

### 3. Bind mount конфигурации

```bash
# порт 8038 должен быть свободен
docker stop arbuzina-assistant && docker rm arbuzina-assistant

docker run -d \
  --name arbuzina-assistant-config \
  --add-host=host.docker.internal:host-gateway \
  -p 8038:8038 \
  -e APP_OWNER=arbuzina \
  -e APP_SECRET=secret38arbuzina \
  -e DATABASE_URL="postgresql://user_38:pgpass_38@host.docker.internal:5468/assistant_38" \
  -v $(pwd)/config:/app/config:ro \
  arbuzina-assistant:v3

docker exec arbuzina-assistant-config cat /app/config/app.conf
```

Проверка режима только для чтения (ожидается `Read-only file system`):

```bash
docker exec arbuzina-assistant-config sh -c 'echo test >> /app/config/app.conf'
```

Изменение конфигурации без пересборки: заменить в `config/app.conf` на хосте `maintenance_mode=false` на `true`, затем:

```bash
docker restart arbuzina-assistant-config
docker exec arbuzina-assistant-config cat /app/config/app.conf
```

### 4. Пользовательская сеть

```bash
docker network create arbuzina-backend

docker stop arbuzina-postgres arbuzina-assistant-config
docker rm arbuzina-postgres arbuzina-assistant-config

docker run -d \
  --name arbuzina-postgres \
  --network arbuzina-backend \
  -e POSTGRES_USER=user_38 \
  -e POSTGRES_PASSWORD=pgpass_38 \
  -e POSTGRES_DB=assistant_38 \
  -v arbuzina-pgdata:/var/lib/postgresql/data \
  postgres:15

sleep 5

docker run -d \
  --name arbuzina-assistant \
  --network arbuzina-backend \
  -p 8038:8038 \
  -e APP_OWNER=arbuzina \
  -e APP_SECRET=secret38arbuzina \
  -e DATABASE_URL="postgresql://user_38:pgpass_38@arbuzina-postgres:5432/assistant_38" \
  -v $(pwd)/config:/app/config:ro \
  arbuzina-assistant:v3
```

Проверка связности и изоляции:

```bash
curl http://localhost:8038/health ; echo
curl -X POST http://localhost:8038/notes \
  -H "Content-Type: application/json" \
  -d '{"text": "ЛР3: сеть работает!"}' ; echo
curl http://localhost:8038/notes ; echo

# вне сети — ошибка: ping: bad address 'arbuzina-postgres'
docker run -it --rm alpine:3.18 ping -c 2 arbuzina-postgres
# внутри сети — успешный ответ
docker run -it --rm --network arbuzina-backend alpine:3.18 ping -c 2 arbuzina-postgres
```

### 5. Итоговый артефакт

```bash
echo "========================================" && \
echo "ЛР3 завершена: $(date '+%d.%m.%Y %H:%M:%S')" && \
echo "Студент: $(whoami)@$(hostname)" && \
echo "========================================" && \
echo "" && \
echo "Контейнеры:" && \
docker ps --filter "name=arbuzina-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" && \
echo "" && \
echo "Volumes:" && \
docker volume ls --filter "name=arbuzina-" && \
echo "" && \
echo "Сети:" && \
docker network ls --filter "name=arbuzina-"
```

### Очистка

```bash
docker stop arbuzina-assistant arbuzina-postgres
docker rm arbuzina-assistant arbuzina-postgres
docker network rm arbuzina-backend
docker volume rm arbuzina-pgdata   # удаляет данные БД безвозвратно
docker rmi arbuzina-assistant:v3
```

## Результаты

| Этап | Проверка | Результат |
| ---- | -------- | --------- |
| 1 | Ассистент подключается к PostgreSQL через `host.docker.internal:5468` | `/health` → `database: connected`, PostgreSQL 15.19 |
| 2 | Пересоздание контейнера ассистента | заметка `id=1` сохранилась |
| 3 | Bind mount `config/` в режиме `:ro` | конфиг виден в контейнере, запись запрещена, изменения с хоста видны без пересборки |
| 4 | Пересоздание PostgreSQL в сети `arbuzina-backend` | обе заметки (`id=1`, `id=2`) на месте; имя `arbuzina-postgres` разрешается только внутри сети |
| 5 | Итоговая инфраструктура | 2 контейнера, volume `arbuzina-pgdata`, сеть `arbuzina-backend`; порт PostgreSQL наружу не опубликован |

## Найденные проблемы и их решения

1. **Приложение из ЛР2 хранило заметки в памяти** (список в `main.py`), поэтому тест персистентности провалился бы. Решение: хранение заметок перенесено в PostgreSQL через `psycopg2`, строка подключения задаётся переменной `DATABASE_URL`.
2. **`host.docker.internal` не существует в Docker Engine на Linux** (это имя есть только в Docker Desktop). Решение: в команды этапов 1–3 добавлен флаг `--add-host=host.docker.internal:host-gateway`.
3. **Конфликт портов.** Приложение ЛР2 слушало порт 5468, который в ЛР3 отдан PostgreSQL. Решение: в `Dockerfile` порт ассистента изменён на 8038. Кроме того, на этапе 3 контейнер `arbuzina-assistant` из этапа 2 занимал порт 8038, поэтому перед запуском `arbuzina-assistant-config` его нужно удалить (в задании этот шаг отсутствует).
4. **Опечатки в командах задания:** в `docker build` пропущена точка (контекст сборки), а в `docker volume ls │ grep` вместо вертикальной черты `|` стоит символ псевдографики `│`.
5. **`python3 -m json.tool` экранирует кириллицу** (`\u041b...`). Решение: флаг `--no-ensure-ascii`.
6. **Ping вне сети возвращал фиктивный адрес 198.18.0.x вместо ошибки.** Контейнер в сети по умолчанию отправлял DNS-запрос на DNS хоста, а VPN-клиент в режиме fake-IP отвечал поддельным адресом из диапазона 198.18.0.0/15. Пакеты не доходили, то есть изоляция работала, но вывод вводил в заблуждение. При отключённом VPN получен ожидаемый результат `bad address`.
