# Overall Architecture

## High-Level Component Diagram

```mermaid
flowchart TB
    subgraph Client["Clients"]
        WebApp["Web / Mobile App"]
        Cron["Cron / Webhook"]
    end

    subgraph API["FastAPI App (app.main)"]
        Routes["API Routes"]
        Routes --> Chat["/api/v1/chat"]
        Routes --> Voice["/api/v1/voice"]
        Routes --> Sync["/api/v1/sync"]
        Routes --> Admin["/api/v1/admin"]
        Routes --> Activity["/api/v1/activity"]
        Routes --> Health["/api/v1/health"]
    end

    subgraph Core["app.core"]
        Settings["settings.py"]
        RateLimiter["rate_limiter.py"]
        Exceptions["exceptions.py"]
    end

    subgraph Services["app.services"]
        RAG["rag_pipeline (generation, retrieval, augmentation)"]
        SummarySvc["chat_summary_service"]
        CronSvc["summary_cron_service"]
        ToneSvc["tone_adaptation_service"]
    end

    subgraph Data["Data & Storage"]
        DB["PostgreSQL + pgvector"]
        Repos["app.db.postgres.repositories"]
        Models["app.db.models"]
    end

    subgraph Ingestion["app.helpers.ingestion_pipeline"]
        PgVector["property/pgvector_store"]
        GenericStore["generic/generic_knowledge_store"]
        Chunker["Chunkers, PDF processors"]
    end

    subgraph Scheduler["app.scheduler"]
        SummaryScheduler["summary_scheduler (daily job)"]
    end

    subgraph External["External Services"]
        OpenAI["OpenAI (LLM, Whisper, Embeddings)"]
        ElevenLabs["ElevenLabs (TTS)"]
        Redis["Redis (optional, rate limits)"]
    end

    WebApp --> Routes
    Cron --> Sync
    Cron --> Admin

    Chat --> RAG
    Chat --> Repos
    Voice --> RAG
    Voice --> OpenAI
    Voice --> ElevenLabs
    Sync --> Ingestion
    Admin --> SummarySvc
    Admin --> Repos
    Activity --> Repos
    Health --> DB
    Health --> OpenAI
    Health --> PgVector

    RAG --> PgVector
    RAG --> GenericStore
    RAG --> OpenAI
    SummarySvc --> Repos
    SummarySvc --> OpenAI
    CronSvc --> SummarySvc
    SummaryScheduler --> CronSvc

    Repos --> DB
    PgVector --> DB
    Ingestion --> DB
    Ingestion --> OpenAI
    RateLimiter --> Redis
```

---

## Layer Overview

```mermaid
flowchart LR
    subgraph Presentation["Presentation"]
        A[API Routes]
    end
    subgraph Business["Business Logic"]
        B[RAG Pipeline]
        C[Chat Summary Service]
        D[Tone Adaptation]
    end
    subgraph DataLayer["Data Layer"]
        E[Repositories]
        F[Vector Stores]
    end
    subgraph Infrastructure["Infrastructure"]
        G[PostgreSQL]
        H[Redis]
        I[OpenAI / ElevenLabs]
    end

    A --> B
    A --> C
    A --> D
    B --> E
    B --> F
    C --> E
    D --> E
    E --> G
    F --> G
    RateLimiter["Rate limiter"] --> H
    B --> I
```

---

## Tech Stack

| Layer            | Technology                                    |
| ---------------- | --------------------------------------------- |
| API              | FastAPI, Pydantic                             |
| Rate limiting    | SlowAPI (Redis or in-memory)                  |
| Database         | PostgreSQL (SQLAlchemy sync + async)          |
| Vector search    | pgvector (in PostgreSQL)                      |
| LLM & embeddings | OpenAI (e.g. gpt-4o, text-embedding-3-small)  |
| Voice            | OpenAI Whisper (transcribe), ElevenLabs (TTS) |
| Background       | In-app asyncio task (summary scheduler)       |

---

## Configuration

Key settings live in **`app/core/settings.py`** (Pydantic, `.env`, case-insensitive):

| Setting            | Env var                                 | Default             | Purpose               |
| ------------------ | --------------------------------------- | ------------------- | --------------------- |
| Database           | `DATABASE_URL`                          | (required)          | PostgreSQL connection |
| Rate limiting      | `RATE_LIMIT_ENABLED`                    | `false`             | Enable SlowAPI limits |
| Rate limit default | `RATE_LIMIT_PER_MINUTE`                 | `60`                | Global default limit  |
| Redis              | `REDIS_URL`                             | (empty → in-memory) | Rate limit storage    |
| Pool / DB          | `db_pool_size`, `db_max_overflow`, etc. | (see settings)      | Engine/pool tuning    |

Other env (used outside Pydantic settings):

- **OpenAI:** `OPENAI_API_KEY`, `OPENAI_MODEL`
- **ElevenLabs:** `ELEVENLABS_API_KEY`
- **Sync:** `WEBHOOK_SECRET`, `REQUIRE_WEBHOOK_SECRET`
- **Scheduler:** `SUMMARY_CRON_HOUR`, `SUMMARY_CRON_MINUTE`, `ENABLE_INAPP_SUMMARY_CRON`
- **RAG:** `TONE_ADAPTATION_MIN_USER_MESSAGES`, `DEBUG`, generic PDF limits, etc.

---

## Route Mounting (main.py)

Routers are included with their own prefix:

- `chat_router` → `/api/v1/chat`
- `voice_router` → `/api/v1/voice`
- `sync_router` → `/api/v1/sync`
- `admin_router` → `/api/v1/admin`
- `activity_router` → `/api/v1/activity`
- `health_router` → `/api/v1/health`

Lifespan: starts **summary scheduler** task; on shutdown cancels it and calls **close_db()**.
