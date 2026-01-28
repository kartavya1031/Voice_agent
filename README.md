# Anvenssa AI Voice Agent

A multi-tenant AI voice agent platform with real-time speech-to-text, LLM-powered responses, and text-to-speech capabilities.

## Features

- 🎙️ **Real-time Voice Conversations** - WebSocket-based audio streaming
- 🤖 **AI-Powered Responses** - Google Gemini LLM integration
- 🗣️ **Azure Speech Services** - STT and TTS with multiple voices
- 📚 **Knowledge Base (RAG)** - Upload PDFs for context-aware responses
- 📞 **Telephony Integration** - FreJun support for phone calls
- 👥 **Multi-Tenant** - Organization-based data isolation
- 🔐 **Authentication** - Role-based access control

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Azure Speech API key
- Google Gemini API key

### Backend Setup
```bash
cd Ai-voice

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r app/requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your API keys

# Run the server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Run the development server
npm run dev
```

### Access the Application
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](docs/API_REFERENCE.md) | Complete API endpoint documentation |
| [Multi-Tenant Architecture](docs/MULTI_TENANT_ARCHITECTURE.md) | Organization-based isolation design |
| [Organization Setup](docs/ORGANIZATION_SETUP.md) | How to create organizations and users |
| [Production Readiness](docs/PRODUCTION_READINESS.md) | Deployment checklist and recommendations |

## Project Structure

```
Ai-voice/
├── app/
│   ├── api/              # API route handlers
│   │   ├── agents.py     # Agent CRUD operations
│   │   ├── auth.py       # Authentication
│   │   ├── frejun.py     # FreJun telephony
│   │   └── webhooks.py   # Recording webhooks
│   ├── db/               # Database layer
│   │   ├── models.py     # SQLAlchemy models
│   │   ├── service.py    # Business logic services
│   │   └── session.py    # Database connection
│   ├── services/         # Core services
│   │   ├── llm.py        # LLM integration
│   │   ├── speech.py     # Azure Speech SDK
│   │   └── vector_store.py # ChromaDB for RAG
│   ├── data/             # Data storage
│   └── main.py           # FastAPI application
├── frontend/
│   ├── src/
│   │   ├── auth/         # Authentication context
│   │   ├── components/   # React components
│   │   └── App.jsx       # Main application
│   └── package.json
├── docs/                 # Documentation
└── README.md
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SPEECH_KEY` | Azure Speech API key | Yes |
| `SPEECH_REGION` | Azure region (e.g., centralindia) | Yes |
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `FREJUN_API_KEY` | FreJun API key | For telephony |
| `FREJUN_FROM_NUMBER` | FreJun caller ID | For telephony |
| `PUBLIC_BASE_URL` | Public URL for webhooks | For telephony |

## License

Proprietary - Anvenssa Consultancy Pvt. Ltd.
