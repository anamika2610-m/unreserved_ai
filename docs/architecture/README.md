# Unreserved – Architecture & End-to-End Overview

This folder describes the end-to-end architecture of the **Unreserved Property Chat API**: main features, components, data flows, and diagrams to support onboarding and future modifications.

---

## Contents

| Document | Description |
|----------|-------------|
| [01-overall-architecture.md](./01-overall-architecture.md) | High-level components, tech stack, layers, and deployment view |
| [02-chat-and-rag-flow.md](./02-chat-and-rag-flow.md) | Chat API and RAG pipeline: request flow, retrieval, generation |
| [03-sync-and-ingestion.md](./03-sync-and-ingestion.md) | Sync endpoints: listings, property PDFs, generic PDFs → vector store |
| [04-summaries-and-cron.md](./04-summaries-and-cron.md) | Property-level chat summaries and in-app daily scheduler |

---

## Important Features (Summary)

- **Chat** – Property and general real-estate Q&A via `POST /api/v1/chat/message`. RAG over listing + generic knowledge; conversation history when `user_id` is provided; enquiry vs conversational handling; tone adaptation after many messages; amenity/Google Maps links for location queries.
- **Voice** – Transcribe audio (OpenAI Whisper), transcribe+chat in one call, text-to-speech (ElevenLabs). Rate-limited (e.g. 20/min).
- **RAG pipeline** – Preprocess → retrieval (pgvector + optional generic store) → augmentation → LLM generation (OpenAI) with prompts; listing-specific, generic, and enquiry flows.
- **Summaries** – Property-level chat summaries (themes, query categories); admin GET and bulk generate; nightly cron via in-app scheduler.
- **Sync** – Sync listings and PDFs into vector store: `/sync/listings`, `/sync/property-pdfs`, `/sync/generic-pdfs` (and async/upload variants); optional webhook-secret protection.
- **Admin** – Listing summary, bulk summary generation, cron status.
- **Activity** – Listing activity metrics and tone level for AI (enquiries, inspections, offers).
- **Health** – Deep health checks: DB, pgvector, LLM, embeddings, internet.
- **Rate limiting** – SlowAPI; per-IP (or user); Redis or in-memory; toggled via `RATE_LIMIT_ENABLED`.

---

## Entry Point & Run

- **Entry:** `app/main.py`
- **Run:** `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- **Docs:** `/docs`, `/redoc`

---

## For New Maintainers

1. Start with [01-overall-architecture.md](./01-overall-architecture.md) for the big picture.
2. Use [02–04](./02-chat-and-rag-flow.md) when changing chat, sync, or summaries.
3. Config and env are summarized in [01-overall-architecture.md#configuration](./01-overall-architecture.md#configuration); see also `app/core/settings.py` and `.env.example` (if present).
