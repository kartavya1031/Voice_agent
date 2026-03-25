# AI Voice Agent Platform

**Link:** [GitHub Repo / Live Demo URL]
**Start Date:** [Your Start Date]
**Location:** [Your Location]
**Organization:** Personal Project

---

## Resume Bullet Points

### Version 1 — Full-Stack & Architecture Focus

- Engineered a multi-tenant AI voice agent platform using **FastAPI**, **Azure OpenAI (GPT-4o)**, and **Azure Speech Services**, enabling real-time bidirectional voice conversations over WebSocket with sub-400ms greeting latency.

- Designed and implemented a **RAG (Retrieval-Augmented Generation)** pipeline using **ChromaDB** vector store and **Azure OpenAI embeddings**, allowing agents to deliver context-aware responses from uploaded PDF knowledge bases.

- Built a **bulk calling campaign system** with CSV upload, dynamic variable interpolation into agent prompts, sequential call execution, and real-time progress tracking for outbound telephony via **FreJun SIP integration**.

- Architected a **multi-tenant data isolation layer** with organization → agent → user hierarchy, **JWT authentication**, and **role-based access control** (super_admin, org_admin, org_member) using **SQLAlchemy ORM** on MySQL.

- Optimized end-to-end voice response latency by **88%** (3.3s → 0.4s) through parallel RAG execution, LLM streaming, early sentence detection, TTS audio caching, and connection pooling strategies.

- Developed a **React (Vite)** frontend with live voice testing via browser WebSocket, agent configuration dashboard, campaign management with CSV validation, and call history with sentiment analysis display.

---

### Version 2 — Backend & AI/ML Focus

- Built a production-grade **AI voice calling platform** integrating **Azure OpenAI GPT-4o**, **Azure Speech-to-Text/Text-to-Speech**, and **ChromaDB** for real-time conversational AI over telephony (SIP) and browser WebSocket.

- Implemented **Retrieval-Augmented Generation (RAG)** with semantic vector search, embedding caching (LRU), and context truncation, reducing hallucinations and enabling domain-specific agent responses from uploaded documents.

- Reduced voice agent response time from **3.3s to 400ms** by parallelizing RAG retrieval with LLM inference, streaming TTS at 8-word sentence boundaries, and caching repeated audio phrases.

- Designed a **multi-organization SaaS backend** with tenant-isolated data, per-agent knowledge bases, configurable speech settings (50+ Azure neural voices), and dual TTS provider support (Azure + ElevenLabs).

- Integrated **FreJun telephony API** for outbound/inbound SIP calls with audio resampling (24kHz → 8kHz for telephony, 16kHz for browser), barge-in support, and post-call sentiment analysis via LLM.

- Developed RESTful APIs and WebSocket endpoints for agent CRUD, campaign management, call history, knowledge base upload (PDF processing via PyMuPDF), and real-time audio streaming.

---

### Version 3 — Short & Punchy (3-4 bullets)

- Built a **real-time AI voice agent platform** using FastAPI, Azure OpenAI, and Azure Speech Services with RAG-powered knowledge base retrieval, achieving **88% latency reduction** (3.3s → 0.4s) through parallel processing and caching optimizations.

- Designed a **multi-tenant SaaS architecture** with JWT auth, role-based access control, per-organization agent isolation, and bulk calling campaigns with dynamic prompt variable interpolation.

- Integrated **FreJun SIP telephony** for production voice calls with bidirectional WebSocket audio streaming, barge-in support, post-call sentiment analysis, and dual TTS providers (Azure + ElevenLabs).

- Developed a **React dashboard** for agent configuration, live voice testing, CSV-driven bulk campaigns, and call analytics with transcript and sentiment display.

---

## Key Technical Skills Demonstrated

| Category | Technologies |
|----------|-------------|
| **Backend** | Python, FastAPI, SQLAlchemy, WebSockets, REST APIs |
| **AI/ML** | Azure OpenAI (GPT-4o), RAG, Embeddings, ChromaDB, Sentiment Analysis |
| **Speech** | Azure Cognitive Services (STT/TTS), ElevenLabs, Audio Resampling |
| **Database** | MySQL, ChromaDB (Vector Store), ORM Design |
| **Frontend** | React 18, Vite, Web Audio API, JWT Auth |
| **Telephony** | FreJun API, SIP Trunking, Telephony Audio Processing |
| **Architecture** | Multi-Tenant SaaS, RBAC, Connection Pooling, Caching, Streaming |
| **DevOps** | Virtual Environments, Environment Config, CORS, SSL/TLS |
