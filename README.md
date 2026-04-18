# autoposter-AI

Локальный, self-hosted AI-постер в соцсети. Альтернатива PilotPoster ($99/мес) на
своей машине за ~$2-5/мес в AI-токенах. Multi-platform-ready: начинаем с Facebook
Groups + Profile, расширяемся на LinkedIn / X / Threads / Bluesky / Reddit / VK.

## Что это

Три компонента, общающиеся через WebSocket на localhost:

| Слой | Что делает | Стек |
|------|-----------|------|
| `backend/` | FastAPI-сервер: планировщик, AI-генерация, БД, оркестрация | Python 3.12, FastAPI, SQLAlchemy, APScheduler, Anthropic SDK, Gemini SDK |
| `extension/` | Chrome-расширение: DOM-автоматизация Facebook | TypeScript, Manifest V3, Vite |
| `dashboard/` | UI: business profile, календарь, очередь ревью, логи | Next.js 15, Tailwind, shadcn/ui |

```
┌────────────────┐     HTTP      ┌──────────────────┐     WebSocket    ┌──────────────────┐
│   Dashboard    │ ──────────▶  │   Backend (API)  │ ◀─────────────▶ │ Chrome extension │
│   Next.js      │               │    FastAPI       │                  │   (content script)│
│  localhost:3000│               │ localhost:8787  │                  │                  │
└────────────────┘               └──────────────────┘                  └─────────┬────────┘
                                         │                                        │
                                         ▼                                        ▼
                                  ┌─────────────┐                        ┌──────────────┐
                                  │  SQLite DB  │                        │   Facebook   │
                                  │  + queue    │                        │     DOM      │
                                  └─────────────┘                        └──────────────┘
                                         │
                                         │ ai calls
                                         ▼
                            ┌──────────────────────────┐
                            │  Claude Sonnet 4.6 (text)│
                            │  Gemini 2.5 Flash Image  │
                            └──────────────────────────┘
```

## Архитектура AI-слоя

9 типов постов (informative, soft-sell, hard-sell, engagement, story, motivational,
testimonial, hot-take, seasonal) как prompt-стратегии. Планировщик ротирует типы по
заданным пропорциям. Для каждой группы делается smart-spintax — N вариаций текста
из одного поста через повторную генерацию с явной инструкцией переформулировать.

**Антипаттерны AI-слопа** (em-dash, "game-changer", "let's unpack", "in today's
ever-evolving landscape") вшиты в negative-prompt на уровне system message.

**Feedback loop:** thumbs-up посты хранятся в БД и подкидываются как few-shot
примеры в следующие генерации того же типа.

**Brand voice RAG (этап 2):** embeddings прошлых постов, подтягиваем топ-3 в контекст.

## Мультиплатформенность

`app.platforms.base.Platform` — абстрактный интерфейс:

```python
class Platform(ABC):
    id: str  # "facebook", "linkedin", "x", ...
    async def publish(self, post: Post, target: Target) -> PublishResult: ...
    async def list_targets(self) -> list[Target]: ...  # группы / каналы / страницы
    def adapt_content(self, post: Post) -> Post: ...   # длина, хэштеги, формат
```

Новая платформа = новый класс, регистрация в `platforms/registry.py`. Начинаем с
`FacebookPlatform`, которая делегирует постинг в Chrome extension через WebSocket.

## Setup

### Требования
- Python 3.12+
- Node.js 20+
- Chrome или Chromium-based браузер
- API-ключи: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (оба в `.env`)

### Быстрый старт

```bash
# 1. Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp ../.env.example ../.env  # и заполни ключи
uvicorn app.main:app --reload --port 8787

# 2. Dashboard (в новом терминале)
cd dashboard
npm install
npm run dev  # http://localhost:3000

# 3. Extension (в новом терминале)
cd extension
npm install
npm run build
# загрузить dist/ как unpacked extension в chrome://extensions (Developer mode ON)
```

## Roadmap

### Этап 0 — скелет ✅
- [x] Структура репо
- [x] SQLAlchemy модели
- [x] FastAPI-каркас с WebSocket
- [x] Prompt-шаблоны 9 типов постов
- [x] Gemini image-gen
- [x] Chrome extension (Manifest V3, content script скелет)

### Этап 1 — работающий одиночный постинг
- [ ] CRUD business profile через API
- [ ] Website import (Playwright скрейп + Claude саммари)
- [ ] Реальные DOM-селекторы Facebook composer (хрупкая часть)
- [ ] Прикрепление картинок через File API
- [ ] Проверка успеха поста через DOM
- [ ] Ручной запуск "постни сейчас"

### Этап 2 — планировщик и очередь
- [ ] APScheduler с окнами постинга + jitter
- [ ] Review queue (approve / edit / skip)
- [ ] Blackout dates
- [ ] Smart pause на N подряд failed
- [ ] Auto first-comment

### Этап 3 — дашборд
- [ ] Business profile UI
- [ ] Groups / lists UI
- [ ] Content calendar (FullCalendar)
- [ ] Логи с фильтрами
- [ ] Thumbs up/down

### Этап 4 — AI-улучшения
- [ ] Few-shot из фидбека
- [ ] Embedding-RAG по прошлым постам
- [ ] Trend research агент (Claude + web search)
- [ ] UTM-тэги в ссылки

### Этап 5 — multi-platform
- [ ] LinkedIn (через тот же extension или отдельный)
- [ ] X / Bluesky (через API — там они открыты)
- [ ] Threads
- [ ] Reddit (subreddit-aware адаптация)
- [ ] Telegram-каналы (Bot API)

### Этап 6 — если идём в продукт
- [ ] Multi-tenant (row-level security)
- [ ] BYOK для пользователей
- [ ] Биллинг (Stripe)
- [ ] Landing + docs
- [ ] Cloud-вариант для тех, кто не хочет self-host

## Правовые нюансы

Автоматизация постинга в Facebook Groups нарушает Facebook Terms of Service. Для
личного использования с разумными задержками риск бана низкий, но не нулевой.
**Не использовать с основным/ценным аккаунтом.** Для продакшена — обязательно
заметная предупреждалка в UI и ToS.

## Лицензия

TBD. Пока для личного пользования.
