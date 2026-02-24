# Database Session: Current vs Standard and Change Plan

This document compares the current `app/db/session.py` with the standard `connection.py` pattern, lists possible changes, their complexity, and how to implement them without breaking the app.

---

## 1. Current vs Standard Comparison

| Aspect | Current (`app/db/session.py`) | Standard (`connection.py`) |
|--------|------------------------------|---------------------------|
| **API** | Sync | Async |
| **Engine** | `create_engine` (sync), created at import | `create_async_engine`, lazy via `get_async_engine()` |
| **Session** | `Session`, `sessionmaker` → `SessionLocal` at module level | `AsyncSession`, `async_sessionmaker` via `get_session_maker()` |
| **get_db** | `Generator[Session, None, None]`; retries, backoff, pool invalidation, in-transaction check | `AsyncGenerator[AsyncSession, None]`; simple commit/rollback/close |
| **Config** | `DatabaseSettings` (Pydantic) in same file; `_get_database_url()`; constants (POOL_SIZE, etc.) in code | Central `app.core.settings`; `get_database_url()`; pool settings from env (DB_POOL_SIZE, APP_ENV, etc.) |
| **Pool** | Always QueuePool with fixed constants | QueuePool in production, NullPool in dev (via `get_engine_kwargs()`) |
| **URL** | Normalized for psycopg, prepare_threshold, keepalives, sslmode in connect_args | Plain URL from settings |
| **PG timeouts** | Event listener: statement_timeout, lock_timeout on connect | None |
| **Lifecycle** | `close_db()`, `check_db_connection()`, `init_db()` (added) | `init_db()`, `close_db()`, `check_db_connection()` |
| **Base** | In `app.db.base` | `declarative_base()` in same module |

---

## 2. Changes You Can Make (With Complexity and Risk)

### Change 1: Centralise config (settings module + env-based DB settings)

**What:** Move database URL and pool settings to a central settings module (e.g. `app/core/settings.py`) and read pool size, overflow, recycle, pre_ping, and env (e.g. `APP_ENV`) from environment variables.

| | Current | Standard |
|--|--------|----------|
| URL | `_get_database_url()` using `os.getenv` + `DatabaseSettings` in session.py | `settings.get_database_url()` from central settings |
| Pool size / overflow / recycle / pre_ping | Hardcoded constants in session.py | From settings (e.g. `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`, `DB_POOL_PRE_PING`) |
| Env-based behaviour | None | `APP_ENV` (e.g. production vs dev) drives pool class (QueuePool vs NullPool) |

**Steps:**

1. Create `app/core/settings.py` (or add to existing config) with:
   - `get_database_url()` (from `DATABASE_URL` env).
   - Optional: `APP_ENV`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`, `DB_POOL_PRE_PING` (with sensible defaults).
2. In `app/db/session.py`:
   - Replace `_get_database_url()` and `DatabaseSettings` with a call to `settings.get_database_url()`.
   - Replace constants with values from settings (or keep constants as defaults if a setting is missing).
3. Optionally: use `APP_ENV` to choose NullPool in dev and QueuePool in production (like the standard).

**Complexity:** Low–medium (one new or extended module, session.py touched in a few places).

**Risk of breaking:** Low if you keep the same default values and only switch the source (env vs constants). Slightly higher if you introduce NullPool in dev (behaviour change).

**Recommendation:** Do this if you want env-based tuning and a single place for DB config. Keep current default numbers when introducing settings.

---

### Change 2: Lazy engine creation

**What:** Create the engine only when first needed (e.g. in a `get_engine()` function) instead of at import time.

| | Current | Standard |
|--|--------|----------|
| Engine | Created at module load (`engine = create_engine(...)`). | Created on first use via `get_async_engine()`. |

**Steps:**

1. In `app/db/session.py`, replace top-level `engine = create_engine(...)` with a function, e.g. `def get_engine() -> Engine:` that creates the engine once (e.g. with a module-level `_engine = None` and `if _engine is None: _engine = create_engine(...)`).
2. Replace every use of `engine` with `get_engine()` (or keep a single `engine = get_engine()` at the end of the module for backward compatibility so existing `from app.db.session import engine` still works).
3. In `close_db()`, dispose the engine from the getter and optionally set the cached reference to `None` so the next use creates a new engine (optional; see note below).

**Complexity:** Low.

**Risk of breaking:** Low. All current code uses `engine` and `SessionLocal`; as long as they still get the same engine (e.g. via a getter or a single assignment after lazy creation), behaviour is unchanged. Only risk is if something disposes the engine and then code still holds the old reference.

**Recommendation:** Optional. Main benefit is delaying DB connection until first use and clearer lifecycle; not required for correctness.

---

### Change 3: Use central settings only for URL (minimal config change)

**What:** Introduce only `get_database_url()` in a central place and keep all pool/timeout logic and constants in session.py.

| | Current | Standard |
|--|--------|----------|
| URL source | session.py (`_get_database_url()` + `DatabaseSettings`) | Central settings (`get_database_url()`) |

**Steps:**

1. Add `app/core/settings.py` with a single function or settings class that reads `DATABASE_URL` (from env or .env) and exposes `get_database_url()`.
2. In `app/db/session.py`, remove `DatabaseSettings` and `_get_database_url()`, and use `from app.core.settings import get_database_url` (or equivalent) where the URL is needed.
3. Keep all pool constants, connect_args, and URL normalization in session.py.

**Complexity:** Low.

**Risk of breaking:** Low. Only the source of the URL string changes; behaviour stays the same.

**Recommendation:** Good first step if you want central config without touching pool behaviour.

---

### Change 4: Align health check with `check_db_connection()`

**What:** Use the existing `check_db_connection()` from session.py in the health route instead of (or in addition to) opening a session and running a query manually.

| | Current | Standard |
|--|--------|----------|
| Health DB check | Health route uses `SessionLocal()` and/or `engine.connect()` and runs a query. | Standard has `check_db_connection()` that runs `SELECT 1` and returns bool. |

**Steps:**

1. In `app/api/v1/routes/health.py`, import `check_db_connection` from `app.db.session`.
2. Where you currently check DB (e.g. “database” in services), call `check_db_connection()` instead of creating a session and executing `SELECT 1` (or use it in addition for a simple up/down check).
3. Keep any extra checks (e.g. table existence) as they are, using a session if needed.

**Complexity:** Low.

**Risk of breaking:** Low. Same check, different implementation; response shape can stay the same.

**Recommendation:** Worth doing for consistency and reuse.

---

### Change 5: Async migration (sync → async engine and sessions)

**What:** Switch to async SQLAlchemy: `create_async_engine`, `AsyncSession`, `async_sessionmaker`, and async `get_db` yielding `AsyncSession`.

| | Current | Standard |
|--|--------|----------|
| Engine/Session | Sync `Engine`, `Session`, `sessionmaker` | Async `create_async_engine`, `AsyncSession`, `async_sessionmaker` |
| get_db | Sync generator yielding `Session` | Async generator yielding `AsyncSession` |
| Route handlers | Sync `Depends(get_db)` → sync `Session` | Async handlers with `Depends(get_db)` → `AsyncSession`; all DB calls must use `await` |

**Steps:**

1. Replace `create_engine` with `create_async_engine`, and session factory with `async_sessionmaker(..., class_=AsyncSession)`.
2. Change `get_db` to an async generator that yields `AsyncSession`; use `async with session_maker() as session: yield session` and handle commit/rollback/close in the async context.
3. Update every route and service that uses the session: ensure they are async and use `await` for all DB operations (e.g. `await session.execute(...)`).
4. Replace all direct `SessionLocal()` usage with an async equivalent (e.g. get a session from the async factory and use it within an async context).
5. Keep URL normalization and connect_args compatible with the async driver (e.g. use `postgresql+asyncpg` or the async equivalent of your current driver and adjust connect_args if needed).
6. Optionally add `init_db` / `close_db` for async engine (e.g. `async with engine.begin()` for init, `await engine.dispose()` for close).

**Complexity:** High. Every file that touches the DB must be updated (routes, services, helpers, tests).

**Risk of breaking:** High. Easy to miss a call site or mix sync/async; tests and all entry points must be verified.

**Recommendation:** Only do this if you need better concurrency or want to align with an async-first stack. Not required for correctness or current behaviour.

---

### Change 6: Environment-based pool (NullPool in dev, QueuePool in prod)

**What:** Use NullPool in development and QueuePool in production, driven by something like `APP_ENV`.

| | Current | Standard |
|--|--------|----------|
| Pool | Always QueuePool with fixed size/overflow. | QueuePool in production; NullPool in dev. |

**Steps:**

1. Introduce `APP_ENV` (e.g. from env, default `"development"`).
2. In session.py (or in your engine getter), when creating the engine:
   - If `APP_ENV == "production"`: use `QueuePool` with your size/overflow/recycle/pre_ping (from constants or settings).
   - Else: use `NullPool` (no pooling).
3. Ensure all other engine options (URL, connect_args, events) are unchanged.

**Complexity:** Low.

**Risk of breaking:** Low–medium. NullPool changes behaviour (new connection per use, no reuse). Usually fine in dev; only risk is if some script or test assumes long-lived pooled connections.

**Recommendation:** Optional. Useful to avoid holding connections in dev; do after or with Change 1 (central config).

---

## 3. What Not to Change (Keep Current Behaviour)

- **Retries and backoff in get_db** – Keep. Standard has no retries; yours improve resilience.
- **Pool invalidation on connection errors** – Keep. Prevents reuse of bad connections.
- **PostgreSQL timeouts (statement_timeout, lock_timeout)** – Keep. Good for stability.
- **URL normalization and connect_args (psycopg, keepalives, sslmode, prepare_threshold)** – Keep. Important for production.
- **Sync API** – Keep unless you deliberately do Change 5 (async migration).
- **Base in app.db.base** – No change needed; standard’s “Base in same module” is just a different layout.

---

## 4. Suggested Order of Implementation

1. **Safe and quick:** Change 4 (use `check_db_connection()` in health).
2. **Low risk:** Change 3 (central URL only) or Change 1 (full central config + env-based pool settings).
3. **Optional:** Change 2 (lazy engine), then Change 6 (NullPool in dev) if you want env-based behaviour.
4. **Only if needed:** Change 5 (async migration); plan and test thoroughly.

---

## 5. Summary Table

| Change | Complexity | Break risk | Suggested |
|--------|------------|------------|-----------|
| 1. Central config (settings + env DB vars) | Low–medium | Low | Yes, for maintainability |
| 2. Lazy engine | Low | Low | Optional |
| 3. Central URL only | Low | Low | Yes, minimal first step |
| 4. Health uses check_db_connection() | Low | Low | Yes |
| 5. Async migration | High | High | Only if you need async |
| 6. NullPool in dev | Low | Low–medium | Optional, with Change 1 |

Implementing 3 and 4 gives you alignment with the standard where it matters most (config and health) without changing behaviour. Adding 1 and optionally 6 gives env-based tuning and dev/prod pool behaviour similar to the standard, still without moving to async.
