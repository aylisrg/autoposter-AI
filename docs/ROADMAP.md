# Autoposter AI — Roadmap

> Локальный self-hosted AI-автопостер. Аналог PilotPoster с открытой
> архитектурой и встроенным SMM-аналитиком, который улучшает контент-стратегию
> на основе реальных метрик.

## Видение

Один продукт, который:

1. **Сам строит контент-план** через AI-агента (Planner) на основе бизнес-профиля и целей.
2. **Принимает медиа** от пользователя (фото/видео) и привязывает их к слотам плана.
3. **Согласует целевые группы/каналы** через AI-агента (Targets) — скрейпит, классифицирует, предлагает сегментацию, человек подтверждает.
4. **Постит «как человек»** — реальная браузерная сессия + симуляция typing/scroll/idle, jitter в окнах постинга, smart pause.
5. **Анализирует и самообучается** — собирает метрики, еженедельный AI-отчёт, авто-корректировка `post_type_ratios`, `posting_window`, тона, длины, few-shot примеров.

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, APScheduler, Anthropic SDK, Google Gemini SDK |
| Extension | TypeScript, Manifest V3, Vite |
| Dashboard | Next.js 15, Tailwind, shadcn/ui, FullCalendar |
| AI | Claude Sonnet 4.6 (writer/planner/analyst), Claude Haiku 4.5 (lightweight tasks), Gemini 2.5 Flash Image |
| Storage | SQLite + локальный media store; Fernet encryption для секретов |

## Платформы v1

- **Facebook Groups** — через Chrome extension (DOM automation)
- **Instagram** — через Meta Graph API (+ extension fallback)
- **Threads** — через Meta Threads API

Multi-platform абстракция (`backend/app/platforms/base.py`) уже готова к расширению на VK, Telegram, LinkedIn, X, Reddit.

## Архитектура

```
Dashboard (Next.js)
    │ HTTP / SSE
    ▼
Backend (FastAPI)
  ├─ Agents: Planner | Target | Writer | Analyst | Optimizer
  ├─ Services: Media | Scheduler | Humanizer | Few-shot Store
  ├─ Platforms: Facebook | Instagram | Threads
  └─ Core: SQLAlchemy ORM | APScheduler | Anti-slop
    │ WebSocket                    │ HTTPS
    ▼                              ▼
Chrome Extension              Meta Graph API
    │
    ▼
Facebook (DOM)
```

## Дорожная карта

Полный план разделён на **9 milestones** (M0–M8). Каждый = отдельный milestone в GitHub
Issues. Issues помечены префиксом `[M0]…[M8]` в title.

| # | Milestone | Цель | Длительность |
|---|-----------|------|--------------|
| **M0** | Foundation Hardening | Скелет → ручной post через dashboard | 1 нед |
| **M1** | Content Planner Agent | AI строит план, юзер редактирует | 1.5 нед |
| **M2** | Media Library | Загрузка/привязка медиа к слотам | 1 нед |
| **M3** | Targets Agent | AI собирает группы, юзер согласует | 1 нед |
| **M4** | Human-Like Posting | Симуляция человека, anti-detection | 1.5 нед |
| **M5** | Review & Approval | Очередь ревью + thumbs feedback | 3-4 дня |
| **M6** | SMM Analyst (auto-loop) ⭐ | Метрики + AI-инсайты + auto-tune | 2 нед |
| **M7** | Multi-Platform: IG + Threads | Параллельный кросс-постинг | 1.5 нед |
| **M8** | Production Polish | Auth, encryption, Docker, docs | 1 нед |

**Sequencing:** M0 → M1 → M2 → M3 → (M4 ∥ M5) → M6 → M7 → M8.
Полная оценка: **8–10 недель** соло-разработки.

---

### M0 — Foundation Hardening

- [x] REST CRUD endpoints: BusinessProfile, Target, Post, Feedback (`backend/app/api/`)
- [x] APScheduler стартует с приложением; job runner для scheduled posts
- [x] Dashboard skeleton: Next.js 15 + Tailwind + shadcn/ui (Profile / Targets / Compose / Queue)
- [x] Реальные FB DOM селекторы (с фоллбеком и smoke-тестом через popup)
- [x] Image attach через File API в extension + backend `/api/media/upload`
- [x] Verification: `docs/M0_CHECKLIST.md` + pytest smoke suite (11 зелёных)

### M1 — Content Planner Agent

- [x] Модели `ContentPlan` + `PlanSlot`
- [x] `PlannerAgent` (`backend/app/agents/planner.py`)
- [x] UI: страница «Контент-план» с calendar view + drag-n-drop
- [x] Conversational refinement: чат с Planner для итераций
- [x] Verification: pytest suite для planner (12 тестов) + `/api/plans/generate` end-to-end

### M2 — Media Library

- [x] Модель `MediaAsset` (path, mime, dimensions, ai_tags, ai_caption)
- [x] Upload endpoint: multipart + Pillow для dimensions (tus отложен — single-user localhost)
- [x] AI tagging при upload (Claude Vision) — caption + 3-8 tags
- [~] Транскод видео для IG/Threads (ffmpeg) — отложено до M7 (video upload тоже)
- [x] UI: галерея + auto-suggest top-3 по tag-overlap в slot inspector
- [x] Verification: 11 pytest + ручной flow upload → tag → attach

### M3 — Targets Agent

- [x] Extension: скрейп joined (list_groups) и suggested (list_suggested_groups) groups
- [~] IG/Threads: list manage-able accounts через Meta Graph — отложено до M7
- [x] `TargetAgent`: relevance_score (0–100) + reasoning per группа
- [x] Авто-сегментация в `target_lists` (Claude clustering → Target.list_name)
- [x] UI: фильтры (status + list), bulk approve/reject, AI-кнопки score/cluster
- [x] Verification: 13 pytest (agent + API + extension bridge stub)

### M4 — Human-Like Posting Engine

- [x] `HumanizerProfile` (typing_wpm, mistake_rate, pauses, scroll behavior, jitter)
- [x] Extension: character-by-character typing with QWERTY-typos + correction,
      bezier mouse moves on hover, idle scroll before composer open
- [x] Scheduler с jitter ±N мин (`apply_schedule_jitter` в `/api/posts/.../schedule`),
      blackout dates — сам per-day check в tick, per-day rate-limit уже из M0
- [x] Smart pause: N подряд failed → пауза M мин + причина
- [x] Session health: checkpoint/captcha/2FA и shadow-ban patterns detect → стоп
- [x] Shadow-ban heuristics (`SHADOW_BAN_PATTERNS` + `SessionHealthStatus`)
- [~] IG/Threads humanizer не нужен — отложен до M7 (API-based posting)
- [x] Verification: 22 pytest (классификация / jitter / pause / blackout / API)

### M5 — Review & Approval Flow

- [ ] `ReviewQueue` (pending → approved/edited/rejected)
- [ ] UI Queue: per-platform preview, inline-edit, regenerate variant, thumbs up/down
- [ ] «Approve all» / «Approve selected»
- [ ] Auto-approve toggle для доверенных типов после N успешных
- [ ] Verification: 10 постов в очереди — апрув 7, эдит 2, скип 1

### M6 — SMM Analyst Agent + Auto-Improving Loop ⭐

- [ ] **Metrics Collector**:
  - FB: extension скрейпит likes/comments/shares/reach через 1ч/24ч/7д
  - IG/Threads: Meta Graph Insights API
  - Модель `PostMetrics`
- [ ] **Analyst Agent** (weekly cron):
  - Структурированный отчёт: top/bottom performers, паттерны (тип/время/длина/тон)
  - Гипотезы с scoring
- [ ] **Optimizer**:
  - Mutations: post_type_ratios, posting_window, tone, length, emoji_density, few-shot store
  - Human-in-loop для крупных изменений; мелкие — авто
- [ ] **Few-shot Store**: top 20 постов как примеры в Writer
- [ ] **A/B framework** при низкой уверенности
- [ ] **Dashboard Analytics**: KPI, графики engagement, before/after
- [ ] Verification: 4 недели данных → отчёт → 2 авто-изменения → метрика недели сверена

### M7 — Multi-Platform: Instagram + Threads

- [ ] `InstagramPlatform` (Meta Graph API): photo, carousel, reels, stories
- [ ] `ThreadsPlatform` (Meta Threads API)
- [ ] `adapt_content`: длина, hashtag density, формат per platform
- [ ] OAuth flow для Meta App в dashboard
- [ ] Cross-posting: один PlanSlot → во все платформы с адаптацией
- [ ] Verification: один план → одновременная публикация во все 3 платформы

### M8 — Production Polish

- [ ] PIN-auth для dashboard
- [ ] Encryption at rest для cookies/API keys (Fernet)
- [ ] Backups: SQLite + media → daily zip
- [ ] Docker Compose: backend + nginx + scheduler
- [ ] Observability: structlog, request IDs, `/metrics` для Prometheus
- [ ] Документация: install, troubleshooting, ban-FAQ
- [ ] Verification: чистый docker-compose install + golden path E2E

---

## Конкурентный анализ

| Продукт | Сильные стороны | Слабые стороны | Чем отличаемся |
|---------|----------------|----------------|----------------|
| **PilotPoster** ($47/мес) | FB Groups, browser-based, AI gen, ban-safe | Только FB, cloud-only, фикс. логика, $47/мес × ∞ | Локальный, multi-platform, открытый код, AI-аналитик |
| **Buffer** | Простота, много платформ | AI слабый, нет FB Groups | Глубже AI + self-hosted |
| **Hootsuite** | Enterprise, OwlyWriter AI | $199+/мес | Дешевле в 100× при self-host |
| **Metricool** | Аналитика | Аналитика без autoloop | У нас autoloop с авто-tuning |
| **Publer** | Brand voice training | Нет авто-улучшений | Brand voice + RLHF-style loop |
| **SMMplanner / LiveDune / SocPoster** | RU-стек, VK/TG | Нет AI-агента-аналитика | RU-стек на M9+ через тот же Platform interface |

## Принципы качества AI-контента

- **Anti-slop hard rules** в system prompt: запрет em-dash, banned-buzzwords (`game-changer`, `let's unpack`, `paradigm shift`, …), generic openings
- **Per-type prompt strategy**: 9 типов (informative / soft_sell / hard_sell / engagement / story / motivational / testimonial / hot_take / seasonal) — каждый со своей стратегической инструкцией
- **Smart spintax**: для каждой группы — отдельная переформулировка, чтобы избежать дубликатов
- **Brand voice RAG** (M2+): embeddings прошлых одобренных постов
- **Few-shot evolution** (M6): топ-метрик посты автоматически становятся примерами

## Юридические нюансы

Автоматизация постинга в Facebook Groups нарушает Facebook ToS. Для личного
использования с разумными задержками риск бана низкий, но не нулевой.
**Не использовать с основным/ценным аккаунтом.** В UI и docs — заметная
предупреждалка.

## Как следить за прогрессом

- **GitHub Issues** с префиксом `[M0]…[M8]` — детальные таски
- **GitHub Milestones** (создать вручную в UI) — группировка по эпикам
- **Project board** «Autoposter AI Roadmap» (создать вручную) — Kanban
- **Этот файл** — обзор-зеркало, обновляется при изменении эпиков
