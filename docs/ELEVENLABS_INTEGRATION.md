# ElevenLabs TTS Integration Plan

**TL;DR:** Add ElevenLabs as an alternative TTS provider alongside Azure. Users will select provider (Azure/ElevenLabs) in frontend, then pick a voice. The system dynamically routes TTS calls based on agent configuration. Requires database schema changes, new ElevenLabs streaming functions, API endpoint updates, and frontend dropdown additions.

---

## Steps

### Phase 1: Setup & Configuration

1. **Create ElevenLabs account**: Sign up at [elevenlabs.io](https://elevenlabs.io), navigate to Profile → API Keys, generate and copy the API key

2. **Add environment variable** to server configuration:
   - Add `ELEVENLABS_API_KEY` to your `.env` or deployment environment

3. **Update [config.py](../app/core/config.py)**: Add ElevenLabs config and default model setting:
   - Add `ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")`
   - Add `ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")` for model selection

4. **Update [requirements.txt](../app/requirements.txt)**: Add `elevenlabs>=1.0.0` package

---

### Phase 2: Database Schema Changes

5. **Update [models.py](../app/db/models.py)** - Add new columns to `Agent` model:
   - `tts_provider = Column(String(20), default="azure")` — values: `"azure"` | `"elevenlabs"`
   - `elevenlabs_voice_id = Column(String(50), nullable=True)` — ElevenLabs voice ID
   - `elevenlabs_model_id = Column(String(50), default="eleven_multilingual_v2")` — model selection

6. **Create migration**: Run Alembic migration to add new columns to existing `agents` table

---

### Phase 3: TTS Service Layer

7. **Update [speech.py](../app/services/speech.py)** - Add ElevenLabs TTS functions:
   
   - Add `text_to_speech_elevenlabs_streaming(text, voice_id, model_id)` — 24kHz native, resample to 16kHz for browser
   - Add `text_to_speech_elevenlabs_telephony(text, voice_id, model_id)` — resample to 8kHz for FreJun
   - Both must use ElevenLabs streaming API (`eleven_labs.generate(stream=True)`)
   - Implement audio resampling (ElevenLabs outputs 24kHz MP3/PCM, FreJun needs 8kHz PCM)
   
   - Add unified router function `get_tts_generator(text, agent_config)` that checks `tts_provider` and routes to Azure or ElevenLabs

8. **Add audio format conversion**: Use `pydub` or `scipy` for resampling 24kHz → 8kHz for telephony support

---

### Phase 4: API Endpoint Updates

9. **Update [agents.py](../app/api/agents.py)** - Modify request/response models:
   - Add `tts_provider: str` to `CreateAgentRequest` and `UpdateAgentRequest`
   - Add `elevenlabs_voice_id: Optional[str]` to both models
   - Add `elevenlabs_model_id: Optional[str]` to both models

10. **Create new endpoint** `GET /api/agent/elevenlabs-voices` in [agents.py](../app/api/agents.py):
    - Fetch voices from ElevenLabs API: `GET https://api.elevenlabs.io/v1/voices`
    - Return list with `voice_id`, `name`, `preview_url`, `labels` (accent, gender, etc.)
    - Cache response to avoid rate limits (voices change infrequently)

11. **Update existing** `GET /api/agent/voices` response to include provider metadata (`provider: "azure"`)

---

### Phase 5: WebSocket Handler Updates

12. **Update [main.py](../app/main.py)** - Modify `agent_config` loading (~line 848-865):
    - Include `tts_provider`, `elevenlabs_voice_id`, `elevenlabs_model_id` from database

13. **Update TTS call sites** in [main.py](../app/main.py) (opening message ~L910, response ~L1210, goodbye ~L1106):
    - Replace direct `text_to_speech_streaming_for_agent()` calls with the new `get_tts_generator(text, agent_config)` router
    - Same for telephony `text_to_speech_telephony_for_agent()` calls

---

### Phase 6: Frontend Changes

14. **Update [AgentConfig.jsx](../frontend/src/components/AgentConfig.jsx)** - Add provider dropdown:
    - Add TTS Provider dropdown (`Azure` | `ElevenLabs`) above voice selection
    - When provider changes, fetch appropriate voice list from `/api/agent/voices` or `/api/agent/elevenlabs-voices`
    - Show ElevenLabs voice dropdown (with preview) when ElevenLabs selected
    - Show Azure voice dropdown when Azure selected

15. **Update agent state** in `AgentConfig.jsx`:
    - Add `tts_provider`, `elevenlabs_voice_id`, `elevenlabs_model_id` to component state
    - Persist these fields on save

16. **Add voice preview** for ElevenLabs: ElevenLabs API returns `preview_url` for each voice — add play button to preview

---

## Verification

1. **Unit test**: Call `text_to_speech_elevenlabs_streaming()` directly with a test voice ID, verify audio bytes returned
2. **Integration test**: Create agent with `tts_provider: "elevenlabs"`, make WebSocket call, verify ElevenLabs audio plays
3. **Telephony test**: Make FreJun call with ElevenLabs agent, verify 8kHz audio quality
4. **Frontend test**: Toggle between Azure/ElevenLabs in dropdown, verify voice lists update and selection persists

---

## Decisions

- **Audio resampling**: Use `pydub` with ffmpeg for 24kHz→8kHz conversion (reliable, handles MP3 input)
- **Voice caching**: Cache ElevenLabs voice list for 1 hour (voices rarely change, avoids rate limits)
- **Default provider**: Keep `azure` as default for backward compatibility
- **Model selection**: Use `eleven_multilingual_v2` as default (best quality, supports multiple languages)
