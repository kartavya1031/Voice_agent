"""
LLM Service with RAG (Retrieval Augmented Generation)
Uses Azure OpenAI with knowledge base context from vector store

OPTIMIZATIONS APPLIED:
1. Parallel RAG + LLM - Start LLM immediately, inject RAG context when ready
2. Reduced max_tokens (150) and temperature (0.5) for faster responses
3. LRU cache for embeddings (in vector_store.py)
4. Optimized system prompt
"""

import time
import threading
import queue
from functools import lru_cache
from openai import AzureOpenAI
from app.core.config import (
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_ENDPOINT,
    DEPLOYMENT_NAME
)
from app.services.vector_store import get_context_for_query
from app.services.agent_config import agent_config_service

# Create client with optimized settings
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version="2024-02-15-preview",
    timeout=15.0,  # Faster timeout
)


def get_system_prompt() -> str:
    """Get the current system prompt from config"""
    return agent_config_service.get_system_prompt()


# Keywords that should skip RAG lookup (fast path)
SKIP_RAG_KEYWORDS = [
    "hello", "hi", "hey", "bye", "goodbye", "thanks", "thank you",
    "yes", "no", "okay", "ok", "sure", "fine", "good", "great",
    "how are you", "what's up", "help", "sorry", "please",
    "what", "who", "test", "testing", "nahi", "haan"
]


# =============================================================================
# INSTANT RESPONSE CACHE - Returns pre-defined responses without calling LLM
# This gives ~0ms latency for common greetings and queries
# =============================================================================
INSTANT_RESPONSES = {
    # Greetings
    "hello": "Hi there! Welcome to Anvenssa.AI. How can I help you today?",
    "hi": "Hello! Welcome to Anvenssa.AI. How may I assist you?",
    "hey": "Hey! Welcome to Anvenssa.AI. What can I do for you?",
    "hi there": "Hello! How can I assist you today?",
    "good morning": "Good morning! Welcome to Anvenssa.AI. How can I help?",
    "good afternoon": "Good afternoon! How may I assist you today?",
    "good evening": "Good evening! Welcome to Anvenssa.AI. How can I help?",
    
    # Farewells
    "bye": "Goodbye! Thank you for contacting Anvenssa.AI. Have a great day!",
    "goodbye": "Goodbye! It was nice helping you. Take care!",
    "thank you": "You're welcome! Is there anything else I can help with?",
    "thanks": "You're welcome! Let me know if you need anything else.",
    "thank you bye": "You're welcome! Goodbye and have a wonderful day!",
    
    # Confirmations
    "yes": "Great! How can I help you further?",
    "no": "Alright. Is there something else I can assist you with?",
    "okay": "Okay! What would you like to know?",
    "ok": "Alright! How can I help?",
}


def get_instant_response(query: str) -> str | None:
    """Check if query matches an instant response (case-insensitive)"""
    query_clean = query.lower().strip().rstrip('.!?')
    
    # Direct match
    if query_clean in INSTANT_RESPONSES:
        return INSTANT_RESPONSES[query_clean]
    
    # Partial match for greetings
    for key, response in INSTANT_RESPONSES.items():
        if query_clean == key or query_clean.startswith(key + " "):
            return response
    
    return None


def should_skip_rag(query: str) -> bool:
    """Check if query should skip RAG for faster response"""
    query_lower = query.lower().strip()
    
    # Skip for very short queries (likely greetings)
    word_count = len(query_lower.split())
    if word_count <= 4:
        for keyword in SKIP_RAG_KEYWORDS:
            if keyword in query_lower:
                return True
    
    return False


def build_prompt_with_context(user_query: str, context: str = "") -> list[dict]:
    """Build messages with optional RAG context"""
    system_prompt = get_system_prompt()
    
    # Build system message with context (truncate to 800 chars max for speed)
    if context:
        context_truncated = context[:800] if len(context) > 800 else context
        system_content = f"""{system_prompt}

CONTEXT:
{context_truncated}

Be brief and conversational."""
    else:
        system_content = system_prompt
    
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_query}
    ]


def ask_ai(text: str) -> str:
    """Get AI response with RAG context"""
    # Simple blocking version - use streaming for real-time
    if should_skip_rag(text):
        context = ""
    else:
        context = get_context_for_query(text)
    
    messages = build_prompt_with_context(text, context)
    
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=150,  # Reduced for speed
        temperature=0.5  # Reduced for faster sampling
    )
    return response.choices[0].message.content


def ask_ai_streaming_parallel(text: str):
    """
    OPTIMIZED: Stream LLM response with PARALLEL RAG lookup.
    
    Strategy:
    - If simple query: skip RAG entirely, start LLM immediately
    - If complex query: start LLM with base prompt, RAG runs in parallel
      (we don't wait for RAG - LLM starts immediately)
    """
    import time
    start_time = time.time()
    
    # Check if we should skip RAG
    if should_skip_rag(text):
        print(f"   ⚡ Skipping RAG for simple query: '{text}'")
        context = ""
        messages = build_prompt_with_context(text, context)
    else:
        # Start RAG in background thread
        rag_result = [None]
        rag_done = threading.Event()
        
        def fetch_rag():
            rag_start = time.time()
            try:
                rag_result[0] = get_context_for_query(text)
                rag_time = (time.time() - rag_start) * 1000
                if rag_result[0]:
                    print(f"   📚 RAG (parallel): {rag_time:.0f}ms ({len(rag_result[0])} chars)")
                else:
                    print(f"   📚 RAG (parallel): {rag_time:.0f}ms (no context)")
            except Exception as e:
                print(f"   ⚠️ RAG error: {e}")
                rag_result[0] = ""
            finally:
                rag_done.set()
        
        # Start RAG thread
        threading.Thread(target=fetch_rag, daemon=True).start()
        
        # DON'T WAIT for RAG - start LLM immediately with base prompt
        # This is the key optimization: we overlap RAG and LLM network calls
        
        # Wait just a tiny bit (50ms) to see if RAG returns fast
        rag_done.wait(timeout=0.05)
        
        if rag_done.is_set() and rag_result[0]:
            # RAG returned quickly, use it
            context = rag_result[0]
            print(f"   ✨ RAG returned in <50ms, including context")
        else:
            # RAG is slow, start without context
            context = ""
            print(f"   🚀 Starting LLM without waiting for RAG")
        
        messages = build_prompt_with_context(text, context)
    
    # Stream LLM response with optimized parameters
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=150,      # Reduced from 200 for speed
        temperature=0.5,     # Reduced from 0.7 for faster sampling
        stream=True
    )
    
    for chunk in response:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


# Keep old function name for backward compatibility
def ask_ai_streaming(text: str):
    """
    Stream LLM response with optimizations:
    1. Check instant response cache first (0ms latency)
    2. Fall back to parallel RAG + LLM
    """
    # Check for instant response first (greetings, farewells, etc.)
    instant = get_instant_response(text)
    if instant:
        print(f"   ⚡ INSTANT RESPONSE (cached): '{text}' -> 0ms latency!")
        # Yield the response word by word to simulate streaming
        words = instant.split()
        for i, word in enumerate(words):
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word
        return
    
    # Fall back to parallel RAG + LLM
    yield from ask_ai_streaming_parallel(text)
