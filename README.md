# Unreserved - FastAPI + SQLAlchemy + Alembic

This project uses FastAPI with SQLAlchemy ORM and Alembic for database migrations.

## Setup

1. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On macOS/Linux
   # or
   venv\Scripts\activate  # On Windows
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment variables:**
   The `.env` file contains your database connection string. Make sure it's configured correctly.

## Database Migrations

### Initial Setup

If you have an existing database and want to generate models from it:
```bash
python scripts/reflect_schema.py
```

### Creating Migrations

1. **Create a new migration:**
   ```bash
   alembic revision --autogenerate -m "description of changes"
   ```

2. **Review the generated migration file** in `alembic/versions/` before applying.

3. **Apply migrations:**
   ```bash
   alembic upgrade head
   ```

4. **Rollback a migration:**
   ```bash
   alembic downgrade -1
   ```

### Migration Commands

- `alembic current` - Show current revision
- `alembic history` - Show migration history
- `alembic upgrade head` - Apply all pending migrations
- `alembic downgrade base` - Rollback all migrations

## Running the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   └── db/
│       ├── __init__.py
│       ├── base.py          # SQLAlchemy Base
│       ├── session.py       # Database session
│       └── models/          # SQLAlchemy models
│           └── __init__.py
├── alembic/                 # Alembic migrations
│   ├── versions/            # Migration files
│   ├── env.py
│   └── script.py.mako
├── alembic.ini              # Alembic configuration
├── requirements.txt
└── .env                     # Environment variables
```

## Next Steps

1. Add your SQLAlchemy models to `app/db/models/` based on your ERD
2. Import them in `app/db/models/__init__.py`
3. Create your first migration: `alembic revision --autogenerate -m "initial schema"`
4. Review and apply: `alembic upgrade head`

