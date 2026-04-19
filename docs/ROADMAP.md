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

- [x] Reuse `PostStatus.PENDING_REVIEW`; `generate()` роутит туда при
      `review_before_posting=true` и отсутствии типа в `auto_approve_types`
- [x] UI `/review`: inline-edit, regenerate, thumbs up/down, approve→DRAFT /
      approve→SCHEDULE(+5 мин), reject с reason, bulk approve
- [x] `POST /api/posts/{id}/approve`, `/reject`, `/regenerate`,
      `/review/approve-all`, `GET /api/posts/review/pending`
- [x] Auto-approve allow-list: `BusinessProfile.auto_approve_types: list[str]`
      (Profile page — comma-separated input)
- [x] Verification: 12 pytest (PENDING_REVIEW роутинг, auto-approve, approve/
      reject/regenerate/approve-all, thumbs feedback)

### M6 — SMM Analyst Agent + Auto-Improving Loop ⭐

- [x] **Metrics Collector**: модель `PostMetrics` (1h/24h/7d), сервис
      `services/metrics.py`, `FacebookPlatform.fetch_metrics` + extension
      `fetch_metrics` handler (aria-label scraping). Hourly scheduler tick
      `collect_metrics_tick`
- [x] **Analyst Agent** (`agents/analyst.py`): Claude Sonnet, structured JSON
      report → AnalystReport; weekly cron (Sunday 21:00 UTC)
- [x] **Optimizer**: `OptimizerProposal` с confidence + auto-apply для safe
      fields (posting_window_*, post_type_ratios, emoji_density,
      posts_per_day) при confidence ≥ 0.75; остальное — human-in-loop
- [x] **Few-shot Store**: `FewShotExample` пополняется top-N по
      engagement_score; `_fetch_few_shot_examples` теперь тянет отсюда,
      fallback к thumbs-up
- [~] A/B framework — отложен до пост-MVP (proposals + Feedback loop уже
      дают функциональный аналог)
- [x] **Dashboard Analytics** (`/analytics`): KPI-панель, top/bottom
      performers, Optimizer proposals с apply/reject, последние Analyst
      reports
- [x] Verification: 13 pytest (collect windows, engagement_score, summary,
      top/bottom, persist+auto-apply, apply/reject endpoints, few-shot
      trim, analyst /generate)

### M7 — Multi-Platform: Instagram + Threads

- [x] `InstagramPlatform` (Meta Graph API v21.0, two-step container flow):
      photo + caption; carousel/reels/stories отложены
- [x] `ThreadsPlatform` (Meta Threads API v1.0): text-only + text+image;
      video отложен
- [x] `adapt_content`: IG — 2200 char cap + 30 hashtag cap; Threads — 500
      char cap на word boundary; FB — без изменений
- [x] `PlatformCredential` model + OAuth flow (`/api/meta/oauth/url` +
      `/api/meta/oauth/callback` → long-lived token + probe /me/accounts →
      upsert IG + Threads credentials)
- [x] Dashboard `/platforms` page с OAuth кнопкой + manual paste fallback
- [x] Platform registry (`backend/app/platforms/registry.py`) —
      scheduler / posts API / metrics service дергают `get_platform(id)`
- [x] Cross-posting: `target_ids` могут спанить несколько платформ; scheduler
      + publish_now дергают нужный Platform по `target.platform_id` и
      применяют `adapt_content` per variant
- [x] Verification: 22 pytest (adapt_content, publish mocked, metrics,
      OAuth URL, credential CRUD, list_targets)

### M8 — Production Polish

- [x] PIN-auth для dashboard (`DashboardAuthMiddleware` + `/api/auth/login`
      cookie + `AuthGate` UI; empty PIN = dev default, disabled)
- [x] Fernet encryption at rest для `PlatformCredential.access_token`
      (hybrid property `encrypt_str` / `decrypt_str`, auto-generated key в
      `data/.fernet.key`)
- [x] Backups: SQLite `.backup()` snapshot + media → zip в `data/backups/`;
      daily cron 03:00 UTC + `/api/admin/backup` on-demand; retention
      `BACKUP_KEEP_DAYS`
- [x] Docker Compose: `Dockerfile` (python:3.12-slim + uvicorn) +
      `docker-compose.yml` (backend only, dashboard/extension остаются host)
- [x] Observability: `RequestContextMiddleware` → request-id header + access
      log + `http_requests_total` Prometheus counters; `GET /metrics`
      exposition endpoint
- [x] Документация: `docs/INSTALL.md`, `docs/TROUBLESHOOTING.md`,
      `docs/BAN_FAQ.md`; `.env.example` расширен M7/M8 settings
- [x] Verification: 17 new pytest (Fernet roundtrip + passthrough,
      credential encryption, auth enabled/disabled/header/cookie, metrics
      endpoint, request-id header, backup zip + prune); 133 total green

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
