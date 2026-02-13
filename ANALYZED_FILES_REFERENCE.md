# Analyzed Files Reference Guide

## Overview

This document provides a quick reference to all files analyzed in the concurrency audit, with direct links to the code locations discussed in the analysis documents.

---

## Key Files Analyzed

### 1. Application Entry Point & WebSocket Handlers

**File:** [app/main.py](app/main.py)

**Critical Sections:**

| Line Range | Component | Issue | Analysis Doc |
|-----------|-----------|-------|--------------|
| 1-25 | Module imports & globals | Declares `current_turn_id` lock (good) | REMEDIATION |
| 79-84 | startup_event() | Initializes speech services (good) | - |
| 150-170 | CallSettings class | Global settings object ⚠️ | ANALYSIS §3 |
| 1065-1290 | `/ws/audio` handler | Browser WebSocket (mostly good, calls globals) | ANALYSIS §3, REMEDIATION §4 |
| 1065-1167 | `audio_ws()` - Config setup | **🔴 CALLS GLOBAL FUNCTIONS** | ANALYSIS §3.1 |
| 1149-1167 | `audio_ws()` - Speech/LLM setup | `update_speech_settings()`, `set_system_prompt()`, `reset_conversation()` | ANALYSIS §3.1 |
| 1330-1948 | `/ws/frejun-audio` handler | FreJun WebSocket (better isolation) | ANALYSIS §3.2, REMEDIATION §5 |
| 1540-1544 | `frejun_audio_ws()` - Goodbye | Uses agent-specific `text_to_speech_telephony_for_agent()` ✓ | ANALYSIS §3.2 |
| 1820 | `frejun_audio_ws()` - TTS | Uses agent-specific voice parameter ✓ | ANALYSIS §3.2 |

**Key Issues:**
- ❌ Browser handler calls global `update_speech_settings()`, `set_system_prompt()`, `reset_conversation()`
- ✓ FreJun handler better - uses agent-specific functions
- Both handlers have good local per-call state for transcript, call_state

**Recommendation:** Update both handlers to use CallContext pattern (REMEDIATION §4-5)

---

### 2. LLM Service - Conversation & Prompt Management

**File:** [app/services/llm.py](app/services/llm.py)

**Critical Sections:**

| Line Range | Variable/Function | Status | Issue | Analysis |
|-----------|---|--------|-------|----------|
| 87-106 | `ConversationManager` class | ✓ Thread-safe class | Used as global singleton | ANALYSIS §2 |
| 108-132 | Global `_conversation_manager` | 🔴 CRITICAL | Shared across all calls, reset overwrites for everyone | ANALYSIS §2.1 |
| 108-110 | `reset_conversation()` | 🔴 CRITICAL | Overwrites global manager | ANALYSIS §2.1 |
| 112-115 | `get_conversation_manager()` | 🔴 CRITICAL | Returns shared singleton | ANALYSIS §2.1 |
| 117-122 | `add_to_conversation()` | 🔴 CRITICAL | Uses global manager | ANALYSIS §2.1 |
| 135-150 | Global `_override_system_prompt` | 🔴 CRITICAL | Shared across all calls | ANALYSIS §2.2 |
| 135-136 | `set_system_prompt()` | 🔴 CRITICAL | Sets global for ALL calls | ANALYSIS §2.2 |
| 145-150 | `get_system_prompt()` | 🔴 CRITICAL | Reads shared global | ANALYSIS §2.2 |
| 152-165 | `SKIP_RAG_KEYWORDS` | ✓ Safe | Read-only constant | - |
| 173-195 | `INSTANT_RESPONSES` | ✓ Safe | Read-only constant | - |
| 257-300 | `build_prompt_with_context()` | ⚠️ Partial | Uses globals without lock | ANALYSIS §2.3 |
| 326-360 | `ask_ai_streaming_parallel()` | ✓ Good | RAG lookup in thread | ANALYSIS §2.4 |
| 452-491 | `ask_ai_streaming_for_agent()` | ✓ Better | Multi-tenant version with params | ANALYSIS §2.5 |

**Key Issues:**

1. **🔴 CRITICAL - Global Conversation Manager**
   - Line 108: `_conversation_manager: Optional[ConversationManager] = None`
   - Line 108-110: `reset_conversation()` - overwrites for all calls
   - Line 112-115: `get_conversation_manager()` - returns shared instance
   - Race condition: Two concurrent calls both calling `reset_conversation()` → conversation histories mix
   - **Fix:** Use CallContext with per-call ConversationHistory (REMEDIATION §1)

2. **🔴 CRITICAL - Global System Prompt Override**
   - Line 135: `_override_system_prompt: str = None`
   - Line 135-136: `set_system_prompt()` - sets global for ALL calls
   - Race condition: Call A sets prompt, Call B changes it, Call A gets wrong prompt
   - **Fix:** Move to CallContext.system_prompt (REMEDIATION §2)

3. **⚠️ HIGH - HTTP Client**
   - Line 26-34: `http_client` for connection pooling - thread-safe but shared
   - This is OK for pooling, not a race condition risk

4. ✓ **GOOD - Multi-tenant LLM Functions**
   - Line 452-491: `ask_ai_streaming_for_agent()` - accepts explicit parameters
   - Could be used instead of global functions

**Recommendation:** 
- Delete global `_conversation_manager`, `_override_system_prompt`, related functions
- Refactor to use CallContext (REMEDIATION §1)
- Keep `ask_ai_streaming_for_agent()` pattern

---

### 3. Speech Service - Voice/TTS/STT Management

**File:** [app/services/speech.py](app/services/speech.py)

**Critical Sections:**

| Line Range | Variable/Function | Status | Issue | Analysis |
|-----------|---|--------|-------|----------|
| 6-9 | Global speech settings | 🔴 CRITICAL | `current_recognition_language`, `current_synthesis_voice` | ANALYSIS §3.1 |
| 23-29 | `update_speech_settings()` | 🔴 CRITICAL | Modifies globals, no lock | ANALYSIS §3.1 |
| 95-98 | `_tts_cache` | 🔴 CRITICAL | Dict with no lock, crashes with concurrent writes | ANALYSIS §3.2 |
| 105-123 | `_get_synthesizer()` | 🔴 CRITICAL | Reuse defeated by global voice changes | ANALYSIS §3.3 |
| `_synthesizer_lock` | Thread lock | ✓ Has lock | But config shared | ANALYSIS §3.3 |
| 133-148 | `text_to_speech_streaming()` | 🔴 CRITICAL | Unsafe cache writes, uses global voice | ANALYSIS §3.2 |
| 162-188 | `_get_telephony_synthesizer()` | 🔴 CRITICAL | Same as regular synthesizer issues | ANALYSIS §3.4 |
| `_telephony_tts_cache` | Cache dict | 🔴 CRITICAL | Same race condition as TTS cache | ANALYSIS §3.4 |
| 200-240 | `text_to_speech_telephony()` | ⚠️ Partial | Uses global synthesizer pool | ANALYSIS §3.4 |
| 280-320 | `initialize_speech_services()` | ✓ Good | Pre-warms connections at startup | - |
| 355-515 | Agent-specific functions | ✓ Better | `create_streaming_recognizer_for_agent()`, uses parameters | ANALYSIS §3.4 |
| 546-615 | `text_to_speech_telephony_for_agent()` | ✓ Better | Accepts explicit voice parameter | ANALYSIS §3.4 |

**Key Issues:**

1. **🔴 CRITICAL - Global Speech Settings**
   - Lines 6-9: `current_recognition_language`, `current_synthesis_voice`
   - Line 23-29: `update_speech_settings()` - sets globals, no lock
   - Race condition: Call A sets to English-India, Call B sets to Spanish-Mexico, Call A gets wrong voice
   - **Fix:** Use CallContext.speech_settings (REMEDIATION §3)

2. **🔴 CRITICAL - Unsafe TTS Cache**
   - Line 95-98: `_tts_cache = {}` - no lock!
   - Line 133-148: Cache read/write in `text_to_speech_streaming()`
   - Race condition: Concurrent writes corrupt dict, "dictionary changed size during iteration"
   - **Fix:** Add `_tts_cache_lock = threading.RLock()` (REMEDIATION §3)

3. **🔴 CRITICAL - Synthesizer Voice Mismatch**
   - Line 105-123: `_get_synthesizer()` with check on `_synthesizer_voice`
   - Problem: Between check and use, global `current_synthesis_voice` can change
   - Effect: Synthesizer reused with wrong voice config OR new one created (defeats pooling)
   - **Fix:** Synthesizer pool per voice (REMEDIATION §3)

4. **🔴 CRITICAL - Telephony Same Issues**
   - Line 162-188: `_get_telephony_synthesizer()` - same problems as regular synthesizer
   - Line `_telephony_tts_cache` - same race condition as TTS cache

5. ✓ **GOOD - Agent-Specific Functions**
   - Line 355-515: `create_streaming_recognizer_for_agent()` - takes language parameter
   - Line 546-615: `text_to_speech_telephony_for_agent()` - takes voice parameter
   - Could be standardized and used everywhere

**Recommendation:**
- Delete global `current_recognition_language`, `current_synthesis_voice`
- Add `_tts_cache_lock`, update caching to be thread-safe
- Implement synthesizer pool by voice
- Use CallContext pattern throughout (REMEDIATION §3)

---

### 4. Database Service - Multi-Tenant Call Management

**File:** [app/db/service.py](app/db/service.py)

**Critical Sections:**

| Class/Method | Status | Analysis |
|-------------|--------|----------|
| `CallService.create_call()` | ✓ GOOD | Creates new DB session, thread-safe |
| `CallService.end_call()` | ✓ GOOD | Per-call DB session |
| `CallService.save_transcript_content()` | ✓ GOOD | New session, atomic transaction |
| Database pooling pattern | ✓ GOOD | All methods use `SessionLocal()`, creates fresh connection |
| No global state | ✓ GOOD | Each method creates own session |

**Key Findings:**
- ✓ **Database layer is thread-safe**
- ✓ Uses SQLAlchemy best practices (new session per operation)
- ✓ Proper rollback on errors
- ✓ No concurrency issues identified

**Recommendation:**
- No changes needed to database layer
- Continue current pattern

---

### 5. Database Models - Schema & Relationships

**File:** [app/db/models.py](app/db/models.py)

**Critical Sections:**

| Class | Multi-Tenant? | Issues |
|-------|---|--------|
| `Organization` | ✓ Primary | Good - org_id as FK |
| `Agent` | ✓ Has org_id | No FK constraint to enforce |
| `User` | ✓ Has org_id | Allows NULL, could bypass filtering |
| `Call` | ⚠️ Partial | agent_id optional, could be orphaned |
| `Campaign` | ✓ Has org_id | Good multi-tenant linking |
| `ConversationManager` | N/A | Not in database |

**Key Findings:**
- ✓ Models are data structures, not executable code
- ✓ No concurrency issues in models themselves
- ⚠️ Recommendations for data integrity (non-critical):
  - Add FK constraints: `Call.agent_id` should reference `Agent.id`
  - Add NOT NULL constraints where appropriate
  - Add org_id filtering at ORM level

**Recommendation:**
- Models are fine for concurrency
- Add database constraints for data integrity (separate task)

---

## Race Condition Hot Spots (Summary Table)

| File | Line(s) | Variable/Function | Severity | Issue |
|------|---------|------------------|----------|-------|
| llm.py | 108-132 | `_conversation_manager` | 🔴 CRITICAL | Global singleton, reset corrupts all |
| llm.py | 135-150 | `_override_system_prompt` | 🔴 CRITICAL | Global override, set for all calls |
| llm.py | 257-300 | `build_prompt_with_context()` | ⚠️ HIGH | Reads globals without lock |
| speech.py | 6-9 | `current_*_language/voice` | 🔴 CRITICAL | Global settings, no synchronization |
| speech.py | 23-29 | `update_speech_settings()` | 🔴 CRITICAL | Modifies globals unsafely |
| speech.py | 95-98 | `_tts_cache` | 🔴 CRITICAL | Dict with no lock, corrupts |
| speech.py | 105-123 | `_get_synthesizer()` | 🔴 CRITICAL | Reuse broken by global changes |
| speech.py | 133-148 | `text_to_speech_streaming()` | 🔴 CRITICAL | Unsafe cache + global voice |
| speech.py | 162-188 | `_get_telephony_synthesizer()` | 🔴 CRITICAL | Same as regular synth |
| main.py | 1149-1167 | `audio_ws()` setup | 🔴 CRITICAL | Calls all global update functions |
| main.py | 1540-1544 | `frejun_audio_ws()` goodbye | ✓ GOOD | Uses agent-specific function |
| db/service.py | All | Database operations | ✓ GOOD | Thread-safe per SQL |
| db/models.py | All | ORM models | ✓ GOOD | No concurrency issues |

---

## Document Cross-References

### In CONCURRENCY_ANALYSIS.md

- **Global State Issues** → Lines 8-50 (overview of all globals)
- **LLM Race Condition #1** → Lines 75-125 (conversation manager)
- **LLM Race Condition #2** → Lines 133-165 (system prompt)
- **Speech Race Condition #3** → Lines 211-245 (speech settings)
- **Speech Race Condition #4** → Lines 260-295 (synthesizer cache)
- **Speech Race Condition #5** → Lines 310-340 (TTS cache)
- **WebSocket Analysis** → Lines 365-420 (both handlers)
- **Failure Scenarios** → Lines 600-750 (example race conditions)

### In CONCURRENCY_REMEDIATION.md

- **CallContext Pattern** → Lines 1-150 (architecture)
- **Fix #1: LLM Service** → Lines 200-320 (remove globals, add context)
- **Fix #2: Speech Service** → Lines 330-500 (thread-safe caching, settings)
- **Fix #3: WebSocket Handlers** → Lines 510-650 (use context)
- **Migration Checklist** → Lines 670-710 (implementation steps)

---

## Quick Navigation

**Looking for a specific issue?**

1. **"I want to know what's broken"** → CONCURRENCY_ANALYSIS.md §1-2
2. **"How do I fix this?"** → CONCURRENCY_REMEDIATION.md §1-5
3. **"What's the business impact?"** → CONCURRENCY_EXECUTIVE_SUMMARY.md
4. **"Show me the exact code locations"** → This document (above)

---

## Checklist for Review

When reviewing these documents:

- [ ] Read CONCURRENCY_EXECUTIVE_SUMMARY.md first
- [ ] Review CONCURRENCY_ANALYSIS.md detailed findings
- [ ] Study CONCURRENCY_REMEDIATION.md code examples
- [ ] Reference this document for specific file locations
- [ ] Create JIRA tickets for each fix
- [ ] Implement following remediation guide
- [ ] Test with concurrent load
- [ ] Deploy with monitoring

---

**Last Updated:** February 7, 2026  
**Status:** Complete Analysis - Ready for Implementation
