"""
LLM Service with RAG (Retrieval Augmented Generation)
Uses Azure OpenAI with knowledge base context from vector store

OPTIMIZATIONS APPLIED:
1. Parallel RAG + LLM - Start LLM immediately, inject RAG context when ready
2. Reduced max_tokens (150) and temperature (0.5) for faster responses
3. LRU cache for embeddings (in vector_store.py)
4. Optimized system prompt
5. Conversation history for multi-turn dialogue
"""

import time
import threading
import queue
from functools import lru_cache
from typing import List, Dict, Optional, Generator
from openai import AzureOpenAI
from app.core.config import (
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_ENDPOINT,
    DEPLOYMENT_NAME
)
from app.services.vector_store import get_context_for_query
from app.services.agent_config import agent_config_service

# Create client with optimized settings for low latency
# Using httpx with connection pooling and keepalive
import httpx

# Custom HTTP client with connection pooling (keeps connections warm)
http_client = httpx.Client(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0),
)

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version="2024-02-15-preview",
    timeout=15.0,
    http_client=http_client,  # Reuse connections
)


# =============================================================================
# CONVERSATION HISTORY MANAGER
# Maintains chat history for multi-turn conversations
# =============================================================================
class ConversationManager:
    """Manages conversation history for a call session.
    
    This is critical for scripted conversations where the LLM needs to know
    where it is in the conversation flow (e.g., already asked opening question,
    now need to ask verification questions).
    """
    
    def __init__(self, max_history: int = 20):
        """Initialize with max history limit to avoid token overflow."""
        self.history: List[Dict[str, str]] = []
        self.max_history = max_history
    
    def add_user_message(self, content: str):
        """Add a user message to history."""
        if content and content.strip():
            self.history.append({"role": "user", "content": content})
            self._trim_history()
    
    def add_assistant_message(self, content: str):
        """Add an assistant message to history."""
        if content and content.strip():
            self.history.append({"role": "assistant", "content": content})
            self._trim_history()
    
    def _trim_history(self):
        """Keep only the most recent messages to avoid token overflow."""
        if len(self.history) > self.max_history:
            # Keep most recent messages
            self.history = self.history[-self.max_history:]
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get a copy of the conversation history."""
        return list(self.history)
    
    def clear(self):
        """Clear conversation history (for new call)."""
        self.history = []
    
    def __len__(self):
        return len(self.history)


# Global conversation manager instance (will be reset per call)
_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Get or create the conversation manager."""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager


def reset_conversation():
    """Reset conversation history (call this at start of each new call)."""
    global _conversation_manager
    _conversation_manager = ConversationManager()


def add_to_conversation(role: str, content: str):
    """Add a message to conversation history."""
    manager = get_conversation_manager()
    if role == "user":
        manager.add_user_message(content)
    elif role == "assistant":
        manager.add_assistant_message(content)


def _warmup_llm_connection():
    """Pre-warm the LLM connection to reduce first-call latency"""
    try:
        # Make a minimal call to establish the connection
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0,
        )
        print("🔥 LLM connection pre-warmed!")
    except Exception as e:
        print(f"⚠️ LLM warmup failed (will work on first real call): {e}")


# Warmup on module load (runs in background thread to not block startup)
import threading
threading.Thread(target=_warmup_llm_connection, daemon=True).start()


# Override system prompt for multi-tenant browser calls
_override_system_prompt: str = None


def get_system_prompt() -> str:
    """Get the current system prompt from config with variables substituted"""
    global _override_system_prompt
    if _override_system_prompt:
        return _override_system_prompt
    return agent_config_service.get_resolved_system_prompt()


def set_system_prompt(prompt: str):
    """Set an override system prompt for the current call (multi-tenant support)"""
    global _override_system_prompt
    _override_system_prompt = prompt
    print(f"   📝 System prompt override set ({len(prompt)} chars)")


# Keywords that should skip RAG lookup (fast path) - only greetings, not questions
SKIP_RAG_KEYWORDS = [
    "hello", "hi", "hey", "bye", "goodbye", "thanks", "thank you",
    "yes", "no", "okay", "ok", "sure", "fine", "good", "great",
    "how are you", "what's up", "help", "sorry", "please",
    "test", "testing", "nahi", "haan"
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


def build_prompt_with_context(user_query: str, context: str = "", include_history: bool = True) -> list[dict]:
    """Build messages with optional RAG context and conversation history.
    
    LEGACY FUNCTION: Uses global conversation manager and agent_config_service.
    For multi-tenant calls, use build_prompt_for_agent() instead.
    
    Args:
        user_query: The current user message
        context: RAG context (if any)
        include_history: Whether to include conversation history for multi-turn dialogue
    
    Returns:
        List of messages for the LLM
    """
    system_prompt = get_system_prompt()
    
    # Get conversation history from global manager
    history = []
    if include_history:
        manager = get_conversation_manager()
        history = manager.get_messages()
    
    return build_prompt_for_agent(
        user_query=user_query,
        system_prompt=system_prompt,
        history=history,
        context=context
    )


def build_prompt_for_agent(
    user_query: str,
    system_prompt: str,
    history: List[Dict[str, str]] = None,
    context: str = ""
) -> list[dict]:
    """Build messages for a specific agent configuration.
    
    MULTI-TENANT VERSION: Accepts explicit parameters instead of using globals.
    Use this for per-agent call handling.
    
    Args:
        user_query: The current user message
        system_prompt: Agent-specific system prompt (already resolved with variables)
        history: Conversation history for this specific call
        context: RAG context (if any)
    
    Returns:
        List of messages for the LLM
    """
    if history is None:
        history = []
    
    # CRITICAL: Voice agent behavior instructions
    # Follow the system prompt EXACTLY - it defines all behavior, responses, and edge cases
    voice_agent_suffix = """

CRITICAL VOICE AGENT RULES:
1. FOLLOW THE SYSTEM PROMPT EXACTLY - it contains all sections, scripts, and edge cases you must follow.
2. ONLY output spoken words. Never output meta-instructions like "Take a pause", "Set variable", or stage directions.
3. ASK ONE QUESTION AT A TIME, then STOP and wait for the user's response.
4. After asking a question, DO NOT continue. Wait for user input.
5. Never use quotation marks, asterisks, brackets, or any formatting in your speech.
6. Check conversation history to know where you are in the script - do NOT repeat greetings.
7. Handle edge cases EXACTLY as defined in the system prompt (wrong person, busy, etc.).

STRICT KNOWLEDGE BASE RULES - VERY IMPORTANT:
8. ONLY use information from the CONTEXT provided. Do NOT make up or guess numbers, rates, tenures, documents, or any other details.
9. If the answer is NOT in the CONTEXT, say "Main abhi yeh information confirm nahi kar sakta, lekin aap humari team se baat kar sakte hain" or similar. NEVER invent information.
10. Use EXACT numbers and details from the knowledge base - do not round, estimate, or modify them.
11. If asked about interest rate, tenure, documents, banks, etc. - ONLY state what is written in the CONTEXT. If not present, admit you don't have that specific information.
12. NEVER hallucinate or fabricate any factual information like percentages, years, bank names, or document lists.
"""
    
    # Build system message
    if context:
        context_truncated = context[:800] if len(context) > 800 else context
        system_content = f"{system_prompt}\n{voice_agent_suffix}\nCONTEXT:\n{context_truncated}"
    else:
        system_content = f"{system_prompt}\n{voice_agent_suffix}"
    
    messages = [{"role": "system", "content": system_content}]
    
    # Add conversation history for multi-turn conversations
    if history:
        messages.extend(history)
    
    # Add current user message
    messages.append({"role": "user", "content": user_query})
    
    return messages


def clean_llm_output(text: str) -> str:
    """
    Clean LLM output to remove meta-instructions and formatting.
    This ensures only speakable content is sent to TTS.
    """
    import re
    
    # Remove common meta-instructions that shouldn't be spoken
    patterns_to_remove = [
        r'Take a pause for \d+ seconds?\.?',
        r'\[.*?\]',  # Remove anything in square brackets
        r'\(.*?\)',  # Remove anything in parentheses (stage directions)
        r'^\s*"',    # Remove leading quotes
        r'"\s*$',    # Remove trailing quotes
        r'\*.*?\*',  # Remove anything between asterisks
    ]
    
    cleaned = text
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    cleaned = re.sub(r'\n\s*\n', '\n', cleaned)  # Multiple newlines to single
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Multiple spaces to single
    cleaned = cleaned.strip()
    
    return cleaned


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
        temperature=0.1,  # Very low for factual responses
        top_p=0.9
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
    
    # Get active KB info for logging
    from app.services.vector_store import get_active_kb_info
    kb_info = get_active_kb_info()
    
    context = ""
    
    if should_skip_rag(text):
        print(f"   ⏩ Skipping RAG (simple query: '{text[:30]}...')")
    else:
        # Try RAG - get context from active knowledge base
        print(f"   🔍 Searching KB: {kb_info.get('kb_id', 'default')} ({kb_info.get('chunk_count', 0)} chunks)")
        
        rag_result = [None]
        rag_done = threading.Event()
        
        def fetch_rag():
            rag_start = time.time()
            try:
                rag_result[0] = get_context_for_query(text)
                rag_time = (time.time() - rag_start) * 1000
                if rag_result[0]:
                    print(f"   📚 RAG found context ({rag_time:.0f}ms): {rag_result[0][:100]}...")
                else:
                    print(f"   📭 No relevant context found in KB ({rag_time:.0f}ms)")
            except Exception as e:
                print(f"   ⚠️ RAG error: {e}")
                rag_result[0] = ""
            finally:
                rag_done.set()
        
        threading.Thread(target=fetch_rag, daemon=True).start()
        rag_done.wait(timeout=3.0)  # Wait max 3 seconds for RAG - MUST have context to avoid hallucination
        
        if rag_done.is_set() and rag_result[0]:
            context = rag_result[0]
            print(f"   ✅ Using RAG context: {len(context)} chars")
        elif not rag_done.is_set():
            print(f"   ⏰ RAG timeout - proceeding without context")
    
    messages = build_prompt_with_context(text, context)
    
    # Stream LLM response with optimized parameters
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=300,      # Increased for scripted conversations with verification blocks
        temperature=0.1,     # Very low for factual, KB-based responses - prevents hallucination
        top_p=0.9,           # Nucleus sampling for more focused responses
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
    Stream LLM response - follows the dynamic system prompt strictly.
    
    LEGACY FUNCTION: Uses global state from agent_config_service.
    For multi-tenant calls, use ask_ai_streaming_for_agent() instead.
    """
    start_time = time.time()
    
    # Special handling for agent-first opening message
    if text == "START_CONVERSATION":
        opening_query = "Begin the conversation with your opening script. Say only the opening greeting - do not continue beyond asking if you are speaking to the right person."
        yield from ask_ai_streaming_parallel(opening_query)
        return
    
    # Check if using custom/dynamic prompt
    prompt_variables = agent_config_service.get_prompt_variables()
    has_custom_prompt = bool(prompt_variables and any(v for v in prompt_variables.values() if v))
    
    if has_custom_prompt:
        # Dynamic prompt mode: ALWAYS use LLM to follow the prompt strictly
        # Skip instant responses - agent behavior is defined in the prompt
        yield from ask_ai_streaming_parallel(text)
    else:
        # Default mode: use instant responses for common phrases
        instant = get_instant_response(text)
        if instant:
            print(f"⚡ CACHED: '{text[:30]}...' -> 0ms")
            words = instant.split()
            for i, word in enumerate(words):
                yield word + (" " if i < len(words) - 1 else "")
            return
        yield from ask_ai_streaming_parallel(text)


# =============================================================================
# MULTI-TENANT LLM FUNCTIONS
# These functions accept explicit agent configuration instead of using globals
# =============================================================================

def get_context_for_agent(query: str, kb_id: Optional[str]) -> str:
    """Get RAG context for a specific agent's knowledge base.
    
    Args:
        query: User query to search for
        kb_id: Agent's active knowledge base ID (ChromaDB collection)
    
    Returns:
        Context string from knowledge base, or empty string if no KB/no match
    """
    if not kb_id:
        return ""
    
    try:
        from app.services.vector_store import search_knowledge_by_id
        results = search_knowledge_by_id(query, kb_id, n_results=2)
        if results:
            return "\n\n".join(results)
    except Exception as e:
        print(f"   ⚠️ RAG error for KB {kb_id}: {e}")
    
    return ""


def ask_ai_streaming_for_agent(
    text: str,
    system_prompt: str,
    history: List[Dict[str, str]],
    kb_id: Optional[str] = None,
    max_tokens: int = 300
) -> Generator[str, None, None]:
    """
    Stream LLM response for a specific agent configuration.
    
    MULTI-TENANT VERSION: Uses explicit parameters instead of global state.
    
    Args:
        text: User's current message
        system_prompt: Agent's system prompt (already resolved with variables)
        history: Conversation history for this call
        kb_id: Agent's active knowledge base ID for RAG
        max_tokens: Maximum tokens for response
    
    Yields:
        Tokens from the LLM response stream
    """
    import time
    start_time = time.time()
    
    # Special handling for agent-first opening message
    if text == "START_CONVERSATION":
        text = "Begin the conversation with your opening script. Say only the opening greeting - do not continue beyond asking if you are speaking to the right person."
    
    context = ""
    
    if not should_skip_rag(text) and kb_id:
        # Try RAG - get context from agent's knowledge base
        print(f"   🔍 Searching agent KB: {kb_id}")
        
        rag_result = [None]
        rag_done = threading.Event()
        
        def fetch_rag():
            rag_start = time.time()
            try:
                rag_result[0] = get_context_for_agent(text, kb_id)
                rag_time = (time.time() - rag_start) * 1000
                if rag_result[0]:
                    print(f"   📚 RAG found context ({rag_time:.0f}ms): {rag_result[0][:100]}...")
                else:
                    print(f"   📭 No relevant context found in agent KB ({rag_time:.0f}ms)")
            except Exception as e:
                print(f"   ⚠️ RAG error: {e}")
                rag_result[0] = ""
            finally:
                rag_done.set()
        
        threading.Thread(target=fetch_rag, daemon=True).start()
        rag_done.wait(timeout=3.0)  # Wait max 3 seconds for RAG
        
        if rag_done.is_set() and rag_result[0]:
            context = rag_result[0]
            print(f"   ✅ Using RAG context: {len(context)} chars")
        elif not rag_done.is_set():
            print(f"   ⏰ RAG timeout - proceeding without context")
    elif should_skip_rag(text):
        print(f"   ⏩ Skipping RAG (simple query)")
    
    # Build messages using agent-specific configuration
    messages = build_prompt_for_agent(
        user_query=text,
        system_prompt=system_prompt,
        history=history,
        context=context
    )
    
    # Stream LLM response
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.1,
        top_p=0.9,
        stream=True
    )
    
    for chunk in response:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
