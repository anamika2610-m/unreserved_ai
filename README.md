# Unreserved Property Chat API

A sophisticated **Retrieval-Augmented Generation (RAG)** chatbot API for property listings, powered by OpenAI GPT-4o and PostgreSQL with pgvector. This system provides intelligent, context-aware responses about property listings and general real estate knowledge.

## 🚀 Features

### Core Capabilities
- **Property-Specific Queries**: Answer questions about specific property listings (pricing, features, location, amenities)
- **Generic Real Estate Knowledge**: Answer general questions about real estate laws, processes, and regulations in Victoria, Australia
- **Conversation History**: Maintains context across multiple messages in a conversation
- **Voice Input**: Transcribe voice to text using OpenAI Whisper-1 model
- **Location-Aware**: Finds nearby properties and amenities with Google Maps integration
- **Intelligent Fallback**: Cascading fallback from property data → property PDFs → generic knowledge → vendor contact

### Technical Features
- **Vector Search**: Semantic search using OpenAI embeddings (1536 dimensions)
- **Dual Vector Stores**: Separate stores for property-specific and generic knowledge
- **PDF Processing**: Extracts and indexes text from property-specific PDFs and generic documents
- **Health Monitoring**: Comprehensive health checks for all critical services
- **Webhook Support**: Sync vector embeddings when listings are updated

## 📋 Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Data Ingestion](#data-ingestion)
- [Development](#development)
- [Recent Updates](#recent-updates)

## 🏗️ Architecture

### System Overview

```
┌─────────────┐
│   Client    │
│  (Web/Mobile)│
└──────┬──────┘
       │ HTTP/WebSocket
       ▼
┌─────────────────────────────────────┐
│      FastAPI Application             │
│  ┌───────────────────────────────┐  │
│  │  API Routes                   │  │
│  │  - Chat                       │  │
│  │  - Voice Transcription       │  │
│  │  - Health Checks              │  │
│  │  - Sync                      │  │
│  └───────────┬───────────────────┘  │
│              │                       │
│  ┌───────────▼───────────────────┐  │
│  │  RAG Pipeline                 │  │
│  │  - Query Preprocessing        │  │
│  │  - Vector Retrieval          │  │
│  │  - Context Augmentation      │  │
│  │  - LLM Generation            │  │
│  │  - Response Postprocessing   │  │
│  └───────────┬───────────────────┘  │
└──────────────┼───────────────────────┘
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │   OpenAI     │
│  + pgvector  │  │  (GPT-4o +   │
│              │  │  Embeddings) │
└──────────────┘  └──────────────┘
```

### Data Flow

1. **User Query** → Preprocessing (extract listing_id, detect query type)
2. **Query Classification** → Property-specific or Generic
3. **Vector Retrieval** → Search relevant chunks from appropriate store
4. **Context Augmentation** → Enrich with location data, nearby properties, amenity links
5. **LLM Generation** → Generate response using GPT-4o
6. **Response Formatting** → Add metadata, nearby properties, amenity links
7. **Conversation Storage** → Save message to database

### Vector Stores

- **`property_embeddings`**: Property-specific data (JSON chunks + property PDFs)
- **`generic_knowledge`**: Generic real estate knowledge (legislation, guides, processes)

## 📦 Prerequisites

- **Python**: 3.9+
- **PostgreSQL**: 14+ with `pgvector` extension
- **OpenAI API Key**: For LLM and embeddings
- **Database**: Access to property listings database

## 🔧 Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Unreserved
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Database

Ensure PostgreSQL is running with the `pgvector` extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. Run Migrations

```bash
alembic upgrade head
```

## ⚙️ Configuration

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/dbname

# OpenAI
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o  # Optional, defaults to gpt-4o

# Optional: Webhook Secret for Sync Endpoint
VECTOR_SYNC_WEBHOOK_SECRET=your-secret-here
```

## 🚀 Running the Application

### Development Mode

```bash
# Using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using the provided script
./infra/scripts/run_api.sh
```

### Production Mode

```bash
# Using Docker (if configured)
docker-compose up -d

# Or using gunicorn with uvicorn workers
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Verify Installation

```bash
# Check health
curl http://localhost:8000/api/v1/health

# View API documentation
open http://localhost:8000/docs
```

## 📡 API Endpoints

### Chat

#### `POST /api/v1/chat/message`

Send a message to the chatbot.

**Request:**
```json
{
  "question": "What is the price of this property?",
  "listing_id": "950b945a-5604-49a0-9cf9-3d3c16cf9c1a",
  "user_id": "22c91760-ac98-4d05-b545-cdb5a7a8d23f",
  "conversation_id": "optional-existing-conversation-id"
}
```

**Response:**
```json
{
  "answer": "The asking price for this property is **$399,000**...",
  "conversation_id": "6a57903b-0e5d-4b60-8d50-0df627693943",
  "nearby_properties": [...],
  "amenity_links": [...],
  "timestamp": "2026-01-15T10:30:00"
}
```

#### `GET /api/v1/chat/history/{conversation_id}`

Get conversation history.

### Voice Transcription

#### `POST /api/v1/voice/transcribe`

Transcribe audio file to text.

**Request:** `multipart/form-data`
- `file`: Audio file (mp3, mp4, wav, webm, etc.)
- `listing_id`: (optional)
- `user_id`: (optional)

**Response:**
```json
{
  "text": "What is the price of this property?",
  "language": "english",
  "duration": 3.5
}
```

#### `POST /api/v1/voice/transcribe-and-chat`

Transcribe audio and send to chat endpoint in one request.

**Request:** `multipart/form-data`
- `file`: Audio file
- `listing_id`: (optional)
- `user_id`: (optional)
- `conversation_id`: (optional)

**Response:**
```json
{
  "transcription": {
    "text": "What is the price?",
    "language": "english",
    "duration": 2.1
  },
  "conversation_id": "...",
  "user_message": {...},
  "chat_response": {...}
}
```

### Health Check

#### `GET /api/v1/health`

Comprehensive health check for all services.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-01-15T10:30:00",
  "services": {
    "internet_connectivity": {"status": "ok", "message": "Google is reachable"},
    "database": {"status": "ok", "message": "Database is reachable", "pgvector_installed": true},
    "llm_api": {"status": "ok", "message": "LLM API is reachable", "model": "gpt-4o"},
    "vector_store": {
      "status": "ok",
      "property_embeddings": {"table_exists": true, "chunk_count": 1234},
      "generic_knowledge": {"table_exists": true, "chunk_count": 567}
    },
    "embedding_service": {"status": "ok", "model": "text-embedding-3-small", "embedding_dimension": 1536}
  }
}
```

### Sync

#### `POST /api/v1/sync/listings` (recommended)

Trigger vector embedding sync.

**Security Note**: 
- **Development**: Works without secret if `VECTOR_SYNC_WEBHOOK_SECRET` is not set (or set to `"change-me-in-production"`)
- **Production**: Set `VECTOR_SYNC_WEBHOOK_SECRET` in `.env` and include it in the header

**Request:**
```json
{
  "listing_ids": ["uuid-1", "uuid-2"],  // Optional: specific listings
  "clear_existing": false
}
```

**Headers (only required if secret is set in .env):**
```
X-Webhook-Secret: your-secret-here
```

**Example (Development - no secret needed):**
```bash
curl -X POST "http://localhost:8000/api/v1/sync/listings" \
  -H "Content-Type: application/json" \
  -d '{"clear_existing": false}'
```

**Example (Production - with secret):**
```bash
curl -X POST "http://localhost:8000/api/v1/sync/listings" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret-here" \
  -d '{"listing_ids": ["uuid-1"], "clear_existing": false}'
```

#### `GET /api/v1/sync/status`

Get sync status.

## 📥 Data Ingestion

### Property Listings

Sync property listings from database to vector store:

```bash
# Sync all active listings
python app/helpers/ingestion_pipeline/property/sync_pgvector.py

# Or via API (requires webhook secret)
curl -X POST "http://localhost:8000/api/v1/sync/listings" \
  -H "X-Webhook-Secret: your-secret" \
  -H "Content-Type: application/json" \
  -d '{"clear_existing": false}'
```

#### `POST /api/v1/sync/trigger` (deprecated)

This is an alias for `POST /api/v1/sync/listings` kept for backward compatibility.

### Property-Specific PDFs

Property PDFs are automatically fetched from the database via `ListingRepository.fetch_property_documents()` and ingested:

```bash
python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py
```

### Generic Knowledge PDFs

Ingest generic real estate knowledge documents:

```bash
python app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py
```

**Auto-Discovery:** The script automatically discovers all PDFs in `app/knowledge_base/**/*.pdf` and infers metadata from folder structure. Simply place PDFs in subdirectories (e.g., `app/knowledge_base/legislation/file.pdf` → category="legislation").

## 🔄 Working Flow

### Property-Specific Query Flow

1. User sends query with `listing_id`
2. System retrieves relevant chunks from `property_embeddings`
3. Enriches with location data, nearby properties, amenity links
4. Generates response using GPT-4o
5. Returns formatted response with metadata

### Generic Query Flow

1. User sends query without `listing_id` (or generic keywords detected)
2. System retrieves relevant chunks from `generic_knowledge`
3. Generates response from general real estate knowledge
4. Returns answer with conversation context

### Cascading Fallback

For property queries, the system tries in order:
1. **Property JSON chunks** (from structured listing data)
2. **Property-specific PDFs** (from property documents)
3. **Generic knowledge PDFs** (legislation, guides)
4. **Final fallback**: "Contact vendor/agent" message

### Conversation Management

- Each conversation is tracked by `conversation_id`
- Generic queries: `listing_id = NULL` (allows multiple generic conversations)
- Property queries: One conversation per `(user_id, listing_id)`
- Last 10 messages are included in context for follow-up questions

## 🛠️ Development

### Project Structure

```
Unreserved/
├── app/
│   ├── api/v1/routes/          # API endpoints
│   │   ├── chat.py             # Chat endpoint
│   │   ├── voice.py            # Voice transcription
│   │   ├── health.py            # Health checks
│   │   └── sync.py              # Vector sync
│   ├── services/rag_pipeline/   # RAG pipeline
│   │   ├── preprocess.py       # Query preprocessing
│   │   ├── retrieval.py        # Vector retrieval
│   │   ├── augmentation.py     # Context augmentation
│   │   ├── generation.py       # LLM generation
│   │   └── prompts.py          # Prompt templates
│   ├── helpers/ingestion_pipeline/  # Data ingestion
│   │   ├── property/           # Property-specific ingestion
│   │   ├── generic/            # Generic knowledge ingestion
│   │   └── shared/             # Shared utilities
│   ├── db/                      # Database layer
│   │   ├── models/             # SQLAlchemy models
│   │   └── postgres/repositories/  # Repository pattern
│   └── main.py                  # FastAPI application
├── tests/                       # Test scripts
├── infra/                       # Infrastructure
│   ├── docker/                 # Docker configs
│   └── migration/              # Alembic migrations
└── requirements.txt
```

### Running Tests

```bash
# Test voice transcription
python tests/unit/test_voice_transcription.py

# Test property PDF repository
python tests/unit/test_property_pdf_repository.py

# Interactive chat CLI
python tests/unit/chat_listing_cli.py
```

### Adding New Features

1. **New API Endpoint**: Add route in `app/api/v1/routes/`
2. **New RAG Component**: Add module in `app/services/rag_pipeline/`
3. **New Data Source**: Add ingestion script in `app/helpers/ingestion_pipeline/`
4. **Database Changes**: Create Alembic migration in `infra/migration/`

## 📝 Recent Updates

### Latest Changes (2026-01-15)

- ✅ **Comprehensive Health Checks**: Added `/api/v1/health` endpoint checking all services
- ✅ **Voice Transcription**: Integrated OpenAI Whisper-1 for voice-to-text
- ✅ **Property PDF Ingestion**: Automatic ingestion from database via repository layer
- ✅ **Generic Knowledge Store**: Separate vector store for generic real estate knowledge
- ✅ **Cascading Fallback**: Intelligent fallback from property data → PDFs → generic knowledge
- ✅ **Location-Aware Responses**: Nearby properties and amenity links with Google Maps
- ✅ **Conversation History**: Full conversation context management
- ✅ **OpenAI Migration**: Migrated from Groq to OpenAI exclusively (GPT-4o)
- ✅ **Repository Pattern**: Centralized database access via repository layer
- ✅ **Code Cleanup**: Removed duplicate files and organized structure

### Migration Notes

- **Vector Dimensions**: Updated from 384 to 1536 (OpenAI embeddings)
- **LLM Provider**: OpenAI only (removed Groq fallback)
- **Data Source**: Property data now fetched from database, not JSON files
- **PDF Processing**: Property PDFs fetched from `property_media` table

## 📚 Additional Documentation

- [Architecture Details](./ARCHITECTURE.md)
- [PDF Ingestion Guide](./PDF_INGESTION_README.md)
- [Property PDF Ingestion](./PROPERTY_PDF_INGESTION.md)
- [Unused Files Analysis](./UNUSED_FILES_ANALYSIS.md)

## 🤝 Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Update documentation
4. Ensure health checks pass

## 📄 License

[Add your license here]

## 🆘 Support

For issues or questions:
1. Check the health endpoint: `/api/v1/health`
2. Review API documentation: `/docs`
3. Check logs for detailed error messages

---

**Version**: 1.0.0  
**Last Updated**: January 2026

