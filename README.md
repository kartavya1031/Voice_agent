# Anvenssa.AI Voice Agent

A real-time AI voice agent built with Python, FastAPI, Azure OpenAI, and Azure Speech Services. Features intelligent conversation with RAG (Retrieval Augmented Generation), barge-in support, and optimized latency.

## 🎯 Features

- **Real-time Voice Conversation** - WebSocket-based audio streaming
- **Speech-to-Text** - Azure Cognitive Services continuous recognition
- **Text-to-Speech** - Azure Neural voices with streaming
- **RAG Integration** - ChromaDB vector store with Azure OpenAI embeddings
- **Barge-in Support** - Interrupt the agent mid-speech
- **Optimized Latency** - ~1700ms first audio for complex queries, ~400ms for greetings
- **Call Management** - MySQL database for call records and transcripts
- **Web Dashboard** - React frontend for testing and configuration

## 📋 Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- MySQL 8.0+ (for call records)
- Azure OpenAI subscription
- Azure Speech Services subscription

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd Ai-voice
```

### 2. Create Python Virtual Environment
```bash
python -m venv env
env\Scripts\activate  # Windows
# OR
source env/bin/activate  # Linux/Mac
```

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

### 5. Configure Environment Variables

Create a `.env` file in the root directory:

```env
# Azure OpenAI Configuration
AZURE_OPENAI_KEY=your_azure_openai_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
DEPLOYMENT_NAME=gpt-4o-mini
AZURE_EMBEDDING_DEPLOYMENT_NAME=text-embedding-ada-002

# Azure Speech Configuration
AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=eastus

# MySQL Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=anvenssa_voice
```

### 6. Setup MySQL Database

```sql
CREATE DATABASE anvenssa_voice;
```

The tables will be created automatically on first run.

## 🚀 Running the Application

### Start Backend Server
```bash
# Activate virtual environment first
env\Scripts\activate  # Windows

# Run the server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Start Frontend Development Server
```bash
cd frontend
npm run dev
```

### Access the Application
- **Frontend**: http://localhost:5173
- **Backend API**: http://127.0.0.1:8000
- **API Docs**: http://127.0.0.1:8000/docs

## 📁 Project Structure

```
Ai-voice/
├── app/
│   ├── main.py              # FastAPI app & WebSocket handler
│   ├── core/
│   │   └── config.py        # Environment configuration
│   ├── services/
│   │   ├── llm.py           # LLM service with RAG
│   │   ├── speech.py        # STT/TTS services
│   │   ├── vector_store.py  # ChromaDB vector store
│   │   └── agent_config.py  # Agent configuration
│   ├── db/
│   │   ├── session.py       # Database connection
│   │   └── service.py       # Call CRUD operations
│   └── data/
│       ├── chroma_db/       # Vector store data
│       └── knowledge_base.md # Default knowledge base
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   └── App.css          # Styles
│   ├── public/
│   │   └── audioProcessor.js # Audio worklet
│   └── package.json
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables
├── OPTIMIZATION_JOURNEY.md   # Latency optimization docs
└── README.md
```

## 🎤 How It Works

### Voice Pipeline
```
User Speaks → STT (Azure) → LLM (GPT-4o-mini) → TTS (Azure) → Audio Playback
                              ↓
                         RAG Context
                        (ChromaDB)
```

### Latency Optimizations Applied
1. **Parallel RAG + LLM** - RAG runs in background, LLM starts immediately
2. **Instant Response Cache** - Common greetings return without LLM call
3. **TTS Audio Caching** - Repeated phrases use cached audio
4. **Early Sentence Flush** - Audio starts before full response
5. **Reduced Token/Temperature** - Faster LLM sampling

## 🔧 Configuration Options

### Agent Configuration (via Dashboard)
- **Recognition Language**: Language for STT (default: en-IN)
- **Synthesis Voice**: Azure Neural voice (default: en-IN-NeerjaNeural)
- **System Prompt**: Customize agent behavior
- **Knowledge Bases**: Upload custom knowledge files

### Call Settings
- **Max Call Duration**: Default 600 seconds
- **Silence Timeout**: Default 20 seconds

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/ws/audio` | WebSocket | Audio streaming |
| `/api/settings` | GET/POST | Call settings |
| `/api/calls` | GET | List all calls |
| `/api/calls/{id}` | GET | Get call details |
| `/api/agent/config` | GET | Agent configuration |
| `/api/agent/speech` | POST | Update speech settings |
| `/api/agent/system-prompt` | POST | Update system prompt |
| `/api/agent/knowledge-bases` | POST | Upload knowledge base |

## 🐛 Troubleshooting

### Server Won't Start
- Check if port 8000 is available
- Verify `.env` file exists with correct values
- Ensure MySQL is running

### No Audio Output
- Check browser microphone permissions
- Verify Azure Speech key and region
- Check browser console for WebSocket errors

### Slow Response
- Check Azure region (use closest)
- Verify embeddings deployment exists
- Review OPTIMIZATION_JOURNEY.md for tuning

## 📈 Performance Metrics

| Metric | Value |
|--------|-------|
| Greeting Response | ~400ms |
| Complex Query | ~1700ms |
| Barge-in Detection | <100ms |
| TTS Latency (cached) | ~0ms |

## 🔮 Future Improvements

1. **Azure PTU** - Provisioned throughput for faster LLM
2. **Multi-language** - Support for more languages
3. **Call Analytics** - Sentiment analysis, call summaries
4. **Twilio/Plivo Integration** - Phone call support
5. **Conversation History** - Multi-turn context

## 📄 License

Proprietary - Anvenssa.AI

## 📞 Support

- Email: sales@anvenssa.com
- Phone: +91 8956512955 (Mon-Fri, 10:00-7:00)
